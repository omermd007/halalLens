"""External barcode lookup adapters (USDA FoodData Central & Open Food Facts).

Self-contained module (stdlib + httpx) providing timeout-guarded barcode lookup
for U.S. packaged foods with graceful offline, rate-limit, and miss handling.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any

import httpx

USDA_FDC_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
OPEN_FOOD_FACTS_PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{upc}.json"
DEFAULT_OFF_USER_AGENT = "HalalLens-Prototype/1.0 (+https://halallens.local)"
DEFAULT_TIMEOUT_SECONDS = 5.0

_VEGAN_LABEL_TAGS = frozenset(
    {
        "en:vegan",
        "en:certified-vegan",
        "en:vegan-action",
        "en:vegetarian-society-vegan",
        "en:100-vegan",
        "en:european-vegetarian-union-vegan",
    }
)

# Ordered from most specific to most generic so e.g. OU-D wins over OU or Kosher.
_KOSHER_LABEL_PRIORITY: tuple[tuple[str, str], ...] = (
    ("en:ou-d", "OU-D"),
    ("en:orthodox-union-kosher-dairy", "OU-D"),
    ("en:ou-pareve", "OU-Pareve"),
    ("en:orthodox-union-kosher-pareve", "OU-Pareve"),
    ("en:orthodox-union-kosher", "OU"),
    ("en:ou-kosher", "OU"),
    ("en:ok-d", "OK-D"),
    ("en:ok-pareve", "OK-Pareve"),
    ("en:ok-kosher", "OK"),
    ("en:star-d", "Star-D"),
    ("en:star-k", "Star-K"),
    ("en:kof-k-dairy", "Kof-K Dairy"),
    ("en:kof-k", "Kof-K"),
    ("en:crc-kosher", "cRc"),
    ("en:kosher", "Kosher"),
)

_KNOWN_HALAL_CERTIFIERS: tuple[tuple[str, str], ...] = (
    ("ifanca", "IFANCA"),
    ("isna", "ISNA"),
    ("hfsaa", "HFSAA"),
    ("hms", "HMS"),
    ("hma", "HMA"),
    ("islamic services of america", "ISA"),
    ("halal transactions of omaha", "HTO"),
)


@dataclass
class ExternalLookupCandidate:
    """Normalized candidate product returned from an external barcode provider."""

    upc: str
    name: str
    brand: str
    category: str
    raw_ingredients: str
    source_type: str
    kosher_symbol: str | None = None
    is_certified_vegan: bool = False
    certifier_name: str | None = None
    certifier_status: str | None = None
    external_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LookupTraceStep:
    """Trace entry describing the outcome of a single lookup tier."""

    tier: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_upc_candidates(upc: str) -> list[str]:
    """Strip non-digits and generate canonical U.S./GTIN barcode variants.

    Produces a deduplicated ordered list covering:
    - raw numeric digits
    - 12-digit UPC-A (zero-padded or trimmed from zero-prefixed EAN-13/GTIN-14)
    - 13-digit EAN-13 (with leading 0 for UPC-A, or trimmed from GTIN-14)
    - 14-digit GTIN-14 (zero-padded)
    """
    raw = re.sub(r"\D", "", upc or "")
    if not raw:
        return []

    variants: list[str] = []

    def _add(code: str) -> None:
        if code and code not in variants:
            variants.append(code)

    _add(raw)

    # Derive canonical 12-digit UPC-A when possible
    if len(raw) <= 12:
        upc_a = raw.zfill(12)
        _add(upc_a)
        _add(upc_a.zfill(13))
        _add(upc_a.zfill(14))
    elif len(raw) == 13:
        if raw.startswith("0"):
            _add(raw[1:])  # 12-digit UPC-A
        _add(raw.zfill(14))  # 14-digit GTIN-14
    elif len(raw) == 14:
        if raw.startswith("00"):
            _add(raw[2:])  # 12-digit UPC-A
        if raw.startswith("0"):
            _add(raw[1:])  # 13-digit EAN-13

    return variants


def _canonical_upc(upc: str) -> str:
    """Choose the cleanest canonical U.S. UPC representation (prefer 12-digit UPC-A)."""
    raw = re.sub(r"\D", "", upc or "")
    if not raw:
        return ""
    if len(raw) == 11:
        return raw.zfill(12)
    if len(raw) == 12:
        return raw
    if len(raw) == 13 and raw.startswith("0"):
        return raw[1:]
    if len(raw) == 14 and raw.startswith("00"):
        return raw[2:]
    return raw


def _parse_off_labels(
    labels_tags: list[str] | None,
    labels_text: str | None = None,
) -> tuple[bool, str | None, str | None, str | None]:
    """Extract vegan, kosher, and halal label metadata from Open Food Facts tags."""
    normalized_tags = [
        str(tag).strip().lower()
        for tag in (labels_tags or [])
        if str(tag).strip()
    ]
    tag_set = set(normalized_tags)
    raw_labels_lower = (labels_text or "").lower()

    is_certified_vegan = bool(tag_set & _VEGAN_LABEL_TAGS)

    kosher_symbol: str | None = None
    for tag, symbol in _KOSHER_LABEL_PRIORITY:
        if tag in tag_set:
            kosher_symbol = symbol
            break

    certifier_name: str | None = None
    certifier_status: str | None = None

    has_halal_tag = "en:halal" in tag_set or any(
        tag.endswith(":halal") or ":halal-" in tag for tag in normalized_tags
    )
    if has_halal_tag:
        combined_hint = " ".join(normalized_tags) + " " + raw_labels_lower
        for keyword, display_name in _KNOWN_HALAL_CERTIFIERS:
            if keyword in combined_hint:
                certifier_name = display_name
                certifier_status = "label_reported"
                break
        if certifier_name is None:
            certifier_name = "Halal (Open Food Facts)"
            certifier_status = "label_reported"

    return is_certified_vegan, kosher_symbol, certifier_name, certifier_status


class UsdaFdcAdapter:
    """Adapter for USDA FoodData Central Branded Foods search API."""

    tier_name = "usda_fdc"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = (
            api_key
            if api_key is not None
            else (os.environ.get("USDA_API_KEY") or "DEMO_KEY")
        )
        self.timeout = timeout
        self._client = client

    def _select_query_variants(self, variants: list[str]) -> list[str]:
        """Select up to 2 high-value UPC query variants to stay friendly to DEMO_KEY quotas."""
        if not variants:
            return []
        ordered: list[str] = []
        # Prefer 12-digit UPC-A first for U.S. USDA FDC branded dataset, then raw/alternate.
        for code in variants:
            if len(code) == 12 and code not in ordered:
                ordered.append(code)
        for code in variants:
            if code not in ordered:
                ordered.append(code)
        return ordered[:2]

    def _pick_best_food_match(
        self,
        foods: list[dict[str, Any]],
        target_variants: set[str],
    ) -> dict[str, Any] | None:
        matches: list[dict[str, Any]] = []
        for food in foods:
            if not isinstance(food, dict):
                continue
            gtin_raw = str(food.get("gtinUpc") or "").strip()
            if not gtin_raw:
                continue
            food_variants = set(normalize_upc_candidates(gtin_raw))
            if food_variants & target_variants:
                matches.append(food)

        if not matches:
            return None

        # Prefer matches with non-empty ingredients and most recent publication date.
        matches.sort(
            key=lambda item: (
                bool(str(item.get("ingredients") or "").strip()),
                str(item.get("publishedDate") or item.get("modifiedDate") or ""),
            ),
            reverse=True,
        )
        return matches[0]

    def lookup(self, upc: str) -> tuple[ExternalLookupCandidate | None, LookupTraceStep]:
        variants = normalize_upc_candidates(upc)
        if not variants:
            return (
                None,
                LookupTraceStep(
                    tier=self.tier_name,
                    status="invalid_upc",
                    detail="No numeric digits found in UPC for USDA FDC lookup.",
                ),
            )

        target_variant_set = set(variants)
        queries = self._select_query_variants(variants)
        tried: list[str] = []

        own_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            for query_upc in queries:
                tried.append(query_upc)
                params = {
                    "query": query_upc,
                    "dataType": "Branded",
                    "pageSize": 5,
                    "api_key": self.api_key,
                }
                try:
                    response = client.get(USDA_FDC_SEARCH_URL, params=params)
                except httpx.TimeoutException:
                    return (
                        None,
                        LookupTraceStep(
                            tier=self.tier_name,
                            status="timeout",
                            detail=f"USDA FDC lookup timed out after {self.timeout:.1f}s.",
                        ),
                    )
                except httpx.RequestError as exc:
                    return (
                        None,
                        LookupTraceStep(
                            tier=self.tier_name,
                            status="offline",
                            detail=(
                                "USDA FDC lookup unavailable due to network error "
                                f"({exc.__class__.__name__})."
                            ),
                        ),
                    )

                if response.status_code == 429:
                    return (
                        None,
                        LookupTraceStep(
                            tier=self.tier_name,
                            status="rate_limited",
                            detail=(
                                "USDA FDC returned HTTP 429 (rate limit exceeded). "
                                "Configure USDA_API_KEY for higher quota."
                            ),
                        ),
                    )
                if response.status_code in (401, 403):
                    return (
                        None,
                        LookupTraceStep(
                            tier=self.tier_name,
                            status="auth_error",
                            detail=(
                                f"USDA FDC returned HTTP {response.status_code} "
                                "(API key rejected or restricted)."
                            ),
                        ),
                    )
                if response.status_code >= 400:
                    return (
                        None,
                        LookupTraceStep(
                            tier=self.tier_name,
                            status="error",
                            detail=f"USDA FDC returned HTTP {response.status_code}.",
                        ),
                    )

                try:
                    payload = response.json()
                except ValueError as exc:
                    return (
                        None,
                        LookupTraceStep(
                            tier=self.tier_name,
                            status="error",
                            detail=f"USDA FDC returned invalid JSON ({exc}).",
                        ),
                    )

                if not isinstance(payload, dict):
                    return (
                        None,
                        LookupTraceStep(
                            tier=self.tier_name,
                            status="error",
                            detail="USDA FDC returned an unexpected response payload.",
                        ),
                    )

                foods = payload.get("foods") or []
                if not isinstance(foods, list):
                    continue

                matched = self._pick_best_food_match(foods, target_variant_set)
                if matched is not None:
                    name = str(matched.get("description") or "").strip()
                    brand = str(
                        matched.get("brandName") or matched.get("brandOwner") or ""
                    ).strip()
                    category = str(matched.get("brandedFoodCategory") or "").strip()
                    raw_ingredients = str(matched.get("ingredients") or "").strip()
                    fdc_id = matched.get("fdcId")
                    gtin_upc = str(matched.get("gtinUpc") or query_upc).strip()
                    external_url = (
                        f"https://fdc.nal.usda.gov/fdc-app.html#/food-details/{fdc_id}/nutrients"
                        if fdc_id is not None
                        else None
                    )
                    candidate = ExternalLookupCandidate(
                        upc=_canonical_upc(gtin_upc) or _canonical_upc(upc),
                        name=name,
                        brand=brand,
                        category=category,
                        raw_ingredients=raw_ingredients,
                        source_type="usda_fdc",
                        external_url=external_url,
                    )
                    return (
                        candidate,
                        LookupTraceStep(
                            tier=self.tier_name,
                            status="hit",
                            detail=(
                                f"Matched USDA FDC branded food '{name or gtin_upc}' "
                                f"(fdcId={fdc_id}, gtinUpc={gtin_upc})."
                            ),
                        ),
                    )

            return (
                None,
                LookupTraceStep(
                    tier=self.tier_name,
                    status="miss",
                    detail=(
                        "No matching branded food in USDA FDC for UPC query "
                        f"{', '.join(tried)}."
                    ),
                ),
            )
        finally:
            if own_client:
                client.close()


class OpenFoodFactsAdapter:
    """Adapter for Open Food Facts v2 product lookup API."""

    tier_name = "open_food_facts"

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        user_agent: str = DEFAULT_OFF_USER_AGENT,
        client: httpx.Client | None = None,
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self._client = client

    def _select_query_variants(self, variants: list[str]) -> list[str]:
        """Try up to 3 canonical UPC/EAN/GTIN variants on Open Food Facts."""
        return variants[:3]

    def lookup(self, upc: str) -> tuple[ExternalLookupCandidate | None, LookupTraceStep]:
        variants = normalize_upc_candidates(upc)
        if not variants:
            return (
                None,
                LookupTraceStep(
                    tier=self.tier_name,
                    status="invalid_upc",
                    detail="No numeric digits found in UPC for Open Food Facts lookup.",
                ),
            )

        queries = self._select_query_variants(variants)
        tried: list[str] = []
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

        own_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            for code in queries:
                tried.append(code)
                url = OPEN_FOOD_FACTS_PRODUCT_URL.format(upc=code)
                try:
                    response = client.get(url, headers=headers)
                except httpx.TimeoutException:
                    return (
                        None,
                        LookupTraceStep(
                            tier=self.tier_name,
                            status="timeout",
                            detail=(
                                f"Open Food Facts lookup timed out after {self.timeout:.1f}s."
                            ),
                        ),
                    )
                except httpx.RequestError as exc:
                    return (
                        None,
                        LookupTraceStep(
                            tier=self.tier_name,
                            status="offline",
                            detail=(
                                "Open Food Facts lookup unavailable due to network error "
                                f"({exc.__class__.__name__})."
                            ),
                        ),
                    )

                if response.status_code == 404:
                    continue
                if response.status_code == 429:
                    return (
                        None,
                        LookupTraceStep(
                            tier=self.tier_name,
                            status="rate_limited",
                            detail="Open Food Facts returned HTTP 429 (rate limit exceeded).",
                        ),
                    )
                if response.status_code >= 400:
                    return (
                        None,
                        LookupTraceStep(
                            tier=self.tier_name,
                            status="error",
                            detail=f"Open Food Facts returned HTTP {response.status_code}.",
                        ),
                    )

                try:
                    payload = response.json()
                except ValueError as exc:
                    return (
                        None,
                        LookupTraceStep(
                            tier=self.tier_name,
                            status="error",
                            detail=f"Open Food Facts returned invalid JSON ({exc}).",
                        ),
                    )

                if not isinstance(payload, dict):
                    continue

                product = payload.get("product")
                if payload.get("status") != 1 or not isinstance(product, dict):
                    continue

                name = str(
                    product.get("product_name_en")
                    or product.get("product_name")
                    or product.get("generic_name_en")
                    or product.get("generic_name")
                    or ""
                ).strip()
                brand = str(product.get("brands") or "").strip()
                category = str(product.get("categories") or "").strip()
                if not category and isinstance(product.get("categories_tags"), list):
                    cleaned_cats = [
                        str(tag).split(":", 1)[-1].replace("-", " ").strip()
                        for tag in product["categories_tags"]
                        if str(tag).strip()
                    ]
                    category = ", ".join(cleaned_cats[:3])

                raw_ingredients = str(
                    product.get("ingredients_text_en")
                    or product.get("ingredients_text")
                    or ""
                ).strip()

                labels_tags = (
                    product.get("labels_tags")
                    if isinstance(product.get("labels_tags"), list)
                    else []
                )
                labels_text = str(product.get("labels") or "")
                (
                    is_certified_vegan,
                    kosher_symbol,
                    certifier_name,
                    certifier_status,
                ) = _parse_off_labels(labels_tags, labels_text)

                matched_code = str(product.get("code") or code).strip()
                candidate = ExternalLookupCandidate(
                    upc=_canonical_upc(matched_code) or _canonical_upc(upc),
                    name=name,
                    brand=brand,
                    category=category,
                    raw_ingredients=raw_ingredients,
                    source_type="open_food_facts",
                    kosher_symbol=kosher_symbol,
                    is_certified_vegan=is_certified_vegan,
                    certifier_name=certifier_name,
                    certifier_status=certifier_status,
                    external_url=f"https://world.openfoodfacts.org/product/{matched_code}",
                )
                return (
                    candidate,
                    LookupTraceStep(
                        tier=self.tier_name,
                        status="hit",
                        detail=(
                            f"Matched Open Food Facts product '{name or matched_code}' "
                            f"(code={matched_code})."
                        ),
                    ),
                )

            return (
                None,
                LookupTraceStep(
                    tier=self.tier_name,
                    status="miss",
                    detail=(
                        "Product not found on Open Food Facts for UPC variants "
                        f"{', '.join(tried)}."
                    ),
                ),
            )
        finally:
            if own_client:
                client.close()


def lookup_external_barcode(
    upc: str,
    allow_usda: bool = True,
    allow_off: bool = True,
    *,
    usda_adapter: UsdaFdcAdapter | None = None,
    off_adapter: OpenFoodFactsAdapter | None = None,
) -> tuple[ExternalLookupCandidate | None, list[LookupTraceStep]]:
    """Run tiered external barcode lookup: USDA FoodData Central first, then Open Food Facts.

    Never raises uncaught network/HTTP exceptions; every attempted or skipped tier
    is recorded in the returned trace list.
    """
    trace: list[LookupTraceStep] = []
    variants = normalize_upc_candidates(upc)
    if not variants:
        trace.append(
            LookupTraceStep(
                tier="normalize",
                status="invalid_upc",
                detail="Provided barcode contained no numeric digits.",
            )
        )
        return None, trace

    if allow_usda:
        adapter = usda_adapter or UsdaFdcAdapter()
        candidate, step = adapter.lookup(upc)
        trace.append(step)
        if candidate is not None:
            return candidate, trace
    else:
        trace.append(
            LookupTraceStep(
                tier=UsdaFdcAdapter.tier_name,
                status="skipped",
                detail="USDA FDC lookup disabled by caller.",
            )
        )

    if allow_off:
        adapter = off_adapter or OpenFoodFactsAdapter()
        candidate, step = adapter.lookup(upc)
        trace.append(step)
        if candidate is not None:
            return candidate, trace
    else:
        trace.append(
            LookupTraceStep(
                tier=OpenFoodFactsAdapter.tier_name,
                status="skipped",
                detail="Open Food Facts lookup disabled by caller.",
            )
        )

    return None, trace
