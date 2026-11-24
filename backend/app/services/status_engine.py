"""Deterministic 5-state halal ingredient status engine, strictness profiles, and review queue."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app import db
from app.config import EXPIRING_SOON_DAYS
from app.schemas import (
    BrandPolicy,
    CommunityNote,
    CompanyVerification,
    Determination,
    EvidenceTier,
    FlagResolutionStatus,
    FormulationDiff,
    FormulationSnapshot,
    ForumConsensus,
    ForumSignal,
    FreshnessBucket,
    IngredientFlag,
    IngredientRisk,
    OutreachInquiry,
    OutreachQueueItem,
    OutreachState,
    ProductDetail,
    ProductStatus,
    ProductSummary,
    RegionFlag,
    ReviewQueueCounts,
    ReviewQueueResponse,
    StrictnessProfile,
)
from app.services.ingredient_parser import (
    compute_ingredient_diff,
    compute_ingredient_hash,
    match_ingredient_rules,
    normalize_ingredients,
    parse_ingredient_tokens,
)

STRICTNESS_SETTING_KEY = "strictness_profile"

# Recognized kosher certification symbols accepted when treat_oud_enzymes_as_verified=True.
# Explicitly excludes generic/unsupervised "K" or "KD".
TRUSTED_KOSHER_SYMBOLS: frozenset[str] = frozenset(
    {
        "ou",
        "ou-d",
        "ou-pareve",
        "ou-p",
        "ok",
        "ok-d",
        "ok-pareve",
        "star-k",
        "star-d",
        "kof-k",
        "kof-k-d",
        "kof-k-dairy",
    }
)

KOSHER_RESOLVABLE_CANONICALS: frozenset[str] = frozenset(
    {
        "enzymes",
        "mono- and diglycerides",
    }
)

ETHANOL_CANONICALS: frozenset[str] = frozenset(
    {
        "vanilla extract",
        "alcohol / wine",
    }
)

UNRESOLVED_FLAG_STATUSES: frozenset[FlagResolutionStatus] = frozenset(
    {
        FlagResolutionStatus.unresolved,
        FlagResolutionStatus.supplier_varies,
        FlagResolutionStatus.expired_verification,
        FlagResolutionStatus.formulation_changed,
        FlagResolutionStatus.confirmed_haram,
    }
)


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _is_date_expired(expires_at: str | None, today: date | None = None) -> bool:
    exp = _parse_iso_date(expires_at)
    if exp is None:
        return False
    ref = today or _today_utc()
    return exp < ref


def _is_date_expiring_or_expired(
    expires_at: str | None,
    today: date | None = None,
    soon_days: int = EXPIRING_SOON_DAYS,
) -> bool:
    exp = _parse_iso_date(expires_at)
    if exp is None:
        return False
    ref = today or _today_utc()
    return exp <= (ref + timedelta(days=soon_days))


def is_trusted_kosher_symbol(symbol: str | None) -> bool:
    """Return True only for recognized agencies (OU/OK/Star-K/Kof-K), never generic 'K'."""
    if not symbol:
        return False
    normalized = symbol.strip().lower().replace(" ", "-")
    return normalized in TRUSTED_KOSHER_SYMBOLS


# ---------------------------------------------------------------------------
# Strictness Profile Settings
# ---------------------------------------------------------------------------


def get_strictness_profile(conn: sqlite3.Connection) -> StrictnessProfile:
    """Load the persisted StrictnessProfile or return the default strict profile."""
    stored = db.get_setting(conn, STRICTNESS_SETTING_KEY)
    if isinstance(stored, dict):
        return StrictnessProfile.model_validate(stored)
    return StrictnessProfile()


def update_strictness_profile(
    conn: sqlite3.Connection,
    profile: StrictnessProfile,
) -> StrictnessProfile:
    """Persist updated StrictnessProfile and recompute all product statuses."""
    db.set_setting(conn, STRICTNESS_SETTING_KEY, profile.model_dump())
    recompute_all_products(conn)
    return profile


# ---------------------------------------------------------------------------
# Row-to-Schema Helpers
# ---------------------------------------------------------------------------


def _row_to_snapshot(row: sqlite3.Row) -> FormulationSnapshot:
    return FormulationSnapshot(
        id=row["id"],
        product_id=row["product_id"],
        raw_ingredients=row["raw_ingredients"],
        normalized_ingredients=row["normalized_ingredients"],
        ingredient_hash=row["ingredient_hash"],
        source_type=row["source_type"],
        lot_code=row["lot_code"],
        plant_code=row["plant_code"],
        captured_at=row["captured_at"],
        is_current=bool(row["is_current"]),
    )


def _row_to_outreach(row: sqlite3.Row) -> OutreachInquiry:
    return OutreachInquiry(
        id=row["id"],
        product_id=row["product_id"],
        formulation_snapshot_id=row["formulation_snapshot_id"],
        target_email=row["target_email"],
        flagged_ingredients=json.loads(row["flagged_ingredients_json"] or "[]"),
        generated_subject=row["generated_subject"],
        generated_body=row["generated_body"],
        mode=row["mode"],
        state=OutreachState(row["state"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_forum_signal(row: sqlite3.Row) -> ForumSignal:
    return ForumSignal(
        id=row["id"],
        product_id=row["product_id"],
        source_platform=row["source_platform"],
        source_name=row["source_name"],
        url=row["url"],
        title=row["title"],
        author=row["author"],
        posted_at=row["posted_at"],
        raw_excerpt=row["raw_excerpt"],
        matched_ingredients=json.loads(row["matched_ingredients_json"] or "[]"),
        claimed_determination=Determination(row["claimed_determination"]),
        evidence_tier=EvidenceTier(row["evidence_tier"]),
        freshness=FreshnessBucket(row["freshness"]),
        region_flag=RegionFlag(row["region_flag"]),
        region_notes=row["region_notes"],
        fetched_at=row["fetched_at"],
    )


def _row_to_community_note(row: sqlite3.Row) -> CommunityNote:
    return CommunityNote(
        id=row["id"],
        product_id=row["product_id"],
        author_label=row["author_label"],
        note_text=row["note_text"],
        confidence_tier=row["confidence_tier"],
        created_at=row["created_at"],
    )


def _dict_to_brand_policy(item: dict[str, Any], today: date) -> BrandPolicy:
    return BrandPolicy(
        id=item["id"],
        brand=item["brand"],
        scope_description=item["scope_description"],
        applies_to_ingredients=list(item["applies_to_ingredients"]),
        determination=Determination(item["determination"]),
        source_url=item.get("source_url"),
        excerpt=item["excerpt"],
        checked_date=item["checked_date"],
        expires_at=item.get("expires_at"),
        is_expired=_is_date_expired(item.get("expires_at"), today),
    )


# ---------------------------------------------------------------------------
# Forum Signal Consensus Summary
# ---------------------------------------------------------------------------


def _extract_signal_field(sig: Any, key: str) -> Any:
    if isinstance(sig, ForumSignal):
        val = getattr(sig, key)
        return val.value if hasattr(val, "value") else val
    if isinstance(sig, dict):
        val = sig.get(key)
        return val.value if hasattr(val, "value") else val
    # sqlite3.Row
    return sig[key]


def summarize_forum_signals(signal_rows: list[Any]) -> ForumConsensus:
    """Aggregate community/forum signals into a secondary consensus summary."""
    counts: dict[str, int] = {
        "plant_or_microbial": 0,
        "varies_by_supplier": 0,
        "animal_or_haram": 0,
        "unclear": 0,
    }
    total = len(signal_rows)
    if total == 0:
        return ForumConsensus(
            total_signals=0,
            counts_by_determination=counts,
            quoted_company_replies=0,
            official_brand_faqs=0,
            has_conflict=False,
            has_non_us_warning=False,
            non_us_count=0,
            newest_post_date=None,
            summary_line="No community or forum reports logged yet.",
        )

    quoted_replies = 0
    official_faqs = 0
    non_us_count = 0
    post_dates: list[str] = []

    for sig in signal_rows:
        det = str(_extract_signal_field(sig, "claimed_determination") or "unclear")
        if det == "synthetic":
            counts["plant_or_microbial"] += 1
        elif det in counts:
            counts[det] += 1
        else:
            counts["unclear"] += 1

        tier = str(_extract_signal_field(sig, "evidence_tier") or "")
        if tier == EvidenceTier.quoted_company_reply.value:
            quoted_replies += 1
        elif tier == EvidenceTier.official_brand_faq.value:
            official_faqs += 1

        region = str(_extract_signal_field(sig, "region_flag") or "")
        if region == RegionFlag.non_us_warning.value:
            non_us_count += 1

        posted_at = _extract_signal_field(sig, "posted_at")
        if posted_at:
            post_dates.append(str(posted_at))

    positive_count = counts["plant_or_microbial"]
    caution_count = counts["varies_by_supplier"]
    negative_count = counts["animal_or_haram"]

    has_conflict = (
        (positive_count > 0 and (caution_count > 0 or negative_count > 0))
        or (caution_count > 0 and negative_count > 0)
    )
    has_non_us_warning = non_us_count > 0
    newest_post_date = max(post_dates) if post_dates else None

    claim_parts: list[str] = []
    if positive_count > 0:
        verb = "reports" if positive_count == 1 else "report"
        detail_bits: list[str] = []
        if official_faqs > 0:
            detail_bits.append(
                f"{official_faqs} official FAQ" if official_faqs == 1 else f"{official_faqs} official FAQs"
            )
        if quoted_replies > 0:
            detail_bits.append(
                f"{quoted_replies} quoted reply" if quoted_replies == 1 else f"{quoted_replies} quoted replies"
            )
        suffix = f" ({', '.join(detail_bits)})" if detail_bits else ""
        claim_parts.append(f"{positive_count} {verb} plant/microbial{suffix}")
    if caution_count > 0:
        verb = "reports" if caution_count == 1 else "report"
        claim_parts.append(f"{caution_count} {verb} varies by supplier")
    if negative_count > 0:
        verb = "reports" if negative_count == 1 else "report"
        claim_parts.append(f"{negative_count} {verb} animal/haram")
    if counts["unclear"] > 0 and not claim_parts:
        claim_parts.append(f"{counts['unclear']} unclear")

    summary_segments: list[str] = []
    if claim_parts:
        summary_segments.append(", ".join(claim_parts))
    if has_conflict:
        summary_segments.append("Conflicting reports")
    if has_non_us_warning:
        noun = "thread" if non_us_count == 1 else "threads"
        summary_segments.append(f"{non_us_count} non-U.S. {noun} flagged")

    summary_line = " • ".join(summary_segments) + "." if summary_segments else "Community signals available."

    return ForumConsensus(
        total_signals=total,
        counts_by_determination=counts,
        quoted_company_replies=quoted_replies,
        official_brand_faqs=official_faqs,
        has_conflict=has_conflict,
        has_non_us_warning=has_non_us_warning,
        non_us_count=non_us_count,
        newest_post_date=newest_post_date,
        summary_line=summary_line,
    )


# ---------------------------------------------------------------------------
# Verification & Policy Matching Helpers
# ---------------------------------------------------------------------------


def _verification_matches_ingredient(
    verification: CompanyVerification,
    canonical_name: str,
    aliases: list[str],
) -> bool:
    v_name = verification.ingredient_name.strip().lower()
    if v_name in {"all", "all ingredients", "all flagged", "all flagged ingredients"}:
        return True
    canon_lower = canonical_name.lower()
    if v_name == canon_lower:
        return True
    alias_set = {a.strip().lower() for a in aliases}
    if v_name in alias_set:
        return True
    # Allow "gelatin" verification to also link onto "pork gelatin" flag when confirming haram.
    if canon_lower == "pork gelatin" and v_name in {"gelatin", "porcine gelatin", "pork gelatin"}:
        return True
    return False


def _policy_matches_ingredient(policy: BrandPolicy, canonical_name: str) -> bool:
    canon_lower = canonical_name.lower()
    return any(item.strip().lower() == canon_lower for item in policy.applies_to_ingredients)


def _evaluate_flags_and_status(
    *,
    raw_ingredients: str,
    rules: list[dict[str, Any]],
    profile: StrictnessProfile,
    certifier_name: str | None,
    certifier_status: str | None,
    kosher_symbol: str | None,
    is_certified_vegan: bool,
    verifications: list[CompanyVerification],
    brand_policies: list[BrandPolicy],
    diff_from_verified: FormulationDiff | None,
    has_prior_verified_snapshot: bool,
) -> tuple[
    ProductStatus,
    list[str],
    list[IngredientFlag],
    BrandPolicy | None,
]:
    """Core pure-deterministic 5-state precedence evaluator."""
    matches = match_ingredient_rules(raw_ingredients, rules)

    active_current_verifications = [
        v for v in verifications if v.matches_current_snapshot and not v.is_expired
    ]
    expired_current_verifications = [
        v for v in verifications if v.matches_current_snapshot and v.is_expired
    ]
    fresh_policies = [p for p in brand_policies if not p.is_expired]

    is_active_halal_certified = bool(
        certifier_name and (certifier_status or "").strip().lower() == "active"
    )
    trusted_kosher = is_trusted_kosher_symbol(kosher_symbol)

    flags: list[IngredientFlag] = []
    matched_policy: BrandPolicy | None = None

    for match in matches:
        rule = match["rule"]
        canonical_name: str = match["canonical_name"]
        canon_lower = canonical_name.lower()
        aliases: list[str] = list(rule.get("aliases") or [])
        default_risk = IngredientRisk(str(rule["default_risk"]))
        explicit_safe = bool(match["explicit_label_safe"])
        explicit_safe_reason: str | None = match.get("explicit_safe_reason")

        # Matching verifications on the current snapshot for this ingredient.
        ing_active_vers = [
            v for v in active_current_verifications
            if _verification_matches_ingredient(v, canonical_name, aliases)
        ]
        ing_expired_vers = [
            v for v in expired_current_verifications
            if _verification_matches_ingredient(v, canonical_name, aliases)
        ]
        ing_fresh_policies = [
            p for p in fresh_policies if _policy_matches_ingredient(p, canonical_name)
        ]

        risk = default_risk
        resolution_status = FlagResolutionStatus.unresolved
        resolution_detail = "No active manufacturer verification for this formulation snapshot."
        verification_id: str | None = None
        brand_policy_id: str | None = None

        # 1. Explicit haram ingredient rule (e.g. pork gelatin, lard, carmine, alcohol/wine)
        if default_risk == IngredientRisk.haram_animal:
            resolution_status = FlagResolutionStatus.confirmed_haram
            resolution_detail = (
                f"Flagged as haram/animal-derived ingredient ('{match['matched_token']}')."
            )
            if ing_active_vers:
                haram_ver = next(
                    (v for v in ing_active_vers if v.determination == Determination.animal_or_haram),
                    ing_active_vers[0],
                )
                verification_id = haram_ver.id
                resolution_detail = (
                    f"Confirmed animal/haram source via manufacturer verification ({haram_ver.verified_date}): "
                    f"{haram_ver.response_excerpt}"
                )

        # 2. Active company verification bound to current formulation snapshot
        elif ing_active_vers:
            best_ver = ing_active_vers[0]
            verification_id = best_ver.id
            if best_ver.determination == Determination.animal_or_haram:
                risk = IngredientRisk.haram_animal
                resolution_status = FlagResolutionStatus.confirmed_haram
                resolution_detail = (
                    f"Manufacturer confirmed animal/haram source ({best_ver.verified_date}): "
                    f"{best_ver.response_excerpt}"
                )
            elif best_ver.varies_by_supplier or best_ver.determination == Determination.varies_by_supplier:
                resolution_status = FlagResolutionStatus.supplier_varies
                resolution_detail = (
                    f"Manufacturer reported source varies by supplier/plant ({best_ver.verified_date}): "
                    f"{best_ver.response_excerpt}"
                )
            elif best_ver.determination in (
                Determination.plant_or_microbial,
                Determination.synthetic,
            ):
                resolution_status = FlagResolutionStatus.verified_plant_or_microbial
                resolution_detail = (
                    f"Verified {best_ver.determination.value.replace('_', '/')} via "
                    f"{best_ver.contact_channel} ({best_ver.verified_date})."
                )
            else:
                resolution_status = FlagResolutionStatus.unresolved
                resolution_detail = (
                    f"Manufacturer reply ({best_ver.verified_date}) was unclear and requires follow-up."
                )

        # 3. StrictnessProfile relaxations (informational / caution_context)
        elif (
            (canon_lower == "whey" and not profile.flag_whey_strictly)
            or (canon_lower == "natural flavors" and not profile.flag_natural_flavors)
            or (canon_lower == "vanilla extract" and not profile.flag_vanilla_ethanol)
        ):
            risk = IngredientRisk.caution_context
            resolution_status = FlagResolutionStatus.informational
            resolution_detail = (
                f"Marked informational under current strictness profile ('{profile.preset}')."
            )

        # 4. Explicit plant/microbial/safe label qualifier
        elif explicit_safe:
            resolution_status = FlagResolutionStatus.verified_plant_or_microbial
            resolution_detail = (
                explicit_safe_reason
                or f"Label explicitly indicates plant/microbial origin ('{match['matched_token']}')."
            )

        # 5. Certified Vegan (excluding ethanol / vanilla extract)
        elif is_certified_vegan and canon_lower not in ETHANOL_CANONICALS:
            resolution_status = FlagResolutionStatus.resolved_via_vegan
            resolution_detail = "Product is certified vegan, ruling out animal-derived ingredients."

        # 6. Fresh matching BrandPolicy
        elif ing_fresh_policies:
            pol = ing_fresh_policies[0]
            brand_policy_id = pol.id
            if matched_policy is None:
                matched_policy = pol
            if pol.determination == Determination.animal_or_haram:
                risk = IngredientRisk.haram_animal
                resolution_status = FlagResolutionStatus.confirmed_haram
                resolution_detail = f"Brand policy ({pol.brand}) indicates animal/haram source."
            elif pol.determination == Determination.varies_by_supplier:
                resolution_status = FlagResolutionStatus.supplier_varies
                resolution_detail = f"Brand policy ({pol.brand}) indicates source varies by supplier."
            elif pol.determination in (
                Determination.plant_or_microbial,
                Determination.synthetic,
            ):
                resolution_status = FlagResolutionStatus.verified_brand_policy
                resolution_detail = (
                    f"Covered by {pol.brand} brand policy (checked {pol.checked_date}): "
                    f"{pol.scope_description}"
                )
            else:
                resolution_status = FlagResolutionStatus.unresolved
                resolution_detail = f"Brand policy ({pol.brand}) is unclear for this ingredient."

        # 7. Active Halal Certifier (when no formulation drift invalidates prior check)
        elif is_active_halal_certified and not has_prior_verified_snapshot:
            resolution_status = FlagResolutionStatus.verified_plant_or_microbial
            resolution_detail = f"Covered by active halal certification ({certifier_name})."

        # 8. Trusted Kosher strictness profile for enzymes & mono- and diglycerides
        elif (
            profile.treat_oud_enzymes_as_verified
            and trusted_kosher
            and canon_lower in KOSHER_RESOLVABLE_CANONICALS
        ):
            resolution_status = FlagResolutionStatus.resolved_via_kosher_profile
            resolution_detail = (
                f"Resolved via trusted kosher certification ({kosher_symbol}) "
                f"under current strictness profile."
            )

        # 9. Formulation changed since last active verification
        elif has_prior_verified_snapshot and diff_from_verified is not None:
            resolution_status = FlagResolutionStatus.formulation_changed
            resolution_detail = (
                "Ingredient list changed since the previous verified snapshot; "
                "re-verification is required for this formulation."
            )

        # 10. Expired manufacturer verification on current snapshot
        elif ing_expired_vers:
            exp_ver = ing_expired_vers[0]
            verification_id = exp_ver.id
            resolution_status = FlagResolutionStatus.expired_verification
            resolution_detail = (
                f"Previous verification from {exp_ver.verified_date} expired on "
                f"{exp_ver.expires_at}; fresh confirmation required."
            )

        flags.append(
            IngredientFlag(
                canonical_name=canonical_name,
                matched_token=match["matched_token"],
                parent_context=match["parent_context"],
                risk=risk,
                resolution_status=resolution_status,
                resolution_detail=resolution_detail,
                us_context_notes=rule["us_context_notes"],
                verification_question=rule["verification_question"],
                kosher_vegan_caveat=rule["kosher_vegan_caveat"],
                verification_id=verification_id,
                brand_policy_id=brand_policy_id,
            )
        )

    # Pick representative brand policy for ProductDetail display if none directly resolved a flag.
    if matched_policy is None and brand_policies:
        matched_policy = fresh_policies[0] if fresh_policies else brand_policies[0]

    # -----------------------------------------------------------------------
    # Deterministic 5-State Precedence Engine
    # -----------------------------------------------------------------------
    reasons: list[str] = []

    haram_flags = [
        f
        for f in flags
        if f.risk == IngredientRisk.haram_animal
        or f.resolution_status == FlagResolutionStatus.confirmed_haram
    ]
    haram_current_verifications = [
        v for v in active_current_verifications if v.determination == Determination.animal_or_haram
    ]

    supplier_vary_flags = [
        f for f in flags if f.resolution_status == FlagResolutionStatus.supplier_varies
    ]
    supplier_vary_verifications = [
        v
        for v in active_current_verifications
        if v.varies_by_supplier or v.determination == Determination.varies_by_supplier
    ]
    drift_flags = [
        f for f in flags if f.resolution_status == FlagResolutionStatus.formulation_changed
    ]
    expired_flags = [
        f for f in flags if f.resolution_status == FlagResolutionStatus.expired_verification
    ]
    unresolved_flags = [
        f for f in flags if f.resolution_status == FlagResolutionStatus.unresolved
    ]

    # Precedence 1: animal_or_haram
    if haram_flags or haram_current_verifications:
        status = ProductStatus.animal_or_haram
        for f in haram_flags:
            reasons.append(f"{f.canonical_name}: {f.resolution_detail}")
        if not haram_flags:
            for v in haram_current_verifications:
                reasons.append(
                    f"Active verification confirms {v.ingredient_name} is animal/haram ({v.verified_date})."
                )

    # Precedence 2: formulation_changed
    elif has_prior_verified_snapshot and diff_from_verified is not None and (
        bool(drift_flags)
        or (not active_current_verifications and (diff_from_verified.added_ingredients or diff_from_verified.removed_ingredients))
    ):
        status = ProductStatus.formulation_changed
        added_str = ", ".join(diff_from_verified.added_ingredients) if diff_from_verified.added_ingredients else "none"
        removed_str = ", ".join(diff_from_verified.removed_ingredients) if diff_from_verified.removed_ingredients else "none"
        reasons.append(
            f"Formulation changed since verified snapshot ({diff_from_verified.previous_captured_at[:10]}): "
            f"added [{added_str}]; removed [{removed_str}]."
        )
        if drift_flags:
            names = ", ".join(f.canonical_name for f in drift_flags)
            reasons.append(f"Re-verification required for: {names}.")

    # Precedence 3: certified_halal
    elif is_active_halal_certified:
        status = ProductStatus.certified_halal
        reasons.append(f"Active halal certification by {certifier_name}.")

    # Precedence 4: mushbooh_needs_check
    elif (
        unresolved_flags
        or supplier_vary_flags
        or supplier_vary_verifications
        or expired_flags
    ):
        status = ProductStatus.mushbooh_needs_check
        if supplier_vary_flags or supplier_vary_verifications:
            vary_names = sorted(
                {f.canonical_name for f in supplier_vary_flags}
                | {v.ingredient_name for v in supplier_vary_verifications}
            )
            reasons.append(
                f"Source varies by supplier/manufacturing plant for: {', '.join(vary_names)}."
            )
        if expired_flags:
            exp_names = ", ".join(f.canonical_name for f in expired_flags)
            reasons.append(f"Expired manufacturer verification for: {exp_names}.")
        if unresolved_flags:
            unres_names = ", ".join(f.canonical_name for f in unresolved_flags)
            reasons.append(f"Unverified mushbooh ingredient(s) require confirmation: {unres_names}.")

    # Precedence 5: verified_plant_or_microbial
    else:
        status = ProductStatus.verified_plant_or_microbial
        if not flags:
            if is_certified_vegan:
                reasons.append("Certified vegan product with no flagged animal or alcohol ingredients.")
            else:
                reasons.append("No haram or unresolved mushbooh ingredients detected on current label.")
        else:
            if any(f.resolution_status == FlagResolutionStatus.verified_plant_or_microbial for f in flags):
                resolved_names = ", ".join(
                    f.canonical_name
                    for f in flags
                    if f.resolution_status == FlagResolutionStatus.verified_plant_or_microbial
                )
                reasons.append(f"Verified plant/microbial or explicitly labeled safe: {resolved_names}.")
            if any(f.resolution_status == FlagResolutionStatus.verified_brand_policy for f in flags):
                pol_names = ", ".join(
                    f.canonical_name
                    for f in flags
                    if f.resolution_status == FlagResolutionStatus.verified_brand_policy
                )
                reasons.append(f"Resolved via active brand policy: {pol_names}.")
            if any(f.resolution_status == FlagResolutionStatus.resolved_via_vegan for f in flags):
                vegan_names = ", ".join(
                    f.canonical_name
                    for f in flags
                    if f.resolution_status == FlagResolutionStatus.resolved_via_vegan
                )
                reasons.append(f"Resolved via certified vegan status: {vegan_names}.")
            if any(f.resolution_status == FlagResolutionStatus.resolved_via_kosher_profile for f in flags):
                kosher_names = ", ".join(
                    f.canonical_name
                    for f in flags
                    if f.resolution_status == FlagResolutionStatus.resolved_via_kosher_profile
                )
                reasons.append(
                    f"Resolved via {kosher_symbol} kosher profile setting: {kosher_names}."
                )
            if not reasons:
                reasons.append("All flagged ingredients are informational under current strictness profile.")

    return status, reasons, flags, matched_policy


# ---------------------------------------------------------------------------
# Public Engine Functions
# ---------------------------------------------------------------------------


def evaluate_product(
    conn: sqlite3.Connection,
    product_id: str,
    persist_status: bool = True,
) -> ProductDetail:
    """Evaluate a product under the 5-state precedence engine and return full ProductDetail."""
    product_row = db.fetch_product_row(conn, product_id)
    if product_row is None:
        raise KeyError(f"Product not found: {product_id}")

    snapshots_rows = db.fetch_snapshots_for_product(conn, product_id)
    if not snapshots_rows:
        raise ValueError(f"Product {product_id} has no formulation snapshots")

    current_snap_row = next(
        (r for r in snapshots_rows if bool(r["is_current"])),
        snapshots_rows[0],
    )
    previous_snap_row = next(
        (r for r in snapshots_rows if r["id"] != current_snap_row["id"]),
        None,
    )

    current_snapshot = _row_to_snapshot(current_snap_row)
    previous_snapshot = _row_to_snapshot(previous_snap_row) if previous_snap_row else None

    snap_by_id = {r["id"]: r for r in snapshots_rows}
    today = _today_utc()

    ver_rows = db.fetch_verifications_for_product(conn, product_id)
    verifications: list[CompanyVerification] = []
    for vr in ver_rows:
        linked_snap = snap_by_id.get(vr["formulation_snapshot_id"])
        linked_hash = linked_snap["ingredient_hash"] if linked_snap else None
        matches_current = (
            vr["formulation_snapshot_id"] == current_snapshot.id
            or (linked_hash is not None and linked_hash == current_snapshot.ingredient_hash)
        )
        verifications.append(
            CompanyVerification(
                id=vr["id"],
                product_id=vr["product_id"],
                formulation_snapshot_id=vr["formulation_snapshot_id"],
                ingredient_name=vr["ingredient_name"],
                determination=Determination(vr["determination"]),
                varies_by_supplier=bool(vr["varies_by_supplier"]),
                contact_channel=vr["contact_channel"],
                company_contact=vr["company_contact"],
                response_excerpt=vr["response_excerpt"],
                lot_code=vr["lot_code"],
                plant_code=vr["plant_code"],
                verified_date=vr["verified_date"],
                expires_at=vr["expires_at"],
                is_expired=_is_date_expired(vr["expires_at"], today),
                matches_current_snapshot=matches_current,
            )
        )

    # Check if an active verification exists on an earlier snapshot with a different ingredient hash.
    prior_active_vers = [
        v
        for v in verifications
        if not v.is_expired
        and not v.matches_current_snapshot
        and v.formulation_snapshot_id in snap_by_id
    ]
    diff_from_verified: FormulationDiff | None = None
    has_prior_verified_snapshot = False
    if prior_active_vers:
        # verifications are already sorted newest verified_date first.
        latest_prior_ver = prior_active_vers[0]
        prior_snap_row = snap_by_id[latest_prior_ver.formulation_snapshot_id]
        if prior_snap_row["ingredient_hash"] != current_snapshot.ingredient_hash:
            has_prior_verified_snapshot = True
            added, removed = compute_ingredient_diff(
                prior_snap_row["raw_ingredients"],
                current_snapshot.raw_ingredients,
            )
            diff_from_verified = FormulationDiff(
                previous_snapshot_id=prior_snap_row["id"],
                previous_captured_at=prior_snap_row["captured_at"],
                added_ingredients=added,
                removed_ingredients=removed,
            )

    rules = db.fetch_all_ingredient_rules(conn)
    profile = get_strictness_profile(conn)
    brand_policy_dicts = db.fetch_brand_policies(conn, brand=product_row["brand"])
    brand_policies = [_dict_to_brand_policy(bp, today) for bp in brand_policy_dicts]

    computed_status, status_reasons, flags, matched_policy = _evaluate_flags_and_status(
        raw_ingredients=current_snapshot.raw_ingredients,
        rules=rules,
        profile=profile,
        certifier_name=product_row["certifier_name"],
        certifier_status=product_row["certifier_status"],
        kosher_symbol=product_row["kosher_symbol"],
        is_certified_vegan=bool(product_row["is_certified_vegan"]),
        verifications=verifications,
        brand_policies=brand_policies,
        diff_from_verified=diff_from_verified,
        has_prior_verified_snapshot=has_prior_verified_snapshot,
    )

    if persist_status and product_row["computed_status"] != computed_status.value:
        conn.execute(
            "UPDATE products SET computed_status = ? WHERE id = ?",
            (computed_status.value, product_id),
        )

    outreach_rows = db.fetch_outreach_for_product(conn, product_id)
    outreach_inquiries = [_row_to_outreach(r) for r in outreach_rows]

    signal_rows = db.fetch_forum_signals_for_product(conn, product_id)
    forum_signals = [_row_to_forum_signal(r) for r in signal_rows]
    forum_consensus = summarize_forum_signals(forum_signals)

    note_rows = db.fetch_community_notes_for_product(conn, product_id)
    community_notes = [_row_to_community_note(r) for r in note_rows]

    unresolved_count = sum(
        1 for f in flags if f.resolution_status in UNRESOLVED_FLAG_STATUSES
    )
    flagged_ingredient_names = sorted(
        f.canonical_name
        for f in flags
        if f.resolution_status != FlagResolutionStatus.informational
    )

    return ProductDetail(
        id=product_row["id"],
        upc=product_row["upc"],
        name=product_row["name"],
        brand=product_row["brand"],
        category=product_row["category"],
        certifier_name=product_row["certifier_name"],
        certifier_status=product_row["certifier_status"],
        kosher_symbol=product_row["kosher_symbol"],
        is_certified_vegan=bool(product_row["is_certified_vegan"]),
        computed_status=computed_status,
        unresolved_count=unresolved_count,
        flagged_ingredient_names=flagged_ingredient_names,
        forum_signal_count=forum_consensus.total_signals,
        has_forum_conflict=forum_consensus.has_conflict,
        updated_at=product_row["updated_at"],
        brand_contact_email=product_row["brand_contact_email"],
        brand_contact_url=product_row["brand_contact_url"],
        status_reasons=status_reasons,
        current_snapshot=current_snapshot,
        previous_snapshot=previous_snapshot,
        diff_from_verified=diff_from_verified,
        ingredient_flags=flags,
        verifications=verifications,
        brand_policy=matched_policy,
        outreach_inquiries=outreach_inquiries,
        forum_signals=forum_signals,
        forum_consensus=forum_consensus,
        community_notes=community_notes,
    )


def evaluate_raw_ingredients(
    conn: sqlite3.Connection,
    raw_ingredients: str,
    *,
    product_id: str | None = None,
    profile: StrictnessProfile | None = None,
) -> dict[str, Any]:
    """Evaluate raw OCR/pasted ingredient text without necessarily mutating DB state."""
    normalized = normalize_ingredients(raw_ingredients)
    ing_hash = compute_ingredient_hash(raw_ingredients)
    parsed_token_dicts = parse_ingredient_tokens(raw_ingredients)
    parsed_tokens = [
        t["token"] for t in parsed_token_dicts if t.get("is_leaf")
    ] or [t["token"] for t in parsed_token_dicts]

    rules = db.fetch_all_ingredient_rules(conn)
    active_profile = profile or get_strictness_profile(conn)
    today = _today_utc()

    certifier_name: str | None = None
    certifier_status: str | None = None
    kosher_symbol: str | None = None
    is_certified_vegan = False
    verifications: list[CompanyVerification] = []
    brand_policies: list[BrandPolicy] = []
    drift_detected = False
    added: list[str] = []
    removed: list[str] = []
    diff_from_verified: FormulationDiff | None = None
    has_prior_verified_snapshot = False

    if product_id:
        product_row = db.fetch_product_row(conn, product_id)
        if product_row is None:
            raise KeyError(f"Product not found: {product_id}")
        certifier_name = product_row["certifier_name"]
        certifier_status = product_row["certifier_status"]
        kosher_symbol = product_row["kosher_symbol"]
        is_certified_vegan = bool(product_row["is_certified_vegan"])
        brand_policies = [
            _dict_to_brand_policy(bp, today)
            for bp in db.fetch_brand_policies(conn, brand=product_row["brand"])
        ]

        snapshots_rows = db.fetch_snapshots_for_product(conn, product_id)
        snap_by_id = {r["id"]: r for r in snapshots_rows}
        current_snap = next(
            (r for r in snapshots_rows if bool(r["is_current"])),
            snapshots_rows[0] if snapshots_rows else None,
        )
        if current_snap is not None and current_snap["ingredient_hash"] != ing_hash:
            drift_detected = True
            added, removed = compute_ingredient_diff(
                current_snap["raw_ingredients"],
                raw_ingredients,
            )

        for vr in db.fetch_verifications_for_product(conn, product_id):
            linked_snap = snap_by_id.get(vr["formulation_snapshot_id"])
            linked_hash = linked_snap["ingredient_hash"] if linked_snap else None
            matches_new = linked_hash is not None and linked_hash == ing_hash
            verifications.append(
                CompanyVerification(
                    id=vr["id"],
                    product_id=vr["product_id"],
                    formulation_snapshot_id=vr["formulation_snapshot_id"],
                    ingredient_name=vr["ingredient_name"],
                    determination=Determination(vr["determination"]),
                    varies_by_supplier=bool(vr["varies_by_supplier"]),
                    contact_channel=vr["contact_channel"],
                    company_contact=vr["company_contact"],
                    response_excerpt=vr["response_excerpt"],
                    lot_code=vr["lot_code"],
                    plant_code=vr["plant_code"],
                    verified_date=vr["verified_date"],
                    expires_at=vr["expires_at"],
                    is_expired=_is_date_expired(vr["expires_at"], today),
                    matches_current_snapshot=matches_new,
                )
            )

        prior_active_vers = [
            v
            for v in verifications
            if not v.is_expired
            and not v.matches_current_snapshot
            and v.formulation_snapshot_id in snap_by_id
        ]
        if prior_active_vers:
            prior_snap = snap_by_id[prior_active_vers[0].formulation_snapshot_id]
            if prior_snap["ingredient_hash"] != ing_hash:
                has_prior_verified_snapshot = True
                v_added, v_removed = compute_ingredient_diff(
                    prior_snap["raw_ingredients"],
                    raw_ingredients,
                )
                diff_from_verified = FormulationDiff(
                    previous_snapshot_id=prior_snap["id"],
                    previous_captured_at=prior_snap["captured_at"],
                    added_ingredients=v_added,
                    removed_ingredients=v_removed,
                )

    projected_status, status_reasons, flags, _ = _evaluate_flags_and_status(
        raw_ingredients=raw_ingredients,
        rules=rules,
        profile=active_profile,
        certifier_name=certifier_name,
        certifier_status=certifier_status,
        kosher_symbol=kosher_symbol,
        is_certified_vegan=is_certified_vegan,
        verifications=verifications,
        brand_policies=brand_policies,
        diff_from_verified=diff_from_verified,
        has_prior_verified_snapshot=has_prior_verified_snapshot,
    )

    return {
        "normalized_ingredients": normalized,
        "ingredient_hash": ing_hash,
        "parsed_tokens": parsed_tokens,
        "flagged_ingredients": flags,
        "projected_status": projected_status,
        "status_reasons": status_reasons,
        "drift_detected": drift_detected,
        "added_ingredients": added,
        "removed_ingredients": removed,
    }


def _detail_to_summary(detail: ProductDetail) -> ProductSummary:
    return ProductSummary(
        id=detail.id,
        upc=detail.upc,
        name=detail.name,
        brand=detail.brand,
        category=detail.category,
        certifier_name=detail.certifier_name,
        certifier_status=detail.certifier_status,
        kosher_symbol=detail.kosher_symbol,
        is_certified_vegan=detail.is_certified_vegan,
        computed_status=detail.computed_status,
        unresolved_count=detail.unresolved_count,
        flagged_ingredient_names=detail.flagged_ingredient_names,
        forum_signal_count=detail.forum_signal_count,
        has_forum_conflict=detail.has_forum_conflict,
        updated_at=detail.updated_at,
    )


def get_product_summary(conn: sqlite3.Connection, product_id: str) -> ProductSummary:
    """Evaluate a product and return its compact ProductSummary."""
    detail = evaluate_product(conn, product_id, persist_status=True)
    return _detail_to_summary(detail)


def list_product_summaries(
    conn: sqlite3.Connection,
    q: str | None = None,
    status: str | None = None,
) -> list[ProductSummary]:
    """List evaluated ProductSummary items filtered by optional search query and status."""
    rows = db.list_product_rows(conn, q=q, status=None)
    summaries: list[ProductSummary] = []
    status_filter = status.strip() if status and status.strip() else None

    for row in rows:
        detail = evaluate_product(conn, row["id"], persist_status=True)
        if status_filter and detail.computed_status.value != status_filter:
            continue
        summaries.append(_detail_to_summary(detail))
    return summaries


def recompute_all_products(conn: sqlite3.Connection) -> list[ProductSummary]:
    """Re-evaluate and persist computed_status for every product in the database."""
    rows = db.list_product_rows(conn)
    summaries: list[ProductSummary] = []
    for row in rows:
        detail = evaluate_product(conn, row["id"], persist_status=True)
        summaries.append(_detail_to_summary(detail))
    return summaries


def build_review_queue(conn: sqlite3.Connection) -> ReviewQueueResponse:
    """Build actionable Review Queue buckets for products and pending outreach."""
    today = _today_utc()
    rows = db.list_product_rows(conn)

    formulation_changed: list[ProductSummary] = []
    expiring_or_expired: list[ProductSummary] = []
    supplier_variability: list[ProductSummary] = []
    mushbooh_unresolved: list[ProductSummary] = []

    for row in rows:
        detail = evaluate_product(conn, row["id"], persist_status=True)
        summary = _detail_to_summary(detail)

        if detail.computed_status == ProductStatus.formulation_changed:
            formulation_changed.append(summary)

        has_expiring_ver = any(
            v.matches_current_snapshot and _is_date_expiring_or_expired(v.expires_at, today)
            for v in detail.verifications
        )
        has_expiring_policy = bool(
            detail.brand_policy
            and _is_date_expiring_or_expired(detail.brand_policy.expires_at, today)
            and any(f.brand_policy_id == detail.brand_policy.id for f in detail.ingredient_flags)
        )
        if has_expiring_ver or has_expiring_policy:
            expiring_or_expired.append(summary)

        has_supplier_var = any(
            f.resolution_status == FlagResolutionStatus.supplier_varies
            for f in detail.ingredient_flags
        ) or any(
            v.matches_current_snapshot
            and not v.is_expired
            and (v.varies_by_supplier or v.determination == Determination.varies_by_supplier)
            for v in detail.verifications
        )
        if has_supplier_var:
            supplier_variability.append(summary)

        has_unresolved_mushbooh = (
            detail.computed_status == ProductStatus.mushbooh_needs_check
            and any(
                f.resolution_status == FlagResolutionStatus.unresolved
                for f in detail.ingredient_flags
            )
        )
        if has_unresolved_mushbooh:
            mushbooh_unresolved.append(summary)

    pending_rows = db.fetch_all_pending_outreach(conn)
    pending_outreach: list[OutreachQueueItem] = []
    for pr in pending_rows:
        updated_date = _parse_iso_date(pr["updated_at"])
        days_since = max(0, (today - updated_date).days) if updated_date else 0
        pending_outreach.append(
            OutreachQueueItem(
                id=pr["id"],
                product_id=pr["product_id"],
                formulation_snapshot_id=pr["formulation_snapshot_id"],
                target_email=pr["target_email"],
                flagged_ingredients=json.loads(pr["flagged_ingredients_json"] or "[]"),
                generated_subject=pr["generated_subject"],
                generated_body=pr["generated_body"],
                mode=pr["mode"],
                state=OutreachState(pr["state"]),
                created_at=pr["created_at"],
                updated_at=pr["updated_at"],
                product_name=pr["product_name"],
                brand=pr["brand"],
                upc=pr["upc"],
                computed_status=ProductStatus(pr["computed_status"]),
                days_since_update=days_since,
            )
        )

    unique_attention_products = {
        p.id
        for bucket in (
            formulation_changed,
            expiring_or_expired,
            supplier_variability,
            mushbooh_unresolved,
        )
        for p in bucket
    }
    counts = ReviewQueueCounts(
        total_attention=len(unique_attention_products) + len(pending_outreach),
        formulation_changed=len(formulation_changed),
        expiring_or_expired=len(expiring_or_expired),
        supplier_variability=len(supplier_variability),
        mushbooh_unresolved=len(mushbooh_unresolved),
        pending_outreach=len(pending_outreach),
    )

    return ReviewQueueResponse(
        formulation_changed=formulation_changed,
        expiring_or_expired=expiring_or_expired,
        supplier_variability=supplier_variability,
        mushbooh_unresolved=mushbooh_unresolved,
        pending_outreach=pending_outreach,
        counts=counts,
    )
