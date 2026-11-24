"""Public forum intelligence parser and live search adapters for HalalLens.

Self-contained module (stdlib + httpx) providing:
- Deterministic negation-aware forum post parsing (ingredients, determination,
  evidence tier, freshness bucket, non-U.S. region guard, clean excerpting)
- Consensus aggregation and conflict detection matching API_CONTRACT.md
- Timeout-guarded public Reddit search adapter with graceful offline/429 handling
- Pluggable web forum search interface with optional Brave Search API support
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_REDDIT_SUBREDDITS: list[str] = [
    "halal",
    "MuslimLounge",
    "vegetarian",
    "Costco",
    "traderjoes",
]
REDDIT_SEARCH_URL = "https://www.reddit.com/r/{subreddit}/search.json"
BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_USER_AGENT = "HalalLens-Prototype/1.0 (U.S. Halal Ingredient Research; read-only)"
DEFAULT_FORUM_TIMEOUT_SECONDS = 4.0
MAX_EXCERPT_LENGTH = 600

# Canonical U.S. mushbooh/haram ingredients and their search aliases.
CANONICAL_INGREDIENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "enzymes",
        (
            r"enzymes?",
            r"rennet",
            r"animal\s+rennet",
            r"calf\s+rennet",
            r"bovine\s+rennet",
            r"porcine\s+rennet",
            r"microbial\s+rennet",
            r"vegetarian\s+rennet",
            r"vegetable\s+rennet",
            r"microbial\s+enzymes?",
            r"animal\s+enzymes?",
            r"fungal\s+enzymes?",
            r"cheese\s+enzymes?",
            r"chymosin",
            r"fermentation[- ]produced\s+chymosin",
            r"fpc",
            r"pepsin",
            r"lipase",
            r"protease",
        ),
    ),
    (
        "cheese culture",
        (
            r"cheese\s+cultures?",
            r"bacterial\s+cultures?",
            r"starter\s+cultures?",
            r"lactic\s+cultures?",
            r"dairy\s+cultures?",
        ),
    ),
    (
        "whey",
        (
            r"whey(?:\s+protein(?:\s+(?:concentrate|isolate))?|\s+powder|\s+permeate)?",
            r"sweet\s+whey",
            r"modified\s+whey",
        ),
    ),
    (
        "mono- and diglycerides",
        (
            r"mono-?\s*(?:and|&)\s*diglycerides",
            r"mono-?diglycerides",
            r"monoglycerides",
            r"diglycerides",
            r"e471",
            r"datem",
        ),
    ),
    (
        "pork gelatin",
        (
            r"(?:pork|porcine|pig)(?:[- ]derived)?\s+gelatine?",
            r"gelatine?\s+(?:from|derived\s+from)\s+(?:pork|porcine|pigs?)",
        ),
    ),
    (
        "gelatin",
        (
            r"gelatine?",
            r"(?:bovine|beef|fish|kosher|animal)(?:[- ]derived)?\s+gelatine?",
        ),
    ),
    (
        "carmine",
        (
            r"carmine",
            r"cochineal(?:\s+extract)?",
            r"carminic\s+acid",
            r"crimson\s+lake",
            r"natural\s+red\s+4",
            r"e120",
        ),
    ),
    (
        "lard",
        (
            r"lard",
            r"(?:rendered\s+)?pork\s+fat",
        ),
    ),
    (
        "L-cysteine",
        (
            r"l[- ]?cysteine",
            r"cysteine",
            r"e920",
        ),
    ),
    (
        "glycerin",
        (
            r"glycerine?",
            r"glycerol",
            r"(?:vegetable|animal)\s+glycerine?",
            r"e422",
        ),
    ),
    (
        "natural flavors",
        (
            r"natural\s+(?:and\s+artificial\s+|&\s+artificial\s+)?flavou?rings?",
            r"natural\s+(?:and\s+artificial\s+|&\s+artificial\s+)?flavou?rs?",
        ),
    ),
    (
        "confectioner's glaze",
        (
            r"confectioner'?s'?\s+glaze",
            r"shellac",
            r"resinous\s+glaze",
            r"pharmaceutical\s+glaze",
            r"lac\s+resin",
            r"e904",
        ),
    ),
    (
        "vitamin D3",
        (
            r"vitamin\s+d-?3",
            r"cholecalciferol",
            r"lanolin",
        ),
    ),
    (
        "sodium stearoyl lactylate",
        (
            r"sodium\s+stearoyl\s+lactylate",
            r"calcium\s+stearoyl\s+lactylate",
            r"stearoyl\s+lactylate",
            r"e481",
            r"e482",
        ),
    ),
    (
        "vanilla extract",
        (
            r"(?:pure\s+)?vanilla(?:\s+bean)?\s+extract",
            r"imitation\s+vanilla",
        ),
    ),
    (
        "alcohol / wine",
        (
            r"(?<!sugar\s)alcohol",
            r"ethanol",
            r"ethyl\s+alcohol",
            r"(?:red|white|cooking|rice)?\s*wine(?:\s+vinegar)?",
            r"sherry",
            r"bourbon",
            r"rum",
            r"beer",
            r"liqueur",
            r"brandy",
            r"mirin",
            r"sake",
        ),
    ),
)

_COMPILED_INGREDIENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (
        canonical,
        re.compile(
            r"(?<![a-z0-9])(?:" + "|".join(patterns) + r")(?![a-z0-9])",
            re.IGNORECASE,
        ),
    )
    for canonical, patterns in CANONICAL_INGREDIENT_PATTERNS
)

# --- Determination extraction patterns ---

_SUPPLIER_VARIABILITY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pat, re.IGNORECASE)
    for pat in (
        r"\bvar(?:y|ies|ying)\s+by\s+(?:the\s+)?(?:supplier|plant|facility|location|lot|batch|region|store|manufacturer|co-?packer|vendor)\b",
        r"\bdepend(?:s|ing)?\s+(?:on|upon)\s+(?:the\s+)?(?:supplier|plant|facility|location|lot|batch|availability|season|vendor)\b",
        r"\b(?:could|can|may|might)\s+(?:be|come\s+from|originate\s+from)\s+(?:either\s+)?(?:plant|vegetable|microbial|synthetic)\s+or\s+animal\b",
        r"\b(?:could|can|may|might)\s+(?:be|come\s+from|originate\s+from)\s+(?:either\s+)?animal\s+or\s+(?:plant|vegetable|microbial|synthetic)\b",
        r"\beither\s+(?:animal|beef|pork)\s+or\s+(?:vegetable|plant|microbial|synthetic)\b",
        r"\beither\s+(?:vegetable|plant|microbial|synthetic)\s+or\s+(?:animal|beef|pork)\b",
        r"\bboth\s+(?:animal|beef|pork)\s+and\s+(?:microbial|plant|vegetable|synthetic)\b",
        r"\bboth\s+(?:microbial|plant|vegetable|synthetic)\s+and\s+(?:animal|beef|pork)\b",
        r"\b(?:plant|vegetable|microbial)\s*(?:/|and/or)\s*animal\b",
        r"\banimal\s*(?:/|and/or)\s*(?:plant|vegetable|microbial)\b",
        r"\b(?:cannot|can'?t|unable\s+to)\s+guarantee\s+(?:the\s+)?(?:source|origin|animal|plant|microbial)\b",
        r"\bmultiple\s+suppliers\b",
        r"\bdifferent\s+suppliers\b",
        r"\bsourced\s+from\s+(?:multiple|different|various)\s+suppliers\b",
        r"\bsometimes\s+(?:animal|microbial|plant)[^.;!?]{0,40}\bsometimes\s+(?:microbial|plant|animal)\b",
        r"\bchanges?\s+(?:by|from|depending\s+on)\s+(?:supplier|batch|lot|plant)\b",
        r"\bsubject\s+to\s+change\s+(?:by|depending\s+on)\s+supplier\b",
    )
)

# Guard phrases that must NOT trigger "not halal" -> animal_or_haram.
_HALAL_CERT_DISCLAIMER_PATTERN = re.compile(
    r"\b(?:not|isn'?t|is\s+not|are\s+not|aren'?t|no)\s+"
    r"(?:officially\s+|formally\s+)?(?:halal[- ]certified|certified\s+halal|halal\s+certification)\b",
    re.IGNORECASE,
)

# Phrases indicating a sentence/clause is reporting a question rather than an answer.
_INQUIRY_CLAUSE_PATTERN = re.compile(
    r"(?:^\s*(?:does|do|is|are|has|have|can\s+anyone|anyone\s+know|does\s+anyone|wondering\s+if|curious\s+if|question\s*:|q\s*:)\b"
    r"|\b(?:asking|asked|inquired|emailed\s+(?:them\s+)?to\s+ask|called\s+(?:them\s+)?to\s+ask|wrote\s+to\s+ask|checking|check)\s+(?:them\s+)?(?:if|whether)\b)",
    re.IGNORECASE,
)

# Historical/superseded phrasing so old formulations don't poison current status.
_HISTORICAL_CLAUSE_PATTERN = re.compile(
    r"\b(?:used\s+to\s+(?:use|contain|have|include)|previously\s+(?:used|contained)|formerly\s+(?:used|contained))\b",
    re.IGNORECASE,
)

# Explicit negation of animal/haram sources within a declarative clause.
# Uses a bounded span that stops before finite clause restarts ("it uses", "they use").
_ANIMAL_TARGET_CORE = (
    r"(?:animal[- ]?(?:derived|based|sourced|rennet|enzymes?|gelatine?|fat|ingredients?|products?|origin|by-?products?)"
    r"|pork(?:[- ]derived)?(?:\s+gelatine?|\s+rennet|\s+fat)?"
    r"|porcine(?:\s+gelatine?|\s+rennet)?"
    r"|pig(?:\s+gelatine?)?"
    r"|swine"
    r"|lard"
    r"|calf\s+rennet"
    r"|bovine\s+(?:rennet|gelatine?)"
    r"|beef\s+(?:tallow|gelatine?|fat|rennet)"
    r"|tallow"
    r"|carmine"
    r"|cochineal"
    r"|pepsin"
    r"|meat)"
)

_NEGATED_ANIMAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:no|not|never|zero|without|free\s+of|free\s+from|doesn'?t|does\s+not|do\s+not|don'?t|"
        r"didn'?t|did\s+not|isn'?t|is\s+not|aren'?t|are\s+not|none\s+of|neither|no\s+longer|"
        r"stopped\s+using|eliminated|removed|switched\s+away\s+from|avoid(?:s|ing)?)\b"
        r"(?:(?!(?:,\s*(?:uses?|contains?|includes?|has)\b|\b(?:it|they|this|that|product|company|brand)\s+(?:uses?|using|contains?|has|have|is|are|includes?)\b))[^.;!?]){0,120}"
        + r"\b"
        + _ANIMAL_TARGET_CORE
        + r"\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bnon[- ]animal(?:\s+(?:enzymes?|rennet|derived|sourced|based|ingredients?))?\b", re.IGNORECASE),
    re.compile(r"\b(?:pork|porcine|animal|gelatine?|lard|carmine)[- ]free\b", re.IGNORECASE),
)

# Negation of microbial/vegetarian claims (prevents false plant_or_microbial).
_NEGATED_PLANT_HARD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:not|isn'?t|is\s+not|are\s+not|aren'?t|does\s+not\s+use|doesn'?t\s+use|do\s+not\s+use|don'?t\s+use|no\s+longer\s+uses?)\s+"
        r"(?:suitable\s+for\s+)?(?:vegetarian|microbial(?:\s+(?:enzymes?|rennet))?|non[- ]animal)\b",
        re.IGNORECASE,
    ),
)

_NEGATED_PLANT_SOFT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:not|isn'?t|is\s+not|are\s+not|aren'?t)\s+"
        r"(?:100%\s+)?(?:vegan|plant[- ]?based|plant[- ]?derived|vegetable[- ]?derived|synthetic)\b",
        re.IGNORECASE,
    ),
)

_POSITIVE_PLANT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pat, re.IGNORECASE)
    for pat in (
        r"\bmicrobial\s+(?:enzymes?|rennet|chymosin|source|origin)\b",
        r"\bmicrobial[- ]derived\b",
        r"\b(?:enzymes?|rennet|cultures?)\s+(?:are|is)\s+(?:100%\s+|all\s+|purely\s+|strictly\s+|solely\s+|exclusively\s+)?(?:microbial|vegetarian|vegan|plant[- ]?(?:based|derived)|vegetable[- ]?(?:based|derived)|fungal|non[- ]animal|synthetic)\b",
        r"\b(?:uses?|using|only|purely)\s+(?:100%\s+)?(?:microbial|vegetarian|vegetable|fungal|non[- ]animal)\s+(?:enzymes?|rennet)\b",
        r"\bvegetarian\s+(?:rennet|enzymes?)\b",
        r"\bvegetable\s+(?:rennet|enzymes?|glycerine?)\b",
        r"\bvegetable[- ]?(?:derived|based|sourced)\b",
        r"\bplant[- ]?(?:based|derived|sourced)\b",
        r"\b100%\s*(?:plant|vegetable|microbial|vegetarian|vegan|non[- ]animal)\b",
        r"\b(?:from|derived\s+from|sourced\s+from|made\s+from)\s+(?:100%\s+)?(?:plants?|vegetables?|soy|palm|corn|rapeseed|canola|microbes?|fungi|fungus|fermentation)\b",
        r"\bfermentation[- ]produced\s+chymosin\b",
        r"\bfpc\b",
        r"\bfungal\s+(?:enzymes?|rennet)\b",
        r"\bsynthetic(?:ally)?(?:\s+(?:derived|produced|sourced|made))?\b",
        r"\bsuitable\s+for\s+vegetarians\b",
        r"\bcertified\s+vegan\b",
        r"\b(?:is|are|confirmed|100%)\s+vegan\b",
        r"\b(?:is|are|confirmed|certified)\s+halal\b",
        r"\bhalal[- ]certified\b",
    )
)

_POSITIVE_ANIMAL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pat, re.IGNORECASE)
    for pat in (
        r"\bporcine\s+gelatine?\b",
        r"\bpork(?:[- ]derived)?\s+gelatine?\b",
        r"\banimal\s+rennet\b",
        r"\bcalf\s+rennet\b",
        r"\bbovine\s+rennet\b",
        r"\bporcine\s+rennet\b",
        r"\bpork\s+rennet\b",
        r"\bpepsin\b",
        r"\bbeef\s+tallow\b",
        r"\blard\b",
        r"\bcarmine\b",
        r"\bcochineal\b",
        r"\bcontains?\s+(?:[a-z0-9-]+\s+){0,3}(?:animal[- ]derived|animal\s+enzymes?|animal\s+rennet|animal\s+gelatine?|porcine|pork|beef\s+gelatine?|bovine\s+gelatine?|lard|tallow|carmine|cochineal)\b",
        r"\buses?\s+(?:[a-z0-9-]+\s+){0,3}(?:animal[- ]derived|animal\s+enzymes?|animal\s+rennet|calf\s+rennet|porcine|pork|beef\s+gelatine?|bovine\s+gelatine?|lard|tallow|carmine|cochineal)\b",
        r"\b(?:derived|sourced|made)\s+from\s+(?:pork|porcine|pigs?|swine|beef|bovine|calf|animals?|insects?|beetles?)\b",
        r"\b(?:animal|pork|porcine|beef|bovine)[- ]derived\b",
        r"\b(?:enzymes?|rennet|gelatine?|glycerine?|mono-?\s*(?:and|&)\s*diglycerides)\s+(?:are|is)\s+(?:from\s+)?(?:animal|pork|porcine|beef|bovine|calf)(?:\s+(?:source|origin|based|derived))?\b",
        r"\bnot\s+halal\b",
        r"\b(?:is|are|it'?s|confirmed|definitely|actually|clearly|considered|therefore|so)\s+(?:still\s+)?haram\b",
        r"\bharam\s+(?:because|due\s+to|ingredient)\b",
    )
)

# --- Evidence tier patterns ---

_SOCIAL_FORUM_DOMAINS = frozenset(
    {
        "reddit.com",
        "old.reddit.com",
        "www.reddit.com",
        "facebook.com",
        "www.facebook.com",
        "instagram.com",
        "www.instagram.com",
        "tiktok.com",
        "www.tiktok.com",
        "twitter.com",
        "x.com",
        "quora.com",
        "www.quora.com",
        "youtube.com",
        "www.youtube.com",
    }
)

_BRAND_FAQ_URL_KEYWORDS = (
    "/faq",
    "/frequently-asked",
    "/halal",
    "/ingredients",
    "/allergen",
    "/dietary",
    "/nutrition",
    "/product-info",
    "/help-center",
    "/support",
)

_OFFICIAL_FAQ_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pat, re.IGNORECASE)
    for pat in (
        r"\bofficial\s+(?:brand\s+|company\s+)?faq\b",
        r"\bbrand\s+faq\b",
        r"\bmanufacturer(?:'s)?\s+(?:official\s+)?(?:website|faq|statement|policy)\b",
        r"\bofficial\s+(?:brand|company)\s+(?:website|statement|policy)\b",
        r"\bfrom\s+their\s+official\s+(?:website|faq)\b",
        r"\bbrand\s+policy\s+page\b",
    )
)

_QUOTED_REPLY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pat, re.IGNORECASE)
    for pat in (
        r"\bi\s+(?:emailed|called|contacted|reached\s+out|messaged|chatted\s+with|wrote\s+to)\b",
        r"\bwe\s+(?:emailed|called|contacted|reached\s+out)\b",
        r"\bcustomer\s+(?:service|support|care|relations)\b",
        r"\bconsumer\s+(?:relations|affairs|service|care)\b",
        r"\bguest\s+relations\b",
        r"\bsupport\s+replied\b",
        r"\b(?:they|company|brand|manufacturer|kraft|nabisco|kellogg'?s?|general\s+mills|frito[- ]lay|nestle|pepsico|mondelez|hershey'?s?|mars|trader\s+joe'?s?|costco|kirkland)\s+(?:emailed|wrote|replied|responded|confirmed|said)\s+back\b",
        r"\bemailed\s+back\b",
        r"\bwrote\s+back\b",
        r"\breplied\s+back\b",
        r"\btheir\s+(?:response|reply|email)\b",
        r"\bcompany\s+confirmed\b",
        r"\bmanufacturer\s+confirmed\b",
        r"\bbrand\s+confirmed\b",
        r"\bhere\s*(?:is|'s)\s+(?:their|the)\s+(?:reply|response|email)\b",
        r"\bverbatim\b",
        r"\bspoke\s+(?:with|to)\s+a\s+(?:rep|representative|agent)\b",
        r"\b(?:rep|representative|agent)\s+(?:told\s+me|said|confirmed|replied)\b",
        r"\bgot\s+(?:an?\s+)?(?:email|reply|response)\s+(?:back|from)\b",
        r"\breceived\s+(?:an?\s+)?(?:email|reply|response)\s+from\b",
        r"\bconfirmed\s+(?:via|by)\s+(?:email|phone|chat)\b",
        r"\bcalled\s+[a-z][a-z0-9'&-]{1,25}\s+(?:about|regarding|to\s+ask|and)\b",
        r"\bemailed\s+[a-z][a-z0-9'&-]{1,25}\s+(?:about|regarding|to\s+ask|and)\b",
    )
)

# --- Region guard patterns ---

# Guard "turkey" against poultry meat references while matching country/version mentions.
_TURKEY_MEAT_PATTERN = re.compile(
    r"\b(?:ground|roast(?:ed)?|smoked|sliced|deli|raw|cooked|baked|white|dark|wild|halal|zabiha)\s+turkey\b"
    r"|\bturkey\s+(?:bacon|breast|sausage|meat|broth|stock|ham|pepperoni|jerky|sandwich|burger|patty|lunch\s*meat|deli|franks?|hot\s*dogs?|fat|flavor(?:ing)?|gravy|chili|soup)\b",
    re.IGNORECASE,
)

_NON_US_REGION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "UK",
        re.compile(
            r"(?:\buk\b|\bu\.k\.|\bunited\s+kingdom\b|\bbritain\b|\bbritish\b|\bengland\b|"
            r"\btesco\b|\basda\b|\bsainsbury'?s?\b|\bmorrisons\b|\bwaitrose\b|\.co\.uk\b|/en-gb/)",
            re.IGNORECASE,
        ),
    ),
    (
        "Canada",
        re.compile(
            r"(?:\bcanada\b|\bcanadian\b|\bontario\b|\btoronto\b|\bquebec\b|\bmontreal\b|\bvancouver\b|"
            r"\bloblaws\b|\bno\s+frills\b|\bwalmart\s+canada\b|\bcostco\s+canada\b|\bsobeys\b|"
            r"\bshoppers\s+drug\s+mart\b|/en-ca/|\.ca(?:/|$))",
            re.IGNORECASE,
        ),
    ),
    (
        "Europe/EU",
        re.compile(
            r"(?:\beu\b|\be\.u\.|\beurope\b|\beuropean\b|\bfrance\b|\bnetherlands\b|\bcarrefour\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "Germany",
        re.compile(r"(?:\bgermany\b|\bgerman\b|\brewe\b|\bedeka\b|\.de(?:/|$))", re.IGNORECASE),
    ),
    (
        "Turkey",
        re.compile(r"(?:\bturkey\b|\bturkish\b|\btürkiye\b|\bistanbul\b)", re.IGNORECASE),
    ),
    (
        "Australia",
        re.compile(
            r"(?:\baustralia\b|\baustralian\b|\bwoolworths\b|\bcoles\b|\.com\.au\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "Malaysia",
        re.compile(r"(?:\bmalaysia\b|\bmalaysian\b|\bjakim\b)", re.IGNORECASE),
    ),
    (
        "Indonesia",
        re.compile(r"(?:\bindonesia\b|\bindonesian\b|\bmui\b)", re.IGNORECASE),
    ),
)

_US_REGION_PATTERN = re.compile(
    r"(?:\bu\.s\.a?\.?(?!\w)|\busa\b|\bunited\s+states\b|\bus\s+version\b|\bus\s+market\b|"
    r"\bus\s+product\b|\bus\s+distribution\b|\bus\s+formula(?:tion)?\b|\bus\s+stores?\b|"
    r"\bus\s+customer\s+service\b|(?:\(us\)|\[us\])|"
    r"\bin\s+the\s+us\b|\bmade\s+in\s+(?:the\s+)?us\b|\bamerica\b|\bamerican\b|"
    r"\busda\b|\bfda\b|\bcostco\s+us\b|\btrader\s+joe'?s?\b|\bkroger\b|"
    r"\bwalmart\s+us\b|\bkraft\s+heinz\s+us\b|\bwhole\s+foods\b|\bpublix\b|\bsafeway\b|\bwegmans\b|"
    r"\btarget\b(?!\s+(?:audience|market|date|price|range|group|demographic)))",
    re.IGNORECASE,
)

_UPPERCASE_US_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z])US(?![A-Za-z])")
_PRONOUN_PRECEDING_WORDS = frozenset(
    {
        "contact",
        "email",
        "call",
        "tell",
        "told",
        "let",
        "ask",
        "asked",
        "give",
        "help",
        "join",
        "about",
        "with",
        "for",
        "sent",
        "send",
        "show",
    }
)


def _has_uppercase_us_reference(text: str) -> bool:
    """Detect standalone uppercase 'US' in mixed-case text without matching pronoun 'us'."""
    if not any(ch.islower() for ch in text):
        return False
    for match in _UPPERCASE_US_TOKEN_PATTERN.finditer(text):
        prefix = text[: match.start()].rstrip()
        prev_words = re.findall(r"[A-Za-z]+", prefix)
        prev_word = prev_words[-1].lower() if prev_words else ""
        if prev_word not in _PRONOUN_PRECEDING_WORDS:
            return True
    return False

# --- Search keyword expansion for Reddit/Web queries ---

_INGREDIENT_SEARCH_HINTS: dict[str, tuple[str, ...]] = {
    "enzymes": ("enzymes", "rennet"),
    "cheese culture": ("enzymes", "culture"),
    "whey": ("whey", "enzymes"),
    "mono- and diglycerides": ("diglycerides", "emulsifier"),
    "gelatin": ("gelatin",),
    "pork gelatin": ("gelatin", "pork"),
    "carmine": ("carmine", "cochineal"),
    "lard": ("lard",),
    "L-cysteine": ("cysteine",),
    "glycerin": ("glycerin",),
    "natural flavors": ("natural flavors",),
    "confectioner's glaze": ("shellac", "glaze"),
    "vitamin D3": ("vitamin D3", "lanolin"),
    "sodium stearoyl lactylate": ("stearoyl lactylate",),
    "vanilla extract": ("vanilla", "alcohol"),
    "alcohol / wine": ("alcohol", "wine"),
}


@dataclass
class ParsedForumSignal:
    """Structured intelligence signal extracted from a public forum thread or pasted post."""

    source_platform: str
    source_name: str
    url: str | None
    title: str
    author: str | None
    posted_at: str | None
    raw_excerpt: str
    matched_ingredients: list[str]
    claimed_determination: str
    evidence_tier: str
    freshness: str
    region_flag: str
    region_notes: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceCheckStatus:
    """Execution status of a single public forum source queried during scanning."""

    source: str
    status: str
    matched_count: int
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _parse_date_flexible(date_str: str | None) -> date | None:
    """Parse ISO dates, ISO timestamps, common human dates, or Unix epoch strings."""
    if not date_str:
        return None
    cleaned = str(date_str).strip()
    if not cleaned:
        return None

    # ISO date prefix (handles YYYY-MM-DD and YYYY-MM-DDTHH:MM:SSZ / offsets)
    iso_match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T\s].*)?$", cleaned)
    if iso_match:
        try:
            return date(
                int(iso_match.group(1)),
                int(iso_match.group(2)),
                int(iso_match.group(3)),
            )
        except ValueError:
            return None

    # Unix epoch timestamp string
    if re.fullmatch(r"\d{9,10}(?:\.\d+)?", cleaned):
        try:
            return datetime.fromtimestamp(float(cleaned), tz=timezone.utc).date()
        except (ValueError, OSError, OverflowError):
            return None

    # Common date formats
    for fmt in (
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%Y-%m",
    ):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    return None


def _compute_freshness(
    posted_at: str | None,
    reference_date: date | None = None,
) -> str:
    parsed = _parse_date_flexible(posted_at)
    if parsed is None:
        return "unknown"
    ref = reference_date or date.today()
    age_days = (ref - parsed).days
    if age_days < 365:
        return "recent"
    if age_days <= 730:
        return "aging"
    return "stale"


def _extract_ingredients(
    text: str,
    tracked_ingredients: list[str] | None = None,
) -> list[str]:
    matched: list[str] = []

    for canonical, pattern in _COMPILED_INGREDIENT_PATTERNS:
        if pattern.search(text):
            matched.append(canonical)

    if tracked_ingredients:
        lower_existing = {item.lower() for item in matched}
        for raw_tracked in tracked_ingredients:
            cleaned = (raw_tracked or "").strip()
            if not cleaned or cleaned.lower() in lower_existing:
                continue
            escaped = re.escape(cleaned)
            if re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text, re.IGNORECASE):
                matched.append(cleaned)
                lower_existing.add(cleaned.lower())

    return matched


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences while retaining trailing punctuation (?, !, .)."""
    if not text:
        return []
    raw_lines = [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]
    sentences: list[str] = []
    for line in raw_lines:
        parts = re.split(r"(?<=[.!?])\s+", line)
        for part in parts:
            stripped = part.strip()
            if stripped:
                sentences.append(stripped)
    return sentences


