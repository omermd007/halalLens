"""Label OCR analysis, ingredient reference rules, and personal strictness profile routes."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app import db
from app.schemas import (
    IngredientRule,
    IngredientRuleListResponse,
    OcrAnalyzeRequest,
    OcrAnalyzeResponse,
    ProductDetail,
    StrictnessProfile,
)
from app.services import status_engine

router = APIRouter(prefix="/api", tags=["analysis"])


@router.post("/ocr/analyze", response_model=OcrAnalyzeResponse)
def analyze_ocr_ingredients(
    payload: OcrAnalyzeRequest,
    conn: sqlite3.Connection = Depends(db.get_db),
) -> OcrAnalyzeResponse:
    """Analyze pasted or OCR-extracted ingredients, check drift, and optionally save snapshot."""
    if not payload.raw_ingredients.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="raw_ingredients cannot be empty.",
        )

    if payload.save_snapshot and not payload.product_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="product_id is required when save_snapshot is true.",
        )

    try:
        analysis = status_engine.evaluate_raw_ingredients(
            conn,
            payload.raw_ingredients,
            product_id=payload.product_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product '{payload.product_id}' not found.",
        ) from exc

    updated_product: ProductDetail | None = None
    if payload.save_snapshot and payload.product_id:
        lot_code = payload.lot_code.strip() if payload.lot_code and payload.lot_code.strip() else None
        plant_code = (
            payload.plant_code.strip() if payload.plant_code and payload.plant_code.strip() else None
        )
        if analysis["drift_detected"] or lot_code is not None or plant_code is not None:
            db.add_formulation_snapshot(
                conn,
                payload.product_id,
                payload.raw_ingredients,
                source_type="ocr",
                lot_code=lot_code,
                plant_code=plant_code,
            )
        updated_product = status_engine.evaluate_product(
            conn,
            payload.product_id,
            persist_status=True,
        )

    return OcrAnalyzeResponse(
        normalized_ingredients=analysis["normalized_ingredients"],
        ingredient_hash=analysis["ingredient_hash"],
        parsed_tokens=analysis["parsed_tokens"],
        flagged_ingredients=analysis["flagged_ingredients"],
        projected_status=analysis["projected_status"],
        status_reasons=analysis["status_reasons"],
        drift_detected=analysis["drift_detected"],
        added_ingredients=analysis["added_ingredients"],
        removed_ingredients=analysis["removed_ingredients"],
        updated_product=updated_product,
    )


@router.get("/ingredients", response_model=IngredientRuleListResponse)
def list_ingredient_rules(
    q: str | None = Query(default=None, description="Optional filter on name, aliases, or notes"),
    conn: sqlite3.Connection = Depends(db.get_db),
) -> IngredientRuleListResponse:
    """List seeded U.S. grocery ingredient rules."""
    rule_dicts = db.fetch_all_ingredient_rules(conn, q=q)
    rules = [IngredientRule.model_validate(item) for item in rule_dicts]
    return IngredientRuleListResponse(rules=rules)


@router.get("/settings/profile", response_model=StrictnessProfile)
def get_strictness_profile(
    conn: sqlite3.Connection = Depends(db.get_db),
) -> StrictnessProfile:
    """Return the active personal strictness profile."""
    return status_engine.get_strictness_profile(conn)


@router.put("/settings/profile", response_model=StrictnessProfile)
def update_strictness_profile(
    payload: StrictnessProfile,
    conn: sqlite3.Connection = Depends(db.get_db),
) -> StrictnessProfile:
    """Persist updated strictness profile toggles and recalculate all product verdicts."""
    return status_engine.update_strictness_profile(conn, payload)
