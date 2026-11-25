"""Verified U.S. brand contact directory & safe server-side contact discovery."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from app.schemas import BrandContactLookupResponse

# ---------------------------------------------------------------------------
# Constants & Safety Filters
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_MAILTO_RE = re.compile(r'mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', re.IGNORECASE)
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_TOLL_FREE_RE = re.compile(r"\b1?[-.\s]?\(?(8(?:00|33|44|55|66|77|88))\)?[-.\s]?(\d{3})[-.\s]?(\d{4})\b")

_BLOCKED_EMAIL_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "test.com",
    "invalid",
    "localhost",
    "wixpress.com",
    "sentry.io",
    "squarespace.com",
    "shopify.com",
    "cloudflare.com",
    "w3.org",
    "schema.org",
    "googleapis.com",
    "gravatar.com",
    "facebook.com",
    "twitter.com",
    "instagram.com",
    "youtube.com",
    "pissedconsumer.com",
    "gethuman.com",
    "bbb.org",
}

_BLOCKED_LOCAL_PARTS = {
    "noreply",
    "no-reply",
    "no_reply",
    "donotreply",
    "do-not-reply",
    "do_not_reply",
    "mailer-daemon",
    "postmaster",
    "webmaster",
    "hostmaster",
    "abuse",
    "security",
    "privacy",
    "usprivacy",
    "gdpr",
    "dpo",
    "legal",
    "dmca",
    "copyright",
    "copyrights",
    "trademark",
    "press",
    "media",
    "pr",
    "news",
    "newsroom",
    "ir",
    "investor",
    "investors",
    "investorrelations",
    "careers",
    "jobs",
    "hr",
    "askhr",
    "recruiting",
    "talent",
    "unsubscribe",
    "bounce",
    "notifications",
    "alerts",
    "billing",
    "sales",
    "wholesale",
    "affiliate",
    "affiliates",
    "donations",
    "sponsorship",
    "boardofdirectors",
}

_PREFERRED_LOCAL_HINTS = (
    "customerservice",
    "customer.service",
    "customercare",
    "customer.care",
    "consumercare",
    "consumer.care",
    "consumerrelations",
    "consumer.relations",
    "crelations",
    "support",
    "care",
    "help",
    "ask",
    "contact",
    "contactus",
    "info",
    "hello",
)

_AGGREGATOR_HOSTS = {
    "pissedconsumer.com",
    "gethuman.com",
    "bbb.org",
    "wikipedia.org",
    "reddit.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "yelp.com",
    "zoominfo.com",
    "amazon.com",
    "walmart.com",
    "target.com",
    "instacart.com",
    "youtube.com",
    "tiktok.com",
    "dnb.com",
    "bloomberg.com",
    "crunchbase.com",
    "glassdoor.com",
    "indeed.com",
    "corporateoffice.com",
    "donotpay.com",
    "duckduckgo.com",
    "google.com",
    "example.com",
    "example.org",
    "example.net",
}

_BRAND_STOPWORDS = {
    "inc",
    "llc",
    "co",
    "corp",
    "corporation",
    "company",
    "foods",
    "food",
    "brands",
    "brand",
    "usa",
    "us",
    "the",
    "and",
    "of",
    "international",
    "north",
    "america",
}

_USER_AGENT = "HalalLens/1.0 (+https://github.com/omermd007/halalLens; consumer-contact-lookup)"


# ---------------------------------------------------------------------------
# Directory loading & normalization
# ---------------------------------------------------------------------------


def _directory_candidates() -> list[Path]:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "frontend" / "src" / "data" / "brandContacts.json",
        Path("/app/frontend/src/data/brandContacts.json"),
    ]
    return candidates


@lru_cache(maxsize=1)
def load_brand_directory() -> tuple[dict[str, Any], ...]:
    """Load the shared verified U.S. brand contact directory JSON."""
    for path in _directory_candidates():
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return tuple(raw)
    return ()


def normalize_brand_name(value: str) -> str:
    """Normalize a brand name for accent/punctuation-insensitive matching."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = ascii_only.lower()
    # Remove apostrophes so "Annie's" and "Annies" normalize identically.
    no_apos = re.sub(r"['’`]", "", lowered)
    spaced = re.sub(r"[^a-z0-9]+", " ", no_apos)
    return re.sub(r"\s+", " ", spaced).strip()