def _split_clauses(sentence: str) -> list[str]:
    """Split a sentence on strong contrast/pivot conjunctions so negations stay scoped."""
    parts = re.split(
        r"(?:;|,\s*(?:but|however|although|though|except|instead|only|whereas|while)\b|\s+(?:however|whereas|instead)\b|\s+[—–-]{1,2}\s+)",
        sentence,
        flags=re.IGNORECASE,
    )
    return [part.strip() for part in parts if part and part.strip()]


def _extract_determination(title: str, raw_text: str) -> str:
    """Deterministically classify claimed ingredient determination with negation awareness."""
    combined_parts = [part for part in (title, raw_text) if part and part.strip()]
    if not combined_parts:
        return "unclear"

    sentences = _split_sentences("\n".join(combined_parts))
    declarative_clauses: list[str] = []
    non_question_sentences: list[str] = []

    for sentence in sentences:
        is_question_sentence = sentence.rstrip().endswith("?")
        if not is_question_sentence:
            non_question_sentences.append(sentence)
        for clause in _split_clauses(sentence):
            if is_question_sentence or _INQUIRY_CLAUSE_PATTERN.search(clause):
                continue
            declarative_clauses.append(clause)

    # 1. Supplier variability check first (across non-question text)
    variability_text = " ".join(non_question_sentences)
    for pattern in _SUPPLIER_VARIABILITY_PATTERNS:
        if pattern.search(variability_text):
            return "varies_by_supplier"

    has_plant_or_microbial = False
    has_animal_or_haram = False

    # 2. Clause-level negation-aware classification
    for clause in declarative_clauses:
        is_historical = bool(_HISTORICAL_CLAUSE_PATTERN.search(clause))
        working = _HALAL_CERT_DISCLAIMER_PATTERN.sub(" [CERT_DISCLAIMER] ", clause)

        # Mask negated plant/microbial claims first so they don't count as plant_or_microbial
        for neg_plant_hard in _NEGATED_PLANT_HARD_PATTERNS:
            if neg_plant_hard.search(working):
                if not is_historical:
                    has_animal_or_haram = True
                working = neg_plant_hard.sub(" [NEGATED_PLANT] ", working)

        for neg_plant_soft in _NEGATED_PLANT_SOFT_PATTERNS:
            if neg_plant_soft.search(working):
                working = neg_plant_soft.sub(" [NEGATED_PLANT] ", working)

        # Handle explicit negations of animal/haram sources BEFORE positive animal checks
        for neg_animal in _NEGATED_ANIMAL_PATTERNS:
            if neg_animal.search(working):
                has_plant_or_microbial = True
                working = neg_animal.sub(" [NEGATED_ANIMAL] ", working)

        # Check positive plant/microbial/synthetic statements
        for pos_plant in _POSITIVE_PLANT_PATTERNS:
            if pos_plant.search(working):
                has_plant_or_microbial = True
                break

        # Check positive animal/haram statements on remaining unmasked declarative text
        if not is_historical:
            for pos_animal in _POSITIVE_ANIMAL_PATTERNS:
                if pos_animal.search(working):
                    has_animal_or_haram = True
                    break

    if has_animal_or_haram:
        return "animal_or_haram"
    if has_plant_or_microbial:
        return "plant_or_microbial"
    return "unclear"


