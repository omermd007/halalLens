"""Unit tests for tailored company outreach draft generation, cooldowns, and mailto encoding."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import db
from app.schemas import Determination
from app.services.outreach import build_mailto_url, generate_outreach_draft


def _future_day(days: int = 180) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()


def test_tailored_draft_targets_only_unresolved_ingredients(seeded_conn) -> None:
    # Verify enzymes on Kraft Mac & Cheese; cheese culture & whey remain unresolved.
    db.insert_verification(
        seeded_conn,
        product_id="prod_kraft_mac",
        formulation_snapshot_id="snap_kraft_mac_v1",
        ingredient_name="enzymes",
        determination=Determination.plant_or_microbial.value,
        response_excerpt="Enzymes are microbial.",
        expires_at=_future_day(),
    )

    draft = generate_outreach_draft(
        seeded_conn,
        product_id="prod_kraft_mac",
        mode="full_inquiry",
        save_draft=False,
    )

    assert draft.inquiry.id == "out_preview"
    assert sorted(draft.unresolved_ingredients) == ["cheese culture", "whey"]
    assert "enzymes" not in draft.unresolved_ingredients
    assert "- cheese culture" in draft.inquiry.generated_body
    assert "- whey" in draft.inquiry.generated_body
    assert "- enzymes" not in draft.inquiry.generated_body
    assert "021000658831" in draft.inquiry.generated_subject
    assert "vary by manufacturing plant, lot, or U.S. supplier" in draft.inquiry.generated_body
    # save_draft=False must NOT persist to DB.
    assert len(db.fetch_outreach_for_product(seeded_conn, "prod_kraft_mac")) == 0


def test_quick_confirmation_cites_referenced_forum_signal(seeded_conn) -> None:
    draft = generate_outreach_draft(
        seeded_conn,
        product_id="prod_kraft_mac",
        mode="quick_confirmation",
        reference_forum_signal_id="fs_kraft_1",
        save_draft=True,
    )

    assert draft.inquiry.mode == "quick_confirmation"
    assert draft.inquiry.generated_subject.startswith("Quick Confirmation:")
    assert "r/halal" in draft.inquiry.generated_body
    assert "enzymes, whey" in draft.inquiry.generated_body
    assert "microbial" in draft.inquiry.generated_body
    assert "still accurate for current U.S. production" in draft.inquiry.generated_body
    assert draft.cooldown_warning is None  # first outreach for Kraft


def test_product_and_brand_cooldown_warnings(seeded_conn) -> None:
    # 1. Draft first outreach for Kraft Mac & Cheese -> no cooldown warning yet.
    first = generate_outreach_draft(
        seeded_conn,
        product_id="prod_kraft_mac",
        save_draft=True,
    )
    assert first.cooldown_warning is None

    # 2. Draft a second outreach for the SAME product -> product cooldown warning active.
    second = generate_outreach_draft(
        seeded_conn,
        product_id="prod_kraft_mac",
        save_draft=False,
    )
    assert second.cooldown_warning is not None
    assert second.cooldown_warning.active is True
    assert second.cooldown_warning.days_ago == 0
    assert "product cooldown" in second.cooldown_warning.message.lower()

    # 3. Create a second Kraft product and draft outreach -> brand-wide cooldown warning active.
    other_pid, _ = db.insert_product_with_snapshot(
        seeded_conn,
        upc="021000999999",
        name="Three Cheese Shells",
        brand="Kraft",
        raw_ingredients="PASTA, CHEDDAR CHEESE (MILK, ENZYMES, SALT).",
        brand_contact_email="consumer.relations@kraftheinz.example.com",
    )
    brand_draft = generate_outreach_draft(
        seeded_conn,
        product_id=other_pid,
        save_draft=False,
    )
    assert brand_draft.cooldown_warning is not None
    assert brand_draft.cooldown_warning.active is True
    assert "brand cooldown" in brand_draft.cooldown_warning.message.lower()
    assert "Original Macaroni & Cheese Dinner" in brand_draft.cooldown_warning.message


def test_reformulation_outreach_mentions_diff_and_lot_code(seeded_conn) -> None:
    # Goodles Cheddy Mac has a seeded reformulation diff and lot code GL-2611C.
    draft = generate_outreach_draft(
        seeded_conn,
        product_id="prod_goodles_cheddy",
        save_draft=False,
    )
    assert "GL-2611C" in draft.inquiry.generated_body
    assert "mono- and diglycerides" in draft.inquiry.generated_body
    assert "updated ingredient list" in draft.inquiry.generated_body
    # Goodles also has a seeded recent drafted inquiry so cooldown warning is active.
    assert draft.cooldown_warning is not None
    assert draft.cooldown_warning.active is True


def test_mailto_rfc2368_encoding() -> None:
    url = build_mailto_url(
        "consumer.relations@kraftheinz.example.com",
        "Ingredient Inquiry: Mac & Cheese (UPC 021000658831)",
        "Hello team,\nPlease confirm enzymes & whey.",
    )
    assert url.startswith("mailto:consumer.relations@kraftheinz.example.com?subject=")
    assert "+" not in url  # RFC 2368 uses %20, not +
    assert "%20" in url
    assert "%26" in url
    assert "%0A" in url
