"""Company verification logging, human-in-the-loop outreach, review queue, and brand policy routes."""

from __future__ import annotations

import calendar
import json
import sqlite3
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field

from app import db
from app.schemas import (
    BrandContactLookupResponse,
    BrandPolicy,
    BrandPolicyCreateRequest,
    BrandPolicyListResponse,
    Determination,
    OutreachDraftRequest,
    OutreachDraftResponse,
    OutreachInquiry,
    OutreachState,
    OutreachUpdateRequest,
    ProductDetail,
    ReviewQueueResponse,
    VerificationCreateRequest,
)
from app.services import brand_contacts, outreach, status_engine

router = APIRouter(prefix="/api", tags=["verification"])


class VerificationCreatePayload(VerificationCreateRequest):
    """Accept both explicit expires_at ISO date and expires_months convenience offset."""

    expires_months: int | None = Field(default=None, ge=0, le=120)


class BrandPolicyCreatePayload(BrandPolicyCreateRequest):
    """Accept both explicit expires_at ISO date and expires_months convenience offset."""

    expires_months: int | None = Field(default=None, ge=0, le=120)


def _add_months_to_iso_date(base_iso: str, months: int) -> str:
    """Add calendar months to a YYYY-MM-DD date string with month-end clamping."""
    try:
        base = date.fromisoformat(base_iso[:10])
    except ValueError:
        base = datetime.now(timezone.utc).date()

    total_months = (base.year * 12 + (base.month - 1)) + months
    target_year = total_months // 12
    target_month = (total_months % 12) + 1
    max_day = calendar.monthrange(target_year, target_month)[1]
    return date(target_year, target_month, min(base.day, max_day)).isoformat()


def _resolve_expiry_date(
    base_date: str,
    expires_at: str | None,
    expires_months: int | None,
    default_months: int = 12,
) -> str | None:
    if expires_at is not None and expires_at.strip():
        return expires_at.strip()
    if expires_months is not None:
        if expires_months <= 0:
            return None
        return _add_months_to_iso_date(base_date, expires_months)
    return _add_months_to_iso_date(base_date, default_months)


@router.post("/verifications", response_model=ProductDetail, status_code=status.HTTP_201_CREATED)
def create_verification(
    payload: VerificationCreatePayload,
    conn: sqlite3.Connection = Depends(db.get_db),
) -> ProductDetail:
    """Log a primary company verification tied to a product's formulation snapshot."""
    product_row = db.fetch_product_row(conn, payload.product_id)
    if product_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product '{payload.product_id}' not found.",
        )

    if not payload.ingredient_name.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="ingredient_name is required.",
        )
    if not payload.response_excerpt.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="response_excerpt is required.",
        )

    snapshots = db.fetch_snapshots_for_product(conn, payload.product_id)
    if not snapshots:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Product '{payload.product_id}' has no formulation snapshots.",
        )

    if payload.formulation_snapshot_id:
        snap_match = next(
            (s for s in snapshots if s["id"] == payload.formulation_snapshot_id),
            None,
        )
        if snap_match is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Formulation snapshot '{payload.formulation_snapshot_id}' "
                    f"not found for product '{payload.product_id}'."
                ),
            )
        snapshot_id = snap_match["id"]
    else:
        current_snap = next((s for s in snapshots if bool(s["is_current"])), snapshots[0])
        snapshot_id = current_snap["id"]

    verified_date = (payload.verified_date or "").strip() or db.today_iso()
    expires_at = _resolve_expiry_date(
        base_date=verified_date,
        expires_at=payload.expires_at,
        expires_months=payload.expires_months,
        default_months=12,
    )
    varies_by_supplier = payload.varies_by_supplier or (
        payload.determination == Determination.varies_by_supplier
    )

    db.insert_verification(
        conn,
        product_id=payload.product_id,
        formulation_snapshot_id=snapshot_id,
        ingredient_name=payload.ingredient_name,
        determination=payload.determination.value,
        varies_by_supplier=varies_by_supplier,
        contact_channel=payload.contact_channel or "email",
        company_contact=payload.company_contact,
        response_excerpt=payload.response_excerpt,
        lot_code=payload.lot_code.strip() if payload.lot_code and payload.lot_code.strip() else None,
        plant_code=(
            payload.plant_code.strip() if payload.plant_code and payload.plant_code.strip() else None
        ),
        verified_date=verified_date,
        expires_at=expires_at,
    )

    if payload.outreach_inquiry_id:
        db.update_outreach_state(
            conn,
            payload.outreach_inquiry_id,
            OutreachState.reply_logged.value,
        )

    return status_engine.evaluate_product(conn, payload.product_id, persist_status=True)