def _is_official_brand_faq_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.netloc or "").lower()
    if not host:
        return False
    if host in _SOCIAL_FORUM_DOMAINS or any(
        host.endswith("." + domain) for domain in ("reddit.com", "facebook.com", "quora.com")
    ):
        return False
    path_and_query = f"{parsed.path}?{parsed.query}".lower()
    return any(keyword in path_and_query for keyword in _BRAND_FAQ_URL_KEYWORDS)


def _extract_evidence_tier(
    source_platform: str,
    source_name: str,
    url: str | None,
    title: str,
    raw_text: str,
) -> str:
    platform_lower = (source_platform or "").strip().lower()
    combined = f"{title}\n{raw_text}"

    if platform_lower in {"brand_faq", "official_faq", "manufacturer_faq", "brand_website"}:
        return "official_brand_faq"

    if _is_official_brand_faq_url(url):
        return "official_brand_faq"

    source_lower = (source_name or "").lower()
    if "official" in source_lower and ("faq" in source_lower or "brand" in source_lower):
        return "official_brand_faq"

    for pattern in _OFFICIAL_FAQ_TEXT_PATTERNS:
        if pattern.search(combined):
            return "official_brand_faq"

    for pattern in _QUOTED_REPLY_PATTERNS:
        if pattern.search(combined):
            return "quoted_company_reply"

    return "community_anecdote"