def lookup_directory_contact(brand: str) -> dict[str, Any] | None:
    """Match a brand or sub-brand against the verified U.S. Brand Contact Directory."""
    query = normalize_brand_name(brand)
    if not query:
        return None

    directory = load_brand_directory()

    # Pass 1: Exact normalized match on brand or any alias.
    for entry in directory:
        names = [entry.get("brand", ""), *(entry.get("aliases") or [])]
        for candidate in names:
            if normalize_brand_name(str(candidate)) == query:
                return entry

    # Pass 2: Word-boundary match (longest alias wins to avoid false positives).
    best_entry: dict[str, Any] | None = None
    best_score = 0
    padded_query = f" {query} "
    for entry in directory:
        names = [entry.get("brand", ""), *(entry.get("aliases") or [])]
        for candidate in names:
            norm = normalize_brand_name(str(candidate))
            if not norm or len(norm) < 3:
                continue
            padded_cand = f" {norm} "
            if padded_cand in padded_query:
                score = len(norm) + 100
                if score > best_score:
                    best_score = score
                    best_entry = entry
            elif len(query) >= 4 and padded_query in padded_cand:
                score = len(query)
                if score > best_score:
                    best_score = score
                    best_entry = entry

    return best_entry


# ---------------------------------------------------------------------------
# Validation & SSRF-safe web helpers
# ---------------------------------------------------------------------------


