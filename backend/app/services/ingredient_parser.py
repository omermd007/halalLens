"""Deterministic ingredient label normalization, parsing, diffing, and rule matching."""

from __future__ import annotations

import hashlib
import re
from typing import Any

# Single-item parenthetical words/phrases treated as inline qualifiers rather than
# standalone sub-ingredient lists (e.g., "enzymes (microbial)", "gelatin (porcine)").
_INLINE_QUALIFIER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^(?:"
        r"microbial|non-?animal|animal-?free|vegetarian|vegan|plant(?:[- ]based|[- ]derived| source)?|"
        r"vegetable(?:[- ]derived| source)?|soy(?:[- ]derived)?|palm(?:[- ]derived)?|"
        r"coconut(?:[- ]derived)?|synthetic|fermentation[- ]produced|fpc|lichen|algae|"
        r"alcohol[- ]free|porcine|pork|bovine|beef|fish|kosher(?: fish)?|halal(?: beef| bovine)?|"
        r"animal|calf|lanolin|iron|zinc|calcium|vitamin\s+[a-z0-9]+|folate|folic acid|"
        r"color|for color|added for color|artificial color|natural color|"
        r"preservative|to preserve freshness|to maintain freshness|an emulsifier|emulsifier|"
        r"for flavor|antioxidant|anti-?caking agent|leavening|processing aid|"
        r"processed with alkali|source|cholecalciferol|ergocalciferol"
        r")$"
    ),
)

# Leading quantity/threshold boilerplate on U.S. FDA ingredient labels.
_LEADING_THRESHOLD_RE = re.compile(
    r"^(?:"
    r"contains\s+(?:less\s+than\s+\d+(?:\.\d+)?%|\d+(?:\.\d+)?%\s+or\s+less)\s+(?:of\s*:?\s*)?(?:the\s+following\s*)?:?\s*|"
    r"(?:less\s+than\s+\d+(?:\.\d+)?%|\d+(?:\.\d+)?%\s+or\s+less)\s+(?:of\s*:?\s*)?(?:the\s+following\s*)?:?\s*"
    r")"
)

# Allergen summary footer ("contains: milk, wheat, soy") distinct from "contains 2% or less of".
_ALLERGEN_FOOTER_RE = re.compile(r"^(?:allergen(?:s)?\s*:|contains\s*:)")

# Explicit safe source qualifiers for mushbooh ingredients (never overrides haram_animal).
_GENERAL_SAFE_QUALIFIER_RE = re.compile(
    r"(?<![a-z0-9])(?:"
    r"microbial|non-?animal|animal-?free|vegetarian|vegan|"
    r"plant[- ]based|plant[- ]derived|plant source|"
    r"vegetable[- ]derived|vegetable source|vegetable(?=\s+(?:mono|di|glycer|shortening|stearoyl|emulsifier|rennet|enzyme))|"
    r"soy[- ]derived|palm[- ]derived|coconut[- ]derived|corn[- ]derived|rapeseed[- ]derived|"
    r"bacterial|fungal|fermentation[- ]produced|fpc|synthetic|lichen|algae"
    r")(?![a-z0-9])"
)

_GELATIN_SAFE_QUALIFIER_RE = re.compile(
    r"(?<![a-z0-9])(?:"
    r"kosher\s+fish\s+gelatin|fish\s+gelatin|gelatin\s*\(\s*(?:kosher\s+)?fish\s*\)|"
    r"halal\s+(?:beef\s+|bovine\s+)?gelatin|gelatin\s*\(\s*halal(?:\s+beef|\s+bovine)?\s*\)|"
    r"plant[- ]based\s+gelatin|vegan\s+gelatin|vegetarian\s+gelatin"
    r")(?![a-z0-9])"
)

_VANILLA_SAFE_QUALIFIER_RE = re.compile(
    r"(?<![a-z0-9])(?:alcohol[- ]free|non-?alcoholic|zero[- ]alcohol)(?![a-z0-9])"
)

# Negative animal-source cues that block explicit_label_safe.
_ANIMAL_CONTRADICTION_RE = re.compile(
    r"(?<![a-z0-9])(?:"
    r"porcine|pork|swine|pig|lard|calf|lanolin|cochineal|carmine|shellac|"
    r"(?<!non-)(?<!non )animal(?=\s+(?:enzyme|rennet|fat|glycer|mono|gelatin|source))"
    r")(?![a-z0-9])"
)

_PORK_CUE_RE = re.compile(r"(?<![a-z0-9])(?:pork|porcine|swine|pig)(?![a-z0-9])")