def _extract_region(
    title: str,
    raw_text: str,
    source_name: str = "",
    url: str | None = None,
) -> tuple[str, str | None]:
    combined = f"{title}\n{raw_text}\n{source_name}\n{url or ''}"
    # Strip poultry references so "turkey bacon" doesn't trigger country "Turkey".
    region_scan_text = _TURKEY_MEAT_PATTERN.sub(" ", combined)

    detected_non_us: list[str] = []
    for label, pattern in _NON_US_REGION_PATTERNS:
        if pattern.search(region_scan_text):
            detected_non_us.append(label)

    if detected_non_us:
        regions_str = ", ".join(detected_non_us)
        return (
            "non_us_warning",
            f"Mentions non-U.S. region/retailer ({regions_str}); non-U.S. formulations often differ from U.S. versions.",
        )

    source_lower = (source_name or "").lower()
    if (
        _US_REGION_PATTERN.search(combined)
        or _has_uppercase_us_reference(f"{title}\n{raw_text}")
        or "traderjoes" in source_lower
    ):
        return ("us", "References U.S. distribution/formulation")

    return ("unknown", None)


def _trim_excerpt(
    raw_text: str,
    title: str,
    matched_ingredients: list[str],
    max_len: int = MAX_EXCERPT_LENGTH,
) -> str:
    cleaned = _normalize_whitespace(raw_text)
    if not cleaned:
        cleaned = _normalize_whitespace(title)
    if len(cleaned) <= max_len:
        return cleaned

    sentences = _split_sentences(raw_text)
    if len(sentences) > 1:
        # Score sentences to keep high-signal statements (company replies, ingredients, determinations)
        scored: list[tuple[int, int, str]] = []
        ing_terms = [ing.lower() for ing in matched_ingredients]
        for idx, sent in enumerate(sentences):
            norm_sent = _normalize_whitespace(sent)
            if not norm_sent:
                continue
            score = 0
            lower_sent = norm_sent.lower()
            if idx == 0:
                score += 1
            if any(term in lower_sent for term in ing_terms):
                score += 3
            if any(p.search(norm_sent) for p in _QUOTED_REPLY_PATTERNS):
                score += 3
            if any(p.search(norm_sent) for p in _SUPPLIER_VARIABILITY_PATTERNS):
                score += 4
            if any(p.search(norm_sent) for p in _NEGATED_ANIMAL_PATTERNS):
                score += 3
            if any(p.search(norm_sent) for p in _POSITIVE_PLANT_PATTERNS):
                score += 2
            if any(p.search(norm_sent) for p in _POSITIVE_ANIMAL_PATTERNS):
                score += 3
            scored.append((score, idx, norm_sent))

        selected_indices: list[int] = []
        current_len = 0
        # Pick highest scoring sentences first while respecting budget, then restore reading order
        for score, idx, sent in sorted(scored, key=lambda x: (-x[0], x[1])):
            addition = len(sent) + (1 if selected_indices else 0)
            if current_len + addition <= max_len - 3:
                selected_indices.append(idx)
                current_len += addition
            elif not selected_indices:
                break

        if selected_indices:
            selected_indices.sort()
            ordered_sents = [_normalize_whitespace(sentences[i]) for i in selected_indices]
            joined = " ".join(ordered_sents)
            if len(selected_indices) < len(sentences) and not joined.endswith("..."):
                if len(joined) + 3 <= max_len:
                    joined = f"{joined}..."
            return joined

    # Fallback: clean word-boundary trim from start
    truncated = cleaned[: max_len - 3].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{truncated}..." if truncated else f"{cleaned[: max_len - 3]}..."


