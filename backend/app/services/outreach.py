"""Company outreach email generator, brand/product cooldown checker, and mailto builder."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from urllib.parse import quote

from app import db
from app.config import COOLDOWN_BRAND_DAYS, COOLDOWN_PRODUCT_DAYS
from app.schemas import (
    CooldownWarning,
    EvidenceTier,
    FlagResolutionStatus,
    ForumSignal,
    IngredientFlag,
    OutreachDraftResponse,
    OutreachInquiry,
    OutreachState,
    ProductDetail,
)
from app.services.status_engine import UNRESOLVED_FLAG_STATUSES, evaluate_product


def _parse_utc_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _check_cooldown(
    conn: sqlite3.Connection,
    product_id: str,
    brand: str,
) -> CooldownWarning | None:
    """Check whether this product (30d) or brand (14d) has recent outreach."""
    now = datetime.now(timezone.utc)

    # 1. Check same-product cooldown first (more specific).
    prod_row = conn.execute(
        """
        SELECT created_at, updated_at, state
        FROM outreach_inquiries
        WHERE product_id = ?
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1
        """,
        (product_id,),
    ).fetchone()

    if prod_row is not None:
        ts_str = prod_row["updated_at"] or prod_row["created_at"]
        ts = _parse_utc_dt(ts_str)
        if ts is not None:
            days_ago = max(0, (now - ts).days)
            if days_ago < COOLDOWN_PRODUCT_DAYS:
                return CooldownWarning(
                    active=True,
                    message=(
                        f"An outreach inquiry ({prod_row['state']}) was already logged for this "
                        f"product {days_ago} day{'s' if days_ago != 1 else ''} ago "
                        f"(product cooldown: {COOLDOWN_PRODUCT_DAYS} days). Consider waiting "
                        f"for a reply before emailing again."
                    ),
                    last_contact_at=ts_str,
                    days_ago=days_ago,
                )

    # 2. Check brand-wide cooldown across other products of the same brand.
    brand_row = conn.execute(
        """
        SELECT oi.created_at, oi.updated_at, oi.state, p.name AS product_name
        FROM outreach_inquiries oi
        JOIN products p ON p.id = oi.product_id
        WHERE LOWER(p.brand) = LOWER(?) AND oi.product_id != ?
        ORDER BY oi.updated_at DESC, oi.created_at DESC
        LIMIT 1
        """,
        (brand, product_id),
    ).fetchone()

    if brand_row is not None:
        ts_str = brand_row["updated_at"] or brand_row["created_at"]
        ts = _parse_utc_dt(ts_str)
        if ts is not None:
            days_ago = max(0, (now - ts).days)
            if days_ago < COOLDOWN_BRAND_DAYS:
                return CooldownWarning(
                    active=True,
                    message=(
                        f"{brand} was already contacted regarding '{brand_row['product_name']}' "
                        f"{days_ago} day{'s' if days_ago != 1 else ''} ago "
                        f"(brand cooldown: {COOLDOWN_BRAND_DAYS} days). You may want to combine "
                        f"questions or wait before sending another inquiry."
                    ),
                    last_contact_at=ts_str,
                    days_ago=days_ago,
                )

    return None


def _select_target_flags(detail: ProductDetail) -> list[IngredientFlag]:
    """Select unresolved/changed/supplier-varying flags to include in the email."""
    actionable = [
        f
        for f in detail.ingredient_flags
        if f.resolution_status in UNRESOLVED_FLAG_STATUSES
        and f.resolution_status != FlagResolutionStatus.confirmed_haram
    ]
    if actionable:
        return actionable

    # Fallback if user explicitly generates an email for an already-resolved product.
    non_haram = [
        f
        for f in detail.ingredient_flags
        if f.resolution_status != FlagResolutionStatus.confirmed_haram
    ]
    return non_haram


def _find_reference_signal(
    detail: ProductDetail,
    reference_forum_signal_id: str | None,
) -> ForumSignal | None:
    if reference_forum_signal_id:
        for sig in detail.forum_signals:
            if sig.id == reference_forum_signal_id:
                return sig
    # Pick the newest quoted_company_reply or official_brand_faq if none explicitly specified.
    preferred = [
        sig
        for sig in detail.forum_signals
        if sig.evidence_tier
        in (EvidenceTier.quoted_company_reply, EvidenceTier.official_brand_faq)
    ]
    if preferred:
        return preferred[0]
    return detail.forum_signals[0] if detail.forum_signals else None


def _build_full_inquiry_email(
    detail: ProductDetail,
    target_flags: list[IngredientFlag],
) -> tuple[str, str]:
    upc_part = f" (UPC {detail.upc})" if detail.upc else ""
    subject = f"Ingredient Source Inquiry: {detail.brand} {detail.name}{upc_part}"

    snap = detail.current_snapshot
    lot_lines: list[str] = []
    if snap.lot_code:
        lot_lines.append(f"Lot Code: {snap.lot_code}")
    if snap.plant_code:
        lot_lines.append(f"Plant Code: {snap.plant_code}")
    lot_block = ("\n" + "\n".join(lot_lines)) if lot_lines else ""

    lines: list[str] = [
        f"Hello {detail.brand} Consumer Relations Team,",
        "",
        f"I am reaching out regarding the U.S. retail version of {detail.brand} {detail.name}{upc_part}.{lot_block}",
    ]

    if detail.diff_from_verified is not None:
        added_note = (
            f" (including newly listed {', '.join(detail.diff_from_verified.added_ingredients)})"
            if detail.diff_from_verified.added_ingredients
            else ""
        )
        lines.extend(
            [
                "",
                f"I recently noticed an updated ingredient list on this product{added_note} and would appreciate fresh confirmation for dietary compliance.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "For dietary compliance, could you please confirm the source of the following ingredient(s) currently used in U.S. production?",
            ]
        )

    lines.append("")
    if target_flags:
        for flag in target_flags:
            ctx = f" (in {flag.parent_context})" if flag.parent_context else ""
            lines.append(f"- {flag.canonical_name}{ctx}: {flag.verification_question}")
    else:
        lines.append(
            "- Are any animal-derived ingredients, animal enzymes/rennet, or ethyl alcohol carriers used anywhere in this product?"
        )

    lines.extend(
        [
            "",
            "Additionally, do the sources of these ingredients vary by manufacturing plant, lot, or U.S. supplier, or are they consistent across all U.S. production facilities?",
            "",
            "Thank you very much for your time and assistance!",
            "",
            "Best regards,",
            "[Your Name]",
        ]
    )

    return subject, "\n".join(lines)


def _build_quick_confirmation_email(
    detail: ProductDetail,
    target_flags: list[IngredientFlag],
    ref_signal: ForumSignal | None,
) -> tuple[str, str]:
    upc_part = f" (UPC {detail.upc})" if detail.upc else ""
    subject = f"Quick Confirmation: {detail.brand} {detail.name}{upc_part}"

    ingredient_names = [f.canonical_name for f in target_flags]
    ing_label = ", ".join(ingredient_names) if ingredient_names else "flagged ingredients"

    lines: list[str] = [
        f"Hello {detail.brand} Consumer Relations Team,",
        "",
        f"I am writing to quickly confirm the current U.S. ingredient sourcing for {detail.brand} {detail.name}{upc_part}.",
    ]

    if ref_signal is not None:
        date_str = ref_signal.posted_at or "a prior date"
        claim_labels = {
            "plant_or_microbial": "plant- or microbial-derived",
            "synthetic": "synthetic / non-animal",
            "animal_or_haram": "animal-derived",
            "varies_by_supplier": "variable depending on supplier",
            "unclear": "unconfirmed",
        }
        claim_text = claim_labels.get(
            ref_signal.claimed_determination.value,
            ref_signal.claimed_determination.value.replace("_", " "),
        )
        sig_ings = (
            ", ".join(ref_signal.matched_ingredients)
            if ref_signal.matched_ingredients
            else ing_label
        )
        lines.extend(
            [
                "",
                (
                    f"A community report from {date_str} ({ref_signal.source_name}) noted a prior "
                    f"statement indicating that {sig_ings} in this product are {claim_text}. "
                    f"Could you please confirm whether this is still accurate for current U.S. production?"
                ),
            ]
        )
    else:
        lines.extend(
            [
                "",
                f"Could you please confirm whether the {ing_label} used in current U.S. production are 100% plant, microbial, or synthetic derived (with no animal-derived sources)?",
            ]
        )

    if target_flags:
        lines.append("")
        for flag in target_flags:
            lines.append(f"- {flag.canonical_name}: {flag.verification_question}")

    lines.extend(
        [
            "",
            "Also, please let me know if sourcing for these ingredients varies by U.S. manufacturing plant or supplier.",
            "",
            "Thank you for your help!",
            "",
            "Best regards,",
            "[Your Name]",
        ]
    )

    return subject, "\n".join(lines)


def build_mailto_url(target_email: str | None, subject: str, body: str) -> str:
    """Build a properly RFC-2368 percent-encoded mailto: URI (spaces as %20)."""
    recipient = quote((target_email or "").strip(), safe="@.+_-")
    encoded_subject = quote(subject, safe="")
    encoded_body = quote(body, safe="")
    return f"mailto:{recipient}?subject={encoded_subject}&body={encoded_body}"


def generate_outreach_draft(
    conn: sqlite3.Connection,
    product_id: str,
    target_email: str | None = None,
    mode: str = "full_inquiry",
    reference_forum_signal_id: str | None = None,
    save_draft: bool = True,
) -> OutreachDraftResponse:
    """Generate a tailored manufacturer inquiry email, check cooldowns, and optionally save draft."""
    detail = evaluate_product(conn, product_id, persist_status=False)
    cooldown_warning = _check_cooldown(conn, product_id=detail.id, brand=detail.brand)

    target_flags = _select_target_flags(detail)
    unresolved_names = [f.canonical_name for f in target_flags]
    raw_email = (target_email or detail.brand_contact_email or "").strip()
    if not raw_email:
        from app.services import brand_contacts

        dir_match = brand_contacts.lookup_directory_contact(detail.brand)
        if dir_match and dir_match.get("email"):
            raw_email = str(dir_match["email"]).strip()
    resolved_email = raw_email or None

    normalized_mode = (
        "quick_confirmation" if mode == "quick_confirmation" else "full_inquiry"
    )
    if normalized_mode == "quick_confirmation":
        ref_signal = _find_reference_signal(detail, reference_forum_signal_id)
        subject, body = _build_quick_confirmation_email(detail, target_flags, ref_signal)
    else:
        subject, body = _build_full_inquiry_email(detail, target_flags)

    mailto_url = build_mailto_url(resolved_email, subject, body)

    if save_draft:
        row = db.insert_outreach_inquiry(
            conn,
            product_id=detail.id,
            formulation_snapshot_id=detail.current_snapshot.id,
            target_email=resolved_email,
            flagged_ingredients=unresolved_names,
            generated_subject=subject,
            generated_body=body,
            mode=normalized_mode,
            state=OutreachState.drafted.value,
        )
        inquiry = OutreachInquiry(
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
    else:
        now = db.utc_now_iso()
        inquiry = OutreachInquiry(
            id="out_preview",
            product_id=detail.id,
            formulation_snapshot_id=detail.current_snapshot.id,
            target_email=resolved_email,
            flagged_ingredients=unresolved_names,
            generated_subject=subject,
            generated_body=body,
            mode=normalized_mode,
            state=OutreachState.drafted,
            created_at=now,
            updated_at=now,
        )

    return OutreachDraftResponse(
        inquiry=inquiry,
        mailto_url=mailto_url,
        cooldown_warning=cooldown_warning,
        unresolved_ingredients=unresolved_names,
    )