_ALCOHOL_FALSE_POSITIVE_RE = re.compile(
    r"(?:sugar|polyvinyl|stearyl|cetyl|cetearyl|benzyl|fatty)\s+alcohol|"
    r"alcohol\s*-?\s*free"
)

_WINE_VINEGAR_RE = re.compile(r"wine\s+vinegar")


def normalize_ingredients(raw: str) -> str:
    """Normalize a raw U.S. ingredient statement while preserving parenthetical nesting."""
    if not raw:
        return ""

    text = raw.replace("\u00a0", " ")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.lower().strip()

    # Strip leading label header such as "INGREDIENTS:" or "Ingredient List:".
    text = re.sub(r"^(?:ingredients?(?:\s+list)?)\s*[:\-]\s*", "", text)

    # Standardize brackets/braces to parentheses for uniform nesting.
    text = text.replace("[", "(").replace("{", "(")
    text = text.replace("]", ")").replace("}", ")")

    # Remove organic/footnote markers like asterisks or daggers.
    text = re.sub(r"[*†‡]", "", text)

    # Collapse whitespace and clean spacing around delimiters.
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([,;:])\s*", r"\1 ", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\s+\.", ".", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Strip trailing period(s) / commas.
    text = text.rstrip(".,; ")
    return text


def compute_ingredient_hash(raw: str) -> str:
    """Compute a deterministic SHA-256 hex digest of the normalized ingredient string."""
    normalized = normalize_ingredients(raw)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _split_top_level(text: str) -> list[str]:
    """Split text on commas, semicolons, and sentence periods at parenthesis depth 0."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    length = len(text)

    for idx, ch in enumerate(text):
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif depth == 0 and ch in (",", ";"):
            segment = "".join(buf).strip()
            if segment:
                parts.append(segment)
            buf = []
        elif depth == 0 and ch == ".":
            prev_ch = text[idx - 1] if idx > 0 else ""
            next_ch = text[idx + 1] if idx + 1 < length else ""
            # Split on sentence-ending period (e.g. "...enzymes). contains 2% or less of: ...")
            # but NOT on decimals like "2.5%".
            if not (prev_ch.isdigit() and next_ch.isdigit()) and (
                next_ch == "" or next_ch.isspace()
            ):
                segment = "".join(buf).strip()
                if segment:
                    parts.append(segment)
                buf = []
            else:
                buf.append(ch)
        else:
            buf.append(ch)

    trailing = "".join(buf).strip()
    if trailing:
        parts.append(trailing)
    return parts


def _clean_segment(segment: str) -> str:
    """Strip FDA percentage threshold prefixes and stray leading conjunctions."""
    cleaned = segment.strip(" ,;.")
    cleaned = _LEADING_THRESHOLD_RE.sub("", cleaned).strip(" ,;.:")
    # Handle "with paprika" or "and annatto added for color" without breaking "mono- and diglycerides".
    cleaned = re.sub(r"^(?:with|and)\s+", "", cleaned).strip()
    cleaned = re.sub(r"\s+added\s+for\s+color$", "", cleaned).strip()
    return cleaned


def _extract_outer_and_parens(segment: str) -> tuple[str, list[str]]:
    """Separate outer text and top-level parenthetical groups from a segment."""
    outer_chars: list[str] = []
    groups: list[str] = []
    current_group: list[str] = []
    depth = 0

    for ch in segment:
        if ch == "(":
            if depth == 0:
                current_group = []
            else:
                current_group.append(ch)
            depth += 1
        elif ch == ")":
            if depth > 0:
                depth -= 1
                if depth == 0:
                    group_text = "".join(current_group).strip()
                    if group_text:
                        groups.append(group_text)
                else:
                    current_group.append(ch)
        else:
            if depth == 0:
                outer_chars.append(ch)
            else:
                current_group.append(ch)

    # Recover unclosed parenthesis cleanly if OCR text was truncated.
    if depth > 0 and current_group:
        group_text = "".join(current_group).strip()
        if group_text:
            groups.append(group_text)

    outer = re.sub(r"\s+", " ", "".join(outer_chars)).strip(" ,;.:")
    return outer, groups


def _is_inline_qualifier(group_text: str) -> bool:
    """Return True if a single-item parenthetical looks like a qualifier/synonym."""
    if "," in group_text or ";" in group_text or "(" in group_text:
        return False
    candidate = group_text.strip().lower()
    return any(pat.match(candidate) for pat in _INLINE_QUALIFIER_PATTERNS)


def parse_ingredient_tokens(raw: str) -> list[dict[str, Any]]:
    """Parse normalized ingredients into depth-aware tokens preserving parent context."""
    normalized = normalize_ingredients(raw)
    if not normalized:
        return []

    tokens: list[dict[str, Any]] = []

    def _walk(text: str, parent_context: str | None, depth: int) -> None:
        for raw_segment in _split_top_level(text):
            seg_lower = raw_segment.strip()
            if not seg_lower:
                continue

            # Skip FDA allergen declaration footer ("contains: milk, wheat") at top level.
            if depth == 0 and _ALLERGEN_FOOTER_RE.match(seg_lower):
                continue

            # If a segment contains "contains less than 2% of: a, b" split after colon if needed.
            cleaned = _clean_segment(seg_lower)
            if not cleaned:
                continue

            if "(" not in cleaned:
                tokens.append(
                    {
                        "token": cleaned,
                        "raw_segment": cleaned,
                        "parent_context": parent_context,
                        "depth": depth,
                        "is_leaf": True,
                    }
                )
                continue

            outer, paren_groups = _extract_outer_and_parens(cleaned)

            # Check whether all parenthetical groups are simple inline qualifiers
            # (e.g. "enzymes (microbial)", "ferrous sulfate (iron)", "gelatin (porcine)").
            if outer and paren_groups and all(_is_inline_qualifier(g) for g in paren_groups):
                tokens.append(
                    {
                        "token": cleaned,
                        "raw_segment": cleaned,
                        "parent_context": parent_context,
                        "depth": depth,
                        "is_leaf": True,
                    }
                )
                continue

            if outer:
                tokens.append(
                    {
                        "token": outer,
                        "raw_segment": cleaned,
                        "parent_context": parent_context,
                        "depth": depth,
                        "is_leaf": not bool(paren_groups),
                    }
                )

            child_parent = outer if outer else parent_context
            for group in paren_groups:
                _walk(group, parent_context=child_parent, depth=depth + 1)

    _walk(normalized, parent_context=None, depth=0)
    return tokens


def compute_ingredient_diff(old_raw: str, new_raw: str) -> tuple[list[str], list[str]]:
    """Return sorted (added_ingredients, removed_ingredients) comparing normalized leaf tokens."""
    old_tokens = parse_ingredient_tokens(old_raw)
    new_tokens = parse_ingredient_tokens(new_raw)

    old_leaves = {t["token"] for t in old_tokens if t.get("is_leaf")}
    if not old_leaves:
        old_leaves = {t["token"] for t in old_tokens}

    new_leaves = {t["token"] for t in new_tokens if t.get("is_leaf")}
    if not new_leaves:
        new_leaves = {t["token"] for t in new_tokens}

    added = sorted(new_leaves - old_leaves)
    removed = sorted(old_leaves - new_leaves)
    return added, removed


def _check_explicit_label_safe(
    canonical_name: str,
    default_risk: str,
    token_text: str,
) -> tuple[bool, str | None]:
    """Detect explicit plant/microbial/safe source qualifiers printed on the label."""
    if default_risk == "haram_animal":
        return False, None

    lower = token_text.lower()
    if _ANIMAL_CONTRADICTION_RE.search(lower):
        return False, None

    canon_lower = canonical_name.lower()

    if canon_lower == "gelatin":
        if _GELATIN_SAFE_QUALIFIER_RE.search(lower):
            return (
                True,
                f"Label explicitly specifies a halal/fish/plant gelatin source ('{token_text}').",
            )
        return False, None

    if canon_lower == "vanilla extract":
        if _VANILLA_SAFE_QUALIFIER_RE.search(lower):
            return (
                True,
                f"Label explicitly specifies alcohol-free vanilla ('{token_text}').",
            )
        return False, None

    if _GENERAL_SAFE_QUALIFIER_RE.search(lower):
        return (
            True,
            f"Label explicitly specifies a plant/microbial/non-animal source ('{token_text}').",
        )

    return False, None


def _phrase_matches_token(phrase: str, token_text: str, canonical_lower: str) -> tuple[int, int] | None:
    """Return (start, end) span if phrase matches token_text safely on word boundaries."""
    pattern = re.compile(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])")
    for match in pattern.finditer(token_text):
        span = match.span()
        # Guard false positives for alcohol/wine rules.
        if canonical_lower == "alcohol / wine":
            if phrase == "alcohol" and _ALCOHOL_FALSE_POSITIVE_RE.search(token_text):
                continue
            if "wine" in phrase and _WINE_VINEGAR_RE.search(token_text):
                continue
        return span
    return None


def match_ingredient_rules(
    raw: str,
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match parsed ingredient tokens against ingredient_rules with specificity & qualifier handling."""
    tokens = parse_ingredient_tokens(raw)
    if not tokens or not rules:
        return []

    rules_by_canon: dict[str, dict[str, Any]] = {
        r["canonical_name"].lower(): r for r in rules
    }
    pork_gelatin_rule = rules_by_canon.get("pork gelatin")

    # Precompute normalized candidate phrases per rule.
    compiled_rules: list[tuple[dict[str, Any], list[str]]] = []
    for rule in rules:
        aliases = rule.get("aliases") or []
        phrases_raw = [rule["canonical_name"], *aliases]
        seen_phrases: set[str] = set()
        phrases: list[str] = []
        for phrase in phrases_raw:
            norm_phrase = normalize_ingredients(str(phrase))
            if norm_phrase and norm_phrase not in seen_phrases:
                seen_phrases.add(norm_phrase)
                phrases.append(norm_phrase)
        # Prefer longest phrases first within the rule.
        phrases.sort(key=len, reverse=True)
        compiled_rules.append((rule, phrases))

    # Collect matches deduplicated by canonical_name (worst/unresolved match wins).
    matched_by_canon: dict[str, dict[str, Any]] = {}

    for tok in tokens:
        token_text: str = tok["token"].lower()
        if not token_text:
            continue

        # Find all candidate rule hits on this single token.
        token_hits: list[tuple[int, int, tuple[int, int], dict[str, Any]]] = []
        for rule, phrases in compiled_rules:
            canon_lower = rule["canonical_name"].lower()
            best_span: tuple[int, int] | None = None
            best_len = 0
            for phrase in phrases:
                span = _phrase_matches_token(phrase, token_text, canon_lower)
                if span is not None and (span[1] - span[0]) > best_len:
                    best_span = span
                    best_len = span[1] - span[0]
            if best_span is not None:
                is_haram = 1 if rule.get("default_risk") == "haram_animal" else 0
                token_hits.append((best_len, is_haram, best_span, rule))

        if not token_hits:
            continue

        # Sort most specific first: longest match span, then haram_animal priority.
        token_hits.sort(key=lambda item: (item[0], item[1]), reverse=True)

        accepted_spans: list[tuple[int, int]] = []
        accepted_rules: list[dict[str, Any]] = []
        for _length, _is_haram, span, rule in token_hits:
            # Suppress generic match completely contained within a more specific match
            # (e.g. "gelatin" inside "pork gelatin" or "gelatin (porcine)").
            if any(a_start <= span[0] and span[1] <= a_end for a_start, a_end in accepted_spans):
                continue

            # Escalate generic gelatin containing pork/porcine cues to pork gelatin rule.
            if (
                rule["canonical_name"].lower() == "gelatin"
                and pork_gelatin_rule is not None
                and _PORK_CUE_RE.search(token_text)
            ):
                rule = pork_gelatin_rule

            accepted_spans.append(span)
            accepted_rules.append(rule)

        for rule in accepted_rules:
            canon_key = rule["canonical_name"].lower()
            explicit_safe, safe_reason = _check_explicit_label_safe(
                rule["canonical_name"],
                str(rule["default_risk"]),
                token_text,
            )

            candidate = {
                "rule": rule,
                "canonical_name": rule["canonical_name"],
                "matched_token": tok["token"],
                "raw_segment": tok["raw_segment"],
                "parent_context": tok["parent_context"],
                "default_risk": rule["default_risk"],
                "explicit_label_safe": explicit_safe,
                "explicit_safe_reason": safe_reason,
            }

            existing = matched_by_canon.get(canon_key)
            if existing is None:
                matched_by_canon[canon_key] = candidate
            else:
                # If an unresolved occurrence appears alongside an explicitly safe one,
                # the unresolved occurrence MUST win so we never false-green a product.
                if existing["explicit_label_safe"] and not candidate["explicit_label_safe"]:
                    matched_by_canon[canon_key] = candidate
                elif (
                    existing["explicit_label_safe"] == candidate["explicit_label_safe"]
                    and candidate["parent_context"]
                    and candidate["parent_context"] != existing["parent_context"]
                ):
                    if existing["parent_context"]:
                        existing_contexts = [
                            c.strip() for c in existing["parent_context"].split(",")
                        ]
                        if candidate["parent_context"] not in existing_contexts:
                            existing["parent_context"] = (
                                f"{existing['parent_context']}, {candidate['parent_context']}"
                            )
                    else:
                        existing["parent_context"] = candidate["parent_context"]

    # Deterministic ordering: haram_animal first, then mushbooh, then caution/safe, alphabetically.
    risk_order = {
        "haram_animal": 0,
        "mushbooh": 1,
        "caution_context": 2,
        "safe": 3,
    }
    return sorted(
        matched_by_canon.values(),
        key=lambda m: (risk_order.get(str(m["default_risk"]), 9), m["canonical_name"].lower()),
    )