def parse_forum_post(
    title: str,
    raw_text: str,
    source_platform: str = "pasted",
    source_name: str = "User Pasted Thread",
    url: str | None = None,
    author: str | None = None,
    posted_at: str | None = None,
    reference_date: date | None = None,
    tracked_ingredients: list[str] | None = None,
) -> ParsedForumSignal:
    """Parse a public forum thread or pasted post into a structured ParsedForumSignal."""
    clean_title = _normalize_whitespace(title)
    combined_for_ingredients = f"{clean_title}\n{raw_text or ''}"

    matched_ingredients = _extract_ingredients(
        combined_for_ingredients,
        tracked_ingredients=tracked_ingredients,
    )
    claimed_determination = _extract_determination(clean_title, raw_text or "")
    evidence_tier = _extract_evidence_tier(
        source_platform=source_platform,
        source_name=source_name,
        url=url,
        title=clean_title,
        raw_text=raw_text or "",
    )
    freshness = _compute_freshness(posted_at, reference_date=reference_date)
    region_flag, region_notes = _extract_region(
        title=clean_title,
        raw_text=raw_text or "",
        source_name=source_name,
        url=url,
    )
    raw_excerpt = _trim_excerpt(
        raw_text=raw_text or "",
        title=clean_title,
        matched_ingredients=matched_ingredients,
    )

    normalized_posted_at: str | None = None
    parsed_date = _parse_date_flexible(posted_at)
    if parsed_date is not None:
        normalized_posted_at = parsed_date.isoformat()
    elif posted_at and str(posted_at).strip():
        normalized_posted_at = str(posted_at).strip()

    return ParsedForumSignal(
        source_platform=(source_platform or "pasted").strip(),
        source_name=(source_name or "User Pasted Thread").strip(),
        url=url.strip() if isinstance(url, str) and url.strip() else None,
        title=clean_title,
        author=author.strip() if isinstance(author, str) and author.strip() else None,
        posted_at=normalized_posted_at,
        raw_excerpt=raw_excerpt,
        matched_ingredients=matched_ingredients,
        claimed_determination=claimed_determination,
        evidence_tier=evidence_tier,
        freshness=freshness,
        region_flag=region_flag,
        region_notes=region_notes,
    )


def _get_signal_field(signal: dict[str, Any] | ParsedForumSignal, key: str, default: Any = None) -> Any:
    if isinstance(signal, dict):
        return signal.get(key, default)
    return getattr(signal, key, default)


def _normalize_determination_bucket(determination: str | None) -> str:
    det = (determination or "unclear").strip().lower()
    if det in ("plant_or_microbial", "synthetic"):
        return "plant_or_microbial"
    if det in ("varies_by_supplier", "animal_or_haram", "unclear"):
        return det
    return "unclear"