def _registrable_domain(host: str) -> str:
    host = host.lower().strip().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = [p for p in host.split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    if parts[-1] in {"uk", "au", "nz", "ca"} and parts[-2] in {"co", "com", "org", "net"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_valid_support_email(email: str, expected_domain: str | None = None) -> bool:
    """Validate that an extracted email is a real consumer-support address on the brand's domain."""
    if not email:
        return False
    cleaned = email.strip().lower()
    if not _EMAIL_RE.fullmatch(cleaned):
        return False

    local, domain = cleaned.rsplit("@", 1)
    if domain in _BLOCKED_EMAIL_DOMAINS:
        return False
    if any(domain.endswith(f".{blocked}") for blocked in _BLOCKED_EMAIL_DOMAINS):
        return False

    local_compact = re.sub(r"[^a-z0-9]", "", local)
    if local in _BLOCKED_LOCAL_PARTS or local_compact in _BLOCKED_LOCAL_PARTS:
        return False
    if any(local.startswith(prefix) for prefix in ("noreply", "no-reply", "no_reply", "donotreply", "do-not-reply")):
        return False

    if expected_domain:
        exp_root = _registrable_domain(expected_domain)
        email_root = _registrable_domain(domain)
        if exp_root and email_root != exp_root:
            return False

    return True


def _is_safe_public_url(url: str) -> bool:
    """Ensure URL is public http(s) and does not point to private/loopback networks."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        return False
    if host.endswith(".local") or host.endswith(".internal") or host.endswith(".localhost"):
        return False

    # Check literal IP first.
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_global and not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
    except ValueError:
        pass

    # Resolve DNS and verify all returned IPs are globally routable.
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    return True


def _extract_ddg_urls(html_text: str) -> list[str]:
    """Extract target URLs from DuckDuckGo HTML search output."""
    urls: list[str] = []
    seen: set[str] = set()
    for raw_href in _HREF_RE.findall(html_text):
        href = raw_href.strip()
        candidate: str | None = None
        if "uddg=" in href:
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            if "uddg" in qs and qs["uddg"]:
                candidate = unquote(qs["uddg"][0])
        elif href.startswith("http://") or href.startswith("https://"):
            candidate = href

        if not candidate:
            continue
        parsed_c = urlparse(candidate)
        if parsed_c.scheme not in ("http", "https"):
            continue
        host = (parsed_c.hostname or "").lower()
        root = _registrable_domain(host)
        if not root or root in _AGGREGATOR_HOSTS or host in _AGGREGATOR_HOSTS:
            continue
        if candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    return urls


def _pick_official_contact_url(brand: str, candidates: list[str]) -> str | None:
    """Rank search result URLs to pick the brand's own official Contact Us page."""
    tokens = [
        tok
        for tok in normalize_brand_name(brand).split()
        if len(tok) >= 3 and tok not in _BRAND_STOPWORDS
    ]
    compact_brand = "".join(tokens)

    best_url: str | None = None
    best_score = -1

    for url in candidates:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        root = _registrable_domain(host)
        host_flat = re.sub(r"[^a-z0-9]", "", root.split(".")[0])
        path = (parsed.path or "").lower()

        # Require the domain to visibly relate to the brand name.
        brand_match = False
        score = 0
        if compact_brand and (compact_brand in host_flat or host_flat in compact_brand):
            brand_match = True
            score += 50
        else:
            matched_tokens = sum(1 for tok in tokens if tok in host_flat)
            if matched_tokens > 0:
                brand_match = True
                score += matched_tokens * 25

        if not brand_match:
            continue

        if any(k in path for k in ("contact", "support", "consumer", "customer-care", "help")):
            score += 30
        elif "faq" in path:
            score += 15

        if parsed.scheme == "https":
            score += 5

        if score > best_score:
            best_score = score
            best_url = url

    return best_url


def _extract_email_and_phone_from_html(html_text: str, page_url: str) -> tuple[str | None, str | None]:
    """Extract a valid brand-domain support email and optional U.S. toll-free phone from HTML."""
    host = (urlparse(page_url).hostname or "").lower()
    expected_domain = _registrable_domain(host)

    # Prefer mailto: links first, then raw text matches.
    candidates: list[str] = []
    for match in _MAILTO_RE.findall(html_text):
        candidates.append(match.strip())
    for match in _EMAIL_RE.findall(html_text):
        candidates.append(match.strip())

    valid: list[str] = []
    seen: set[str] = set()
    for email in candidates:
        low = email.lower()
        if low in seen:
            continue
        seen.add(low)
        if is_valid_support_email(low, expected_domain=expected_domain):
            valid.append(low)

    chosen_email: str | None = None
    if valid:
        def _rank(addr: str) -> int:
            local = addr.split("@", 1)[0]
            local_flat = re.sub(r"[^a-z0-9]", "", local)
            for idx, hint in enumerate(_PREFERRED_LOCAL_HINTS):
                hint_flat = re.sub(r"[^a-z0-9]", "", hint)
                if local == hint or local_flat == hint_flat:
                    return idx
                if hint_flat in local_flat:
                    return idx + 50
            return 200

        valid.sort(key=_rank)
        chosen_email = valid[0]

    phone_match = _TOLL_FREE_RE.search(html_text)
    phone = (
        f"1-{phone_match.group(1)}-{phone_match.group(2)}-{phone_match.group(3)}"
        if phone_match
        else None
    )
    return chosen_email, phone


def _web_lookup_brand_contact(brand: str) -> tuple[str | None, str | None, str | None]:
    """Perform a bounded, SSRF-safe server-side lookup for an unknown brand's contact page."""
    query = f'"{brand}" official contact us consumer care OR customer support'
    try:
        with httpx.Client(
            timeout=6.0,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        ) as client:
            search_resp = client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
            )
            if search_resp.status_code != 200:
                return None, None, None

            candidates = _extract_ddg_urls(search_resp.text[:300_000])
            contact_url = _pick_official_contact_url(brand, candidates)
            if not contact_url or not _is_safe_public_url(contact_url):
                return None, None, None

            email: str | None = None
            phone: str | None = None
            try:
                page_resp = client.get(contact_url)
                final_url = str(page_resp.url)
                if page_resp.status_code == 200 and _is_safe_public_url(final_url):
                    contact_url = final_url
                    ctype = (page_resp.headers.get("content-type") or "").lower()
                    if "text/html" in ctype or "text/plain" in ctype or not ctype:
                        email, phone = _extract_email_and_phone_from_html(
                            page_resp.text[:250_000],
                            final_url,
                        )
            except httpx.HTTPError:
                # Even if fetching the page fails, returning the official URL is still useful.
                pass

            return contact_url, email, phone
    except httpx.HTTPError:
        return None, None, None


def build_google_search_url(brand: str) -> str:
    query = f'"{brand.strip()}" consumer care OR customer support contact email'
    return f"https://www.google.com/search?q={quote_plus(query)}"


def lookup_brand_contact(brand: str, *, allow_web: bool = True) -> BrandContactLookupResponse:
    """Resolve official consumer-care contact details for a grocery brand."""
    cleaned_brand = brand.strip()
    search_url = build_google_search_url(cleaned_brand)

    # 1. Verified U.S. Brand Contact Directory first.
    entry = lookup_directory_contact(cleaned_brand)
    if entry is not None:
        email = entry.get("email") or None
        contact_url = entry.get("contact_url") or None
        contact_type = entry.get("contact_type") or ("email" if email else "web_form")
        return BrandContactLookupResponse(
            brand=entry["brand"],
            matched_query=cleaned_brand,
            source="verified_directory",
            verified=True,
            contact_type=contact_type,
            email=email,
            contact_url=contact_url,
            phone=entry.get("phone") or None,
            search_url=search_url,
            note=(
                f"Verified U.S. consumer care contact for {entry['brand']}."
                if email
                else f"{entry['brand']} handles inquiries via their online contact form rather than direct email."
            ),
        )

    # 2. Safe server-side web discovery for unknown brands.
    if allow_web:
        contact_url, email, phone = _web_lookup_brand_contact(cleaned_brand)
        if contact_url or email:
            return BrandContactLookupResponse(
                brand=cleaned_brand,
                matched_query=cleaned_brand,
                source="web_lookup",
                verified=False,
                contact_type="email" if email else "web_form",
                email=email,
                contact_url=contact_url,
                phone=phone,
                search_url=search_url,
                note=(
                    "Discovered via web lookup on the brand's website. Please verify before sending."
                ),
            )

    return BrandContactLookupResponse(
        brand=cleaned_brand,
        matched_query=cleaned_brand,
        source="not_found",
        verified=False,
        contact_type="unknown",
        email=None,
        contact_url=None,
        phone=None,
        search_url=search_url,
        note="No official support contact found automatically. Use the web search link to look up this brand.",
    )
