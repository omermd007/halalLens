"""Product catalog, 5-tier barcode scan, formulation snapshots, and community notes routes."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app import db
from app.schemas import (
    CommunityNote,
    CommunityNoteCreateRequest,
    LookupTraceItem,
    ProductCreateRequest,
    ProductDetail,
    ProductListResponse,
    ScanRequest,
    ScanResponse,
    SnapshotCreateRequest,
    SnapshotCreateResponse,
)
from app.services import barcode_lookup, status_engine
from app.services.ingredient_parser import compute_ingredient_diff, compute_ingredient_hash

router = APIRouter(prefix="/api", tags=["products"])


@router.get("/products", response_model=ProductListResponse)
def list_products(
    q: str | None = Query(default=None, description="Optional search by name, brand, UPC, or category"),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Optional ProductStatus filter",
    ),
    conn: sqlite3.Connection = Depends(db.get_db),
) -> ProductListResponse:
    """List products evaluated under the current strictness profile."""
    normalized_status = (
        None
        if not status_filter or status_filter.strip().lower() == "all"
        else status_filter.strip()
    )
    summaries = status_engine.list_product_summaries(conn, q=q, status=normalized_status)
    return ProductListResponse(products=summaries)


@router.get("/products/{product_id}", response_model=ProductDetail)
def get_product(
    product_id: str,
    conn: sqlite3.Connection = Depends(db.get_db),
) -> ProductDetail:
    """Fetch a fully evaluated ProductDetail record."""
    try:
        return status_engine.evaluate_product(conn, product_id, persist_status=True)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product '{product_id}' not found.",
        ) from exc


@router.post("/products", response_model=ProductDetail, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreateRequest,
    conn: sqlite3.Connection = Depends(db.get_db),
) -> ProductDetail:
    """Create a product with its initial normalized FormulationSnapshot."""
    if not payload.name.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Product name is required.",
        )
    if not payload.brand.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Brand is required.",
        )
    if not payload.raw_ingredients.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Ingredient statement (raw_ingredients) is required.",
        )

    if payload.upc and payload.upc.strip():
        existing = db.fetch_product_by_upc(conn, payload.upc)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"A product with UPC '{payload.upc.strip()}' already exists "
                    f"({existing['brand']} {existing['name']}, id={existing['id']})."
                ),
            )

    try:
        product_id, _snapshot_id = db.insert_product_with_snapshot(
            conn,
            upc=payload.upc,
            name=payload.name,
            brand=payload.brand,
            category=payload.category,
            raw_ingredients=payload.raw_ingredients,
            source_type=payload.source_type or "manual",
            certifier_name=payload.certifier_name,
            certifier_status=payload.certifier_status,
            kosher_symbol=payload.kosher_symbol,
            is_certified_vegan=payload.is_certified_vegan,
            brand_contact_email=payload.brand_contact_email,
            brand_contact_url=payload.brand_contact_url,
            lot_code=payload.lot_code.strip() if payload.lot_code and payload.lot_code.strip() else None,
            plant_code=payload.plant_code.strip() if payload.plant_code and payload.plant_code.strip() else None,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A product with this UPC already exists.",
        ) from exc

    return status_engine.evaluate_product(conn, product_id, persist_status=True)


@router.post("/scan", response_model=ScanResponse)
def scan_barcode(
    payload: ScanRequest,
    conn: sqlite3.Connection = Depends(db.get_db),
) -> ScanResponse:
    """Walk the tiered barcode lookup waterfall: Local SQLite -> USDA FDC -> Open Food Facts."""
    upc_raw = (payload.upc or "").strip()
    if not upc_raw:
        return ScanResponse(
            found=False,
            source="not_found",
            product=None,
            lookup_trace=[
                LookupTraceItem(
                    tier="normalize",
                    status="invalid_upc",
                    detail="No UPC barcode digits were provided.",
                )
            ],
        )

    trace: list[LookupTraceItem] = []

    # Tier 1: Local SQLite lookup (handles UPC-A / EAN-13 leading-zero variants).
    local_row = db.fetch_product_by_upc(conn, upc_raw)
    if local_row is not None:
        detail = status_engine.evaluate_product(conn, local_row["id"], persist_status=True)
        trace.append(
            LookupTraceItem(
                tier="local_db",
                status="hit",
                detail=(
                    f"Matched '{detail.brand} {detail.name}' in local SQLite database "
                    f"(UPC {detail.upc or upc_raw})."
                ),
            )
        )
        return ScanResponse(
            found=True,
            source="local_db",
            product=detail,
            lookup_trace=trace,
        )

    trace.append(
        LookupTraceItem(
            tier="local_db",
            status="miss",
            detail=f"UPC '{upc_raw}' was not found in local SQLite catalog.",
        )
    )

    # Tier 2: Optional live external barcode waterfall (USDA FDC -> Open Food Facts).
    if not payload.allow_external:
        trace.append(
            LookupTraceItem(
                tier="external_lookup",
                status="skipped",
                detail="External USDA FDC and Open Food Facts fallback disabled by caller.",
            )
        )
        return ScanResponse(
            found=False,
            source="not_found",
            product=None,
            lookup_trace=trace,
        )

    candidate, external_trace = barcode_lookup.lookup_external_barcode(upc_raw)
    for step in external_trace:
        trace.append(LookupTraceItem(tier=step.tier, status=step.status, detail=step.detail))

    if candidate is not None:
        # Guard against external canonical UPC colliding with an already-stored local record.
        if candidate.upc:
            existing = db.fetch_product_by_upc(conn, candidate.upc)
            if existing is not None:
                detail = status_engine.evaluate_product(conn, existing["id"], persist_status=True)
                return ScanResponse(
                    found=True,
                    source="local_db",
                    product=detail,
                    lookup_trace=trace,
                )

        resolved_upc = candidate.upc or db.normalize_upc(upc_raw)
        product_id, _snapshot_id = db.insert_product_with_snapshot(
            conn,
            upc=resolved_upc,
            name=candidate.name or f"Product {resolved_upc or upc_raw}",
            brand=candidate.brand or "Unknown Brand",
            category=candidate.category or "Grocery",
            raw_ingredients=candidate.raw_ingredients or "",
            source_type=candidate.source_type,
            certifier_name=candidate.certifier_name,
            certifier_status=candidate.certifier_status,
            kosher_symbol=candidate.kosher_symbol,
            is_certified_vegan=candidate.is_certified_vegan,
        )
        detail = status_engine.evaluate_product(conn, product_id, persist_status=True)
        return ScanResponse(
            found=True,
            source=candidate.source_type,
            product=detail,
            lookup_trace=trace,
        )

    return ScanResponse(
        found=False,
        source="not_found",
        product=None,
        lookup_trace=trace,
    )


@router.post("/products/{product_id}/snapshots", response_model=SnapshotCreateResponse)
def create_formulation_snapshot(
    product_id: str,
    payload: SnapshotCreateRequest,
    conn: sqlite3.Connection = Depends(db.get_db),
) -> SnapshotCreateResponse:
    """Submit a new ingredient label snapshot, detect drift, and re-evaluate product status."""
    product_row = db.fetch_product_row(conn, product_id)
    if product_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product '{product_id}' not found.",
        )

    if not payload.raw_ingredients.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Ingredient statement (raw_ingredients) cannot be empty.",
        )

    existing_snapshots = db.fetch_snapshots_for_product(conn, product_id)
    current_snap = next(
        (row for row in existing_snapshots if bool(row["is_current"])),
        existing_snapshots[0] if existing_snapshots else None,
    )

    new_hash = compute_ingredient_hash(payload.raw_ingredients)
    drift_detected = current_snap is not None and current_snap["ingredient_hash"] != new_hash

    if drift_detected and current_snap is not None:
        added_ingredients, removed_ingredients = compute_ingredient_diff(
            current_snap["raw_ingredients"],
            payload.raw_ingredients,
        )
    else:
        added_ingredients, removed_ingredients = [], []

    lot_code = payload.lot_code.strip() if payload.lot_code and payload.lot_code.strip() else None
    plant_code = (
        payload.plant_code.strip() if payload.plant_code and payload.plant_code.strip() else None
    )

    if current_snap is None or drift_detected or lot_code is not None or plant_code is not None:
        db.add_formulation_snapshot(
            conn,
            product_id,
            payload.raw_ingredients,
            source_type=payload.source_type or "manual",
            lot_code=lot_code,
            plant_code=plant_code,
        )

    detail = status_engine.evaluate_product(conn, product_id, persist_status=True)
    return SnapshotCreateResponse(
        product=detail,
        drift_detected=drift_detected,
        added_ingredients=added_ingredients,
        removed_ingredients=removed_ingredients,
    )


@router.post(
    "/products/{product_id}/notes",
    response_model=CommunityNote,
    status_code=status.HTTP_201_CREATED,
)
def add_community_note(
    product_id: str,
    payload: CommunityNoteCreateRequest,
    conn: sqlite3.Connection = Depends(db.get_db),
) -> CommunityNote:
    """Attach a secondary personal/community observation note to a product."""
    product_row = db.fetch_product_row(conn, product_id)
    if product_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product '{product_id}' not found.",
        )

    if not payload.note_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Note text cannot be empty.",
        )

    row = db.insert_community_note(
        conn,
        product_id=product_id,
        author_label=payload.author_label,
        note_text=payload.note_text,
        confidence_tier=payload.confidence_tier,
    )
    return CommunityNote(
        id=row["id"],
        product_id=row["product_id"],
        author_label=row["author_label"],
        note_text=row["note_text"],
        confidence_tier=row["confidence_tier"],
        created_at=row["created_at"],
    )