def aggregate_forum_consensus(signals: list[dict[str, Any] | ParsedForumSignal]) -> dict[str, Any]:
    """Aggregate forum signals into a ForumConsensus dict matching API_CONTRACT.md."""
    counts_by_determination: dict[str, int] = {
        "plant_or_microbial": 0,
        "varies_by_supplier": 0,
        "animal_or_haram": 0,
        "unclear": 0,
    }
    quoted_company_replies = 0
    official_brand_faqs = 0
    non_us_count = 0
    newest_date: date | None = None

    domestic_determinations: set[str] = set()
    quoted_by_det: dict[str, int] = {k: 0 for k in counts_by_determination}
    faq_by_det: dict[str, int] = {k: 0 for k in counts_by_determination}

    for sig in signals:
        det = _normalize_determination_bucket(_get_signal_field(sig, "claimed_determination", "unclear"))
        counts_by_determination[det] += 1

        tier = (_get_signal_field(sig, "evidence_tier", "community_anecdote") or "").strip().lower()
        if tier == "quoted_company_reply":
            quoted_company_replies += 1
            quoted_by_det[det] += 1
        elif tier == "official_brand_faq":
            official_brand_faqs += 1
            faq_by_det[det] += 1

        region = (_get_signal_field(sig, "region_flag", "unknown") or "unknown").strip().lower()
        if region == "non_us_warning":
            non_us_count += 1
        else:
            domestic_determinations.add(det)

        parsed_dt = _parse_date_flexible(_get_signal_field(sig, "posted_at"))
        if parsed_dt is not None and (newest_date is None or parsed_dt > newest_date):
            newest_date = parsed_dt

    has_domestic_plant = "plant_or_microbial" in domestic_determinations
    has_domestic_animal = "animal_or_haram" in domestic_determinations
    has_domestic_varies = "varies_by_supplier" in domestic_determinations

    has_conflict = bool(
        (has_domestic_plant and (has_domestic_animal or has_domestic_varies))
        or (has_domestic_animal and has_domestic_varies)
    )
    has_non_us_warning = non_us_count > 0
    total_signals = len(signals)

    def _evidence_suffix(det_key: str) -> str:
        notes: list[str] = []
        q_cnt = quoted_by_det[det_key]
        f_cnt = faq_by_det[det_key]
        if q_cnt > 0:
            notes.append(f"{q_cnt} quoted {'reply' if q_cnt == 1 else 'replies'}")
        if f_cnt > 0:
            notes.append(f"{f_cnt} brand {'FAQ' if f_cnt == 1 else 'FAQs'}")
        return f" ({', '.join(notes)})" if notes else ""

    # Build concise human-readable summary_line
    if total_signals == 0:
        summary_line = "No public forum signals recorded yet."
    else:
        clause_parts: list[str] = []

        pm = counts_by_determination["plant_or_microbial"]
        if pm > 0:
            verb = "reports" if pm == 1 else "report"
            clause_parts.append(f"{pm} {verb} plant/microbial{_evidence_suffix('plant_or_microbial')}")

        vs = counts_by_determination["varies_by_supplier"]
        if vs > 0:
            verb = "reports" if vs == 1 else "report"
            clause_parts.append(f"{vs} {verb} varies by supplier{_evidence_suffix('varies_by_supplier')}")

        ah = counts_by_determination["animal_or_haram"]
        if ah > 0:
            verb = "reports" if ah == 1 else "report"
            clause_parts.append(f"{ah} {verb} animal/haram{_evidence_suffix('animal_or_haram')}")

        uc = counts_by_determination["unclear"]
        if uc > 0:
            clause_parts.append(f"{uc} unclear")

        summary_segments = [", ".join(clause_parts)]
        if has_conflict:
            summary_segments.append("Conflicting reports")
        if non_us_count > 0:
            summary_segments.append(
                f"{non_us_count} non-U.S. {'thread' if non_us_count == 1 else 'threads'} flagged"
            )
        summary_line = " • ".join(summary_segments) + "."

    return {
        "total_signals": total_signals,
        "counts_by_determination": counts_by_determination,
        "quoted_company_replies": quoted_company_replies,
        "official_brand_faqs": official_brand_faqs,
        "has_conflict": has_conflict,
        "has_non_us_warning": has_non_us_warning,
        "non_us_count": non_us_count,
        "newest_post_date": newest_date.isoformat() if newest_date is not None else None,
        "summary_line": summary_line,
    }


def _normalize_url_key(url: str | None) -> str | None:
    if not url:
        return None
    cleaned = url.strip().lower()
    if not cleaned:
        return None
    try:
        parsed = urlparse(cleaned)
        host = parsed.netloc.removeprefix("www.").removeprefix("old.")
        path = parsed.path.rstrip("/")
        return f"{host}{path}"
    except ValueError:
        return cleaned.rstrip("/")


def _build_product_search_query(
    product_name: str,
    brand: str,
    flagged_ingredients: list[str],
    custom_query: str | None = None,
) -> str:
    """Build a concise, high-recall public forum search query."""
    if custom_query and custom_query.strip():
        return custom_query.strip()

    clean_brand = re.sub(r"[^\w\s'&-]", " ", brand or "").strip()
    clean_name = re.sub(r"\b\d+(?:\.\d+)?\s*(?:oz|lb|g|kg|ml|l|ct|pk|pack)\b", "", product_name or "", flags=re.IGNORECASE)
    clean_name = re.sub(r"[^\w\s'&-]", " ", clean_name).strip()
    clean_name = re.sub(r"\s+", " ", clean_name)

    # Avoid duplicating brand if already at start of product name
    if clean_brand and clean_name.lower().startswith(clean_brand.lower()):
        core_product = clean_name
    else:
        core_product = f"{clean_brand} {clean_name}".strip()

    # Trim overly long product names to the first 5 meaningful tokens
    product_tokens = [tok for tok in core_product.split() if tok.lower() not in {"dinner", "original", "classic", "family", "size"}]
    compact_product = " ".join(product_tokens[:5]) if product_tokens else core_product

    keyword_pool: list[str] = []
    for ing in flagged_ingredients or []:
        hints = _INGREDIENT_SEARCH_HINTS.get(ing) or _INGREDIENT_SEARCH_HINTS.get(ing.lower())
        if hints:
            for hint in hints:
                if hint not in keyword_pool:
                    keyword_pool.append(hint)
        else:
            token = ing.strip()
            if token and token not in keyword_pool:
                keyword_pool.append(token)
        if len(keyword_pool) >= 3:
            break

    if "halal" not in keyword_pool:
        keyword_pool.append("halal")

    or_clause = " OR ".join(keyword_pool[:4])
    if compact_product:
        return f"{compact_product} ({or_clause})"
    return or_clause


def _is_post_relevant(
    title: str,
    body: str,
    brand: str,
    product_name: str,
    flagged_ingredients: list[str],
) -> bool:
    """Filter out obviously unrelated or deleted/empty forum hits."""
    combined = f"{title} {body}".strip()
    if not combined:
        return False
    lower = combined.lower()
    if lower in {"[removed]", "[deleted]"}:
        return False

    brand_tokens = [
        tok for tok in re.findall(r"[a-z0-9']+", (brand or "").lower()) if len(tok) >= 3
    ]
    name_tokens = [
        tok
        for tok in re.findall(r"[a-z0-9']+", (product_name or "").lower())
        if len(tok) >= 4 and tok not in {"original", "dinner", "classic", "flavor", "flavored"}
    ]
    ingredient_tokens = [
        tok
        for ing in (flagged_ingredients or [])
        for tok in re.findall(r"[a-z0-9]+", ing.lower())
        if len(tok) >= 4
    ]
    halal_domain_tokens = (
        "halal",
        "haram",
        "mushbooh",
        "rennet",
        "enzyme",
        "gelatin",
        "microbial",
        "vegetarian",
        "vegan",
        "kosher",
        "porcine",
        "pork",
        "carmine",
        "shellac",
    )

    matches_product = any(tok in lower for tok in brand_tokens) or any(
        tok in lower for tok in name_tokens
    )
    matches_domain = any(tok in lower for tok in ingredient_tokens) or any(
        tok in lower for tok in halal_domain_tokens
    )
    return matches_product or matches_domain


