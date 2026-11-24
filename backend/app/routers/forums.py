"""Public forum intelligence scanner and pasted-thread parser routes."""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Body, Depends, HTTPException, status

from app import db
from app.schemas import (
    Determination,
    EvidenceTier,
    ForumConsensus,
    ForumParsePostRequest,
    ForumParsePostResponse,
    ForumScanRequest,
    ForumScanResponse,
    ForumSignal,
    ForumSourceCheck,
    FreshnessBucket,
    RegionFlag,
)
from app.services import forum_scanner, status_engine

router = APIRouter(prefix="/api/forums", tags=["forums"])


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


def _build_consensus(signals: list[ForumSignal]) -> ForumConsensus:
    serialized = [sig.model_dump(mode="json") for sig in signals]
    return ForumConsensus.model_validate(forum_scanner.aggregate_forum_consensus(serialized))


@router.post("/scan/{product_id}", response_model=ForumScanResponse)
def scan_product_forums(
    product_id: str,
    payload: ForumScanRequest = Body(default_factory=ForumScanRequest),
    conn: sqlite3.Connection = Depends(db.get_db),
) -> ForumScanResponse:
    """Scan public Reddit/web forum adapters for a product, deduplicate, and persist new signals."""
    try:
        detail = status_engine.evaluate_product(conn, product_id, persist_status=False)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product '{product_id}' not found.",
        ) from exc

    flagged_names = detail.flagged_ingredient_names or [
        flag.canonical_name for flag in detail.ingredient_flags
    ]

    parsed_signals, source_statuses = forum_scanner.scan_public_forums(
        product_name=detail.name,
        brand=detail.brand,
        flagged_ingredients=flagged_names,
        include_live_reddit=payload.include_live_reddit,
        subreddits=payload.subreddits,
        custom_query=payload.custom_query,
    )

    existing_rows = db.fetch_forum_signals_for_product(conn, product_id)
    existing_url_keys: set[str] = set()
    existing_title_sources: set[tuple[str, str]] = set()
    for row in existing_rows:
        url_key = forum_scanner._normalize_url_key(row["url"])
        if url_key:
            existing_url_keys.add(url_key)
        existing_title_sources.add(
            ((row["source_name"] or "").strip().lower(), (row["title"] or "").strip().lower())
        )

    new_signals_added = 0
    for sig in parsed_signals:
        url_key = forum_scanner._normalize_url_key(sig.url)
        title_source_key = (
            (sig.source_name or "").strip().lower(),
            (sig.title or "").strip().lower(),
        )
        if (url_key and url_key in existing_url_keys) or title_source_key in existing_title_sources:
            continue

        db.insert_forum_signal(
            conn,
            product_id=product_id,
            source_platform=sig.source_platform,
            source_name=sig.source_name,
            url=sig.url,
            title=sig.title,
            author=sig.author,
            posted_at=sig.posted_at,
            raw_excerpt=sig.raw_excerpt,
            matched_ingredients=sig.matched_ingredients,
            claimed_determination=sig.claimed_determination,
            evidence_tier=sig.evidence_tier,
            freshness=sig.freshness,
            region_flag=sig.region_flag,
            region_notes=sig.region_notes,
        )
        if url_key:
            existing_url_keys.add(url_key)
        existing_title_sources.add(title_source_key)
        new_signals_added += 1

    if new_signals_added > 0:
        conn.execute(
            "UPDATE products SET updated_at = ? WHERE id = ?",
            (db.utc_now_iso(), product_id),
        )

    all_rows = db.fetch_forum_signals_for_product(conn, product_id)
    signals = [_row_to_forum_signal(row) for row in all_rows]
    consensus = _build_consensus(signals)
    sources_checked = [
        ForumSourceCheck(
            source=st.source,
            status=st.status,
            matched_count=st.matched_count,
            detail=st.detail,
        )
        for st in source_statuses
    ]

    return ForumScanResponse(
        signals=signals,
        consensus=consensus,
        sources_checked=sources_checked,
        new_signals_added=new_signals_added,
    )


@router.post("/parse-post", response_model=ForumParsePostResponse)
def parse_forum_post_endpoint(
    payload: ForumParsePostRequest,
    conn: sqlite3.Connection = Depends(db.get_db),
) -> ForumParsePostResponse:
    """Parse a pasted Reddit or forum thread into a structured ForumSignal and optionally save it."""
    if not payload.title.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="title is required.",
        )
    if not payload.raw_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="raw_text is required.",
        )
    if payload.save_to_product and not payload.product_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="product_id is required when save_to_product is true.",
        )

    tracked_ingredients: list[str] | None = None
    if payload.product_id:
        try:
            detail = status_engine.evaluate_product(conn, payload.product_id, persist_status=False)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product '{payload.product_id}' not found.",
            ) from exc
        tracked_ingredients = detail.flagged_ingredient_names or [
            flag.canonical_name for flag in detail.ingredient_flags
        ]

    parsed = forum_scanner.parse_forum_post(
        title=payload.title,
        raw_text=payload.raw_text,
        source_platform=payload.source_platform or "forum",
        source_name=payload.source_name,
        url=payload.url,
        author=payload.author,
        posted_at=payload.posted_at,
        tracked_ingredients=tracked_ingredients,
    )

    if payload.save_to_product and payload.product_id:
        signal_id = db.insert_forum_signal(
            conn,
            product_id=payload.product_id,
            source_platform=parsed.source_platform,
            source_name=parsed.source_name,
            url=parsed.url,
            title=parsed.title,
            author=parsed.author,
            posted_at=parsed.posted_at,
            raw_excerpt=parsed.raw_excerpt,
            matched_ingredients=parsed.matched_ingredients,
            claimed_determination=parsed.claimed_determination,
            evidence_tier=parsed.evidence_tier,
            freshness=parsed.freshness,
            region_flag=parsed.region_flag,
            region_notes=parsed.region_notes,
        )
        conn.execute(
            "UPDATE products SET updated_at = ? WHERE id = ?",
            (db.utc_now_iso(), payload.product_id),
        )
        saved_row = db.fetch_forum_signal_by_id(conn, signal_id)
        assert saved_row is not None
        signal = _row_to_forum_signal(saved_row)

        all_rows = db.fetch_forum_signals_for_product(conn, payload.product_id)
        all_signals = [_row_to_forum_signal(r) for r in all_rows]
        consensus = _build_consensus(all_signals)
        return ForumParsePostResponse(signal=signal, consensus=consensus)

    preview_signal = ForumSignal(
        id=db.generate_id("fs_preview"),
        product_id=payload.product_id,
        source_platform=parsed.source_platform,
        source_name=parsed.source_name,
        url=parsed.url,
        title=parsed.title,
        author=parsed.author,
        posted_at=parsed.posted_at,
        raw_excerpt=parsed.raw_excerpt,
        matched_ingredients=parsed.matched_ingredients,
        claimed_determination=Determination(parsed.claimed_determination),
        evidence_tier=EvidenceTier(parsed.evidence_tier),
        freshness=FreshnessBucket(parsed.freshness),
        region_flag=RegionFlag(parsed.region_flag),
        region_notes=parsed.region_notes,
        fetched_at=db.utc_now_iso(),
    )
    return ForumParsePostResponse(signal=preview_signal, consensus=None)