@router.post("/outreach/draft", response_model=OutreachDraftResponse)
def draft_outreach(
    payload: OutreachDraftRequest,
    conn: sqlite3.Connection = Depends(db.get_db),
) -> OutreachDraftResponse:
    """Generate a tailored human-in-the-loop outreach email draft with cooldown checks."""
    try:
        return outreach.generate_outreach_draft(
            conn,
            product_id=payload.product_id,
            target_email=payload.target_email,
            mode=payload.mode,
            reference_forum_signal_id=payload.reference_forum_signal_id,
            save_draft=payload.save_draft,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product '{payload.product_id}' not found.",
        ) from exc


@router.patch("/outreach/{inquiry_id}", response_model=OutreachInquiry)
def update_outreach(
    inquiry_id: str,
    payload: OutreachUpdateRequest,
    conn: sqlite3.Connection = Depends(db.get_db),
) -> OutreachInquiry:
    """Update the workflow state of an outreach inquiry."""
    row = db.update_outreach_state(conn, inquiry_id, payload.state.value)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Outreach inquiry '{inquiry_id}' not found.",
        )
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


@router.get("/review-queue", response_model=ReviewQueueResponse)
def get_review_queue(
    conn: sqlite3.Connection = Depends(db.get_db),
) -> ReviewQueueResponse:
    """Return all products and pending outreach inquiries requiring attention."""
    return status_engine.build_review_queue(conn)


@router.get("/brand-policies", response_model=BrandPolicyListResponse)
def list_brand_policies(
    conn: sqlite3.Connection = Depends(db.get_db),
) -> BrandPolicyListResponse:
    """List all cited brand-wide ingredient sourcing policies with live expiry status."""
    today = datetime.now(timezone.utc).date()
    policy_dicts = db.fetch_brand_policies(conn)
    policies = [status_engine._dict_to_brand_policy(item, today) for item in policy_dicts]
    return BrandPolicyListResponse(policies=policies)


@router.post("/brand-policies", response_model=BrandPolicy, status_code=status.HTTP_201_CREATED)
def create_brand_policy(
    payload: BrandPolicyCreatePayload,
    conn: sqlite3.Connection = Depends(db.get_db),
) -> BrandPolicy:
    """Create a brand-wide policy and recompute statuses across all products."""
    if not payload.brand.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="brand is required.",
        )
    if not payload.scope_description.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="scope_description is required.",
        )
    if not payload.excerpt.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="excerpt is required.",
        )

    cleaned_ingredients = [
        item.strip() for item in payload.applies_to_ingredients if item and item.strip()
    ]
    if not cleaned_ingredients:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="applies_to_ingredients must include at least one ingredient.",
        )

    checked_date = (payload.checked_date or "").strip() or db.today_iso()
    expires_at = _resolve_expiry_date(
        base_date=checked_date,
        expires_at=payload.expires_at,
        expires_months=payload.expires_months,
        default_months=12,
    )

    inserted = db.insert_brand_policy(
        conn,
        brand=payload.brand,
        scope_description=payload.scope_description,
        applies_to_ingredients=cleaned_ingredients,
        determination=payload.determination.value,
        source_url=payload.source_url,
        excerpt=payload.excerpt,
        checked_date=checked_date,
        expires_at=expires_at,
    )
    status_engine.recompute_all_products(conn)

    today = datetime.now(timezone.utc).date()
    return status_engine._dict_to_brand_policy(inserted, today)


@router.get("/brands/lookup-contact", response_model=BrandContactLookupResponse)
def lookup_brand_contact_route(
    brand: str = Query(..., min_length=1, max_length=120, description="Brand or sub-brand name to look up"),
    allow_web: bool = Query(default=True, description="Whether to perform a safe server-side web lookup if not in the verified directory"),
) -> BrandContactLookupResponse:
    """Resolve official U.S. consumer-care contact info from the verified directory or safe web lookup."""
    cleaned = brand.strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="brand query parameter is required.",
        )
    return brand_contacts.lookup_brand_contact(cleaned, allow_web=allow_web)