class RedditForumAdapter:
    """Read-only Reddit public JSON search adapter targeting curated subreddits."""

    def __init__(
        self,
        subreddits: list[str] | None = None,
        timeout: float = DEFAULT_FORUM_TIMEOUT_SECONDS,
        user_agent: str = DEFAULT_USER_AGENT,
        limit_per_subreddit: int = 4,
        client: httpx.Client | None = None,
    ) -> None:
        self.subreddits = list(subreddits) if subreddits else list(DEFAULT_REDDIT_SUBREDDITS)
        self.timeout = timeout
        self.user_agent = user_agent
        self.limit_per_subreddit = limit_per_subreddit
        self._client = client

    def search(
        self,
        product_name: str,
        brand: str,
        flagged_ingredients: list[str],
        subreddits: list[str] | None = None,
        custom_query: str | None = None,
    ) -> tuple[list[ParsedForumSignal], list[SourceCheckStatus]]:
        target_subs = [
            sub.strip().removeprefix("r/").removeprefix("/r/")
            for sub in (subreddits if subreddits else self.subreddits)
            if sub and sub.strip()
        ]
        query = _build_product_search_query(
            product_name=product_name,
            brand=brand,
            flagged_ingredients=flagged_ingredients,
            custom_query=custom_query,
        )

        signals: list[ParsedForumSignal] = []
        statuses: list[SourceCheckStatus] = []
        seen_urls: set[str] = set()
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

        abort_reason: tuple[str, str] | None = None

        own_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout, follow_redirects=True)
        try:
            for sub in target_subs:
                source_label = f"r/{sub}"

                if abort_reason is not None:
                    abort_status, abort_detail = abort_reason
                    statuses.append(
                        SourceCheckStatus(
                            source=source_label,
                            status=abort_status,
                            matched_count=0,
                            detail=abort_detail,
                        )
                    )
                    continue

                url = REDDIT_SEARCH_URL.format(subreddit=sub)
                params = {
                    "q": query,
                    "restrict_sr": 1,
                    "sort": "relevance",
                    "t": "all",
                    "limit": self.limit_per_subreddit,
                }
                try:
                    response = client.get(url, params=params, headers=headers)
                except httpx.TimeoutException:
                    statuses.append(
                        SourceCheckStatus(
                            source=source_label,
                            status="timeout",
                            matched_count=0,
                            detail=f"Reddit search on {source_label} timed out after {self.timeout:.1f}s.",
                        )
                    )
                    continue
                except httpx.RequestError as exc:
                    detail = (
                        f"Reddit unreachable due to network error ({exc.__class__.__name__}); "
                        "skipping remaining live Reddit checks."
                    )
                    statuses.append(
                        SourceCheckStatus(
                            source=source_label,
                            status="offline",
                            matched_count=0,
                            detail=detail,
                        )
                    )
                    abort_reason = ("offline", "Skipped after network error reaching Reddit.")
                    continue

                if response.status_code == 429:
                    statuses.append(
                        SourceCheckStatus(
                            source=source_label,
                            status="rate_limited",
                            matched_count=0,
                            detail=f"Reddit returned HTTP 429 on {source_label} (rate limit exceeded).",
                        )
                    )
                    abort_reason = (
                        "rate_limited",
                        "Skipped after Reddit HTTP 429 rate limit.",
                    )
                    continue

                if response.status_code == 403:
                    statuses.append(
                        SourceCheckStatus(
                            source=source_label,
                            status="blocked",
                            matched_count=0,
                            detail=f"Reddit returned HTTP 403 (access blocked) for {source_label}.",
                        )
                    )
                    continue

                if response.status_code >= 400:
                    statuses.append(
                        SourceCheckStatus(
                            source=source_label,
                            status="error",
                            matched_count=0,
                            detail=f"Reddit returned HTTP {response.status_code} for {source_label}.",
                        )
                    )
                    continue

                try:
                    payload = response.json()
                except ValueError as exc:
                    statuses.append(
                        SourceCheckStatus(
                            source=source_label,
                            status="error",
                            matched_count=0,
                            detail=f"Invalid JSON returned from {source_label} ({exc}).",
                        )
                    )
                    continue

                children = (
                    payload.get("data", {}).get("children", [])
                    if isinstance(payload, dict)
                    else []
                )
                sub_matches = 0
                for child in children:
                    if not isinstance(child, dict):
                        continue
                    post = child.get("data")
                    if not isinstance(post, dict):
                        continue

                    post_title = str(post.get("title") or "").strip()
                    selftext = str(post.get("selftext") or "").strip()
                    if selftext in ("[removed]", "[deleted]"):
                        selftext = ""

                    if not _is_post_relevant(
                        post_title,
                        selftext,
                        brand=brand,
                        product_name=product_name,
                        flagged_ingredients=flagged_ingredients,
                    ):
                        continue

                    permalink = str(post.get("permalink") or "").strip()
                    post_url = (
                        f"https://www.reddit.com{permalink}"
                        if permalink.startswith("/")
                        else (str(post.get("url") or "").strip() or None)
                    )
                    url_key = _normalize_url_key(post_url)
                    if url_key and url_key in seen_urls:
                        continue
                    if url_key:
                        seen_urls.add(url_key)

                    raw_author = str(post.get("author") or "").strip()
                    if raw_author and raw_author not in ("[deleted]", "[removed]"):
                        author = raw_author if raw_author.startswith("u/") else f"u/{raw_author}"
                    else:
                        author = None

                    created_utc = post.get("created_utc")
                    posted_at: str | None = None
                    if isinstance(created_utc, (int, float)):
                        try:
                            posted_at = datetime.fromtimestamp(
                                float(created_utc), tz=timezone.utc
                            ).date().isoformat()
                        except (ValueError, OSError, OverflowError):
                            posted_at = None

                    parsed_signal = parse_forum_post(
                        title=post_title,
                        raw_text=selftext or post_title,
                        source_platform="reddit",
                        source_name=source_label,
                        url=post_url,
                        author=author,
                        posted_at=posted_at,
                        tracked_ingredients=flagged_ingredients,
                    )
                    signals.append(parsed_signal)
                    sub_matches += 1

                statuses.append(
                    SourceCheckStatus(
                        source=source_label,
                        status="ok" if sub_matches > 0 else "no_matches",
                        matched_count=sub_matches,
                        detail=(
                            f"Found {sub_matches} relevant thread(s) in {source_label} for query: {query}"
                            if sub_matches > 0
                            else f"No relevant threads matched in {source_label} for query: {query}"
                        ),
                    )
                )
        finally:
            if own_client:
                client.close()

        return signals, statuses


class BaseWebForumAdapter(ABC):
    """Abstract interface for pluggable public web/FAQ search providers."""

    source_name: str = "web_search"

    @abstractmethod
    def search(
        self,
        product_name: str,
        brand: str,
        flagged_ingredients: list[str],
        custom_query: str | None = None,
    ) -> tuple[list[ParsedForumSignal], SourceCheckStatus]:
        """Search external forums and brand FAQ pages and return parsed signals + status."""


class PluggableWebForumAdapter(BaseWebForumAdapter):
    """Pluggable web forum/FAQ search adapter backed by Brave Search API when configured.

    Reads ``WEB_SEARCH_API_KEY`` from the environment (or explicit constructor arg).
    Gracefully returns ``status="skipped_unconfigured"`` when no API key is set.
    """

    source_name = "web_search_brave"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = DEFAULT_FORUM_TIMEOUT_SECONDS,
        max_results: int = 5,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = (
            api_key
            if api_key is not None
            else (os.environ.get("WEB_SEARCH_API_KEY") or "").strip() or None
        )
        self.timeout = timeout
        self.max_results = max_results
        self._client = client

    def search(
        self,
        product_name: str,
        brand: str,
        flagged_ingredients: list[str],
        custom_query: str | None = None,
    ) -> tuple[list[ParsedForumSignal], SourceCheckStatus]:
        if not self.api_key:
            return (
                [],
                SourceCheckStatus(
                    source=self.source_name,
                    status="skipped_unconfigured",
                    matched_count=0,
                    detail=(
                        "Web forum & brand FAQ search skipped: set WEB_SEARCH_API_KEY "
                        "(Brave Search API token) to enable live web discovery."
                    ),
                ),
            )

        base_query = _build_product_search_query(
            product_name=product_name,
            brand=brand,
            flagged_ingredients=flagged_ingredients,
            custom_query=custom_query,
        )
        web_query = f"{base_query} (halal OR vegetarian OR FAQ OR rennet OR enzymes)"
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key,
            "User-Agent": DEFAULT_USER_AGENT,
        }
        params = {
            "q": web_query,
            "count": self.max_results,
            "country": "us",
            "search_lang": "en",
        }

        own_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            try:
                response = client.get(BRAVE_WEB_SEARCH_URL, params=params, headers=headers)
            except httpx.TimeoutException:
                return (
                    [],
                    SourceCheckStatus(
                        source=self.source_name,
                        status="timeout",
                        matched_count=0,
                        detail=f"Brave Search API timed out after {self.timeout:.1f}s.",
                    ),
                )
            except httpx.RequestError as exc:
                return (
                    [],
                    SourceCheckStatus(
                        source=self.source_name,
                        status="offline",
                        matched_count=0,
                        detail=f"Brave Search API unavailable ({exc.__class__.__name__}).",
                    ),
                )

            if response.status_code == 429:
                return (
                    [],
                    SourceCheckStatus(
                        source=self.source_name,
                        status="rate_limited",
                        matched_count=0,
                        detail="Brave Search API returned HTTP 429 (rate limit exceeded).",
                    ),
                )
            if response.status_code in (401, 403):
                return (
                    [],
                    SourceCheckStatus(
                        source=self.source_name,
                        status="auth_error",
                        matched_count=0,
                        detail=f"Brave Search API rejected WEB_SEARCH_API_KEY (HTTP {response.status_code}).",
                    ),
                )
            if response.status_code >= 400:
                return (
                    [],
                    SourceCheckStatus(
                        source=self.source_name,
                        status="error",
                        matched_count=0,
                        detail=f"Brave Search API returned HTTP {response.status_code}.",
                    ),
                )

            try:
                payload = response.json()
            except ValueError as exc:
                return (
                    [],
                    SourceCheckStatus(
                        source=self.source_name,
                        status="error",
                        matched_count=0,
                        detail=f"Brave Search API returned invalid JSON ({exc}).",
                    ),
                )

            results = (
                payload.get("web", {}).get("results", [])
                if isinstance(payload, dict)
                else []
            )
            signals: list[ParsedForumSignal] = []
            seen_urls: set[str] = set()

            for item in results:
                if not isinstance(item, dict):
                    continue
                res_url = str(item.get("url") or "").strip() or None
                url_key = _normalize_url_key(res_url)
                if url_key and url_key in seen_urls:
                    continue
                if url_key:
                    seen_urls.add(url_key)

                res_title = str(item.get("title") or "").strip()
                desc_parts = [str(item.get("description") or "").strip()]
                extra = item.get("extra_snippets")
                if isinstance(extra, list):
                    desc_parts.extend(str(s).strip() for s in extra if str(s).strip())
                body_text = " ".join(part for part in desc_parts if part)

                if not _is_post_relevant(
                    res_title,
                    body_text,
                    brand=brand,
                    product_name=product_name,
                    flagged_ingredients=flagged_ingredients,
                ):
                    continue

                host = urlparse(res_url).netloc.removeprefix("www.") if res_url else "Web Forum"
                platform = "brand_faq" if _is_official_brand_faq_url(res_url) else "web_forum"
                posted_at = str(item.get("page_age") or "").strip() or None

                signals.append(
                    parse_forum_post(
                        title=res_title,
                        raw_text=body_text or res_title,
                        source_platform=platform,
                        source_name=host or "Web Forum",
                        url=res_url,
                        author=None,
                        posted_at=posted_at,
                        tracked_ingredients=flagged_ingredients,
                    )
                )

            return (
                signals,
                SourceCheckStatus(
                    source=self.source_name,
                    status="ok" if signals else "no_matches",
                    matched_count=len(signals),
                    detail=(
                        f"Matched {len(signals)} web/FAQ result(s) via Brave Search."
                        if signals
                        else "No relevant web forum or brand FAQ pages matched via Brave Search."
                    ),
                ),
            )
        finally:
            if own_client:
                client.close()


_EVIDENCE_SORT_RANK = {
    "official_brand_faq": 0,
    "quoted_company_reply": 1,
    "community_anecdote": 2,
}

_REGION_SORT_RANK = {
    "us": 0,
    "unknown": 1,
    "non_us_warning": 2,
}


def scan_public_forums(
    product_name: str,
    brand: str,
    flagged_ingredients: list[str],
    include_live_reddit: bool = True,
    subreddits: list[str] | None = None,
    custom_query: str | None = None,
    *,
    reddit_adapter: RedditForumAdapter | None = None,
    web_adapter: BaseWebForumAdapter | None = None,
) -> tuple[list[ParsedForumSignal], list[SourceCheckStatus]]:
    """Run public forum scanning across Reddit and optional pluggable web search.

    Returns deduplicated, evidence-ranked ``ParsedForumSignal`` entries alongside
    per-source ``SourceCheckStatus`` diagnostics.
    """
    collected: list[ParsedForumSignal] = []
    statuses: list[SourceCheckStatus] = []

    if include_live_reddit:
        adapter = reddit_adapter or RedditForumAdapter()
        reddit_signals, reddit_statuses = adapter.search(
            product_name=product_name,
            brand=brand,
            flagged_ingredients=flagged_ingredients,
            subreddits=subreddits,
            custom_query=custom_query,
        )
        collected.extend(reddit_signals)
        statuses.extend(reddit_statuses)
    else:
        statuses.append(
            SourceCheckStatus(
                source="reddit",
                status="skipped",
                matched_count=0,
                detail="Live Reddit search disabled by caller.",
            )
        )

    active_web_adapter = web_adapter or PluggableWebForumAdapter()
    web_signals, web_status = active_web_adapter.search(
        product_name=product_name,
        brand=brand,
        flagged_ingredients=flagged_ingredients,
        custom_query=custom_query,
    )
    collected.extend(web_signals)
    statuses.append(web_status)

    # Deduplicate across adapters by normalized URL while keeping highest-ranked signal
    deduped: list[ParsedForumSignal] = []
    seen_url_keys: set[str] = set()
    for sig in collected:
        key = _normalize_url_key(sig.url)
        if key:
            if key in seen_url_keys:
                continue
            seen_url_keys.add(key)
        deduped.append(sig)

    # Sort U.S. signals first, then highest evidence tier, then newest post date
    deduped.sort(
        key=lambda s: (
            _REGION_SORT_RANK.get(s.region_flag, 1),
            _EVIDENCE_SORT_RANK.get(s.evidence_tier, 2),
            -(_parse_date_flexible(s.posted_at).toordinal() if _parse_date_flexible(s.posted_at) else 0),
        )
    )

    return deduped, statuses
