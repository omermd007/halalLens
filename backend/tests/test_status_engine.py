"""Unit tests for the deterministic 5-state halal status engine, strictness profiles, and review queue."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import db
from app.schemas import (
    Determination,
    FlagResolutionStatus,
    ProductStatus,
    StrictnessProfile,
)
from app.services import status_engine


def _iso_day(delta_days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).date().isoformat()


def test_seeded_products_cover_all_five_status_states(seeded_conn) -> None:
    expected = {
        "prod_saffron_tikka": ProductStatus.certified_halal,
        "prod_annies_mac": ProductStatus.verified_plant_or_microbial,
        "prod_tj_marshmallows": ProductStatus.verified_plant_or_microbial,
        "prod_cabot_cheddar": ProductStatus.verified_plant_or_microbial,
        "prod_kraft_mac": ProductStatus.mushbooh_needs_check,
        "prod_oreo_original": ProductStatus.mushbooh_needs_check,
        "prod_goodles_cheddy": ProductStatus.formulation_changed,
        "prod_haribo_us": ProductStatus.animal_or_haram,
    }
    for product_id, expected_status in expected.items():
        detail = status_engine.evaluate_product(seeded_conn, product_id, persist_status=True)
        assert detail.computed_status == expected_status, (
            f"{product_id}: expected {expected_status}, got {detail.computed_status}"
        )


def test_precedence_order_haram_overrides_certifier_and_drift(seeded_conn) -> None:
    pid, sid = db.insert_product_with_snapshot(
        seeded_conn,
        upc="999000111001",
        name="Precedence Test Snack",
        brand="TestBrand",
        raw_ingredients="WHEAT FLOUR, ENZYMES, SALT.",
        certifier_name="IFANCA",
        certifier_status="active",
        is_certified_vegan=True,
    )
    # Active verification on v1
    db.insert_verification(
        seeded_conn,
        product_id=pid,
        formulation_snapshot_id=sid,
        ingredient_name="enzymes",
        determination=Determination.plant_or_microbial.value,
        response_excerpt="Microbial enzymes confirmed.",
        expires_at=_iso_day(180),
    )
    # Drift to v2 adding carmine (haram_animal)
    db.add_formulation_snapshot(
        seeded_conn,
        pid,
        "WHEAT FLOUR, ENZYMES, SALT, CARMINE.",
        source_type="ocr",
    )

    detail = status_engine.evaluate_product(seeded_conn, pid)
    # Precedence 1 (animal_or_haram) MUST override formulation_changed and certified_halal.
    assert detail.computed_status == ProductStatus.animal_or_haram
    carmine_flag = next(f for f in detail.ingredient_flags if f.canonical_name == "carmine")
    assert carmine_flag.resolution_status == FlagResolutionStatus.confirmed_haram


def test_reformulation_drift_detection_and_same_hash_lot_update(seeded_conn) -> None:
    pid, sid = db.insert_product_with_snapshot(
        seeded_conn,
        upc="999000111002",
        name="Drift Cheddar Crackers",
        brand="DriftBrand",
        raw_ingredients="WHEAT FLOUR, CHEDDAR CHEESE (MILK, ENZYMES, SALT).",
    )
    db.insert_verification(
        seeded_conn,
        product_id=pid,
        formulation_snapshot_id=sid,
        ingredient_name="enzymes",
        determination=Determination.plant_or_microbial.value,
        response_excerpt="Enzymes are 100% microbial.",
        expires_at=_iso_day(200),
    )
    assert status_engine.evaluate_product(seeded_conn, pid).computed_status == (
        ProductStatus.verified_plant_or_microbial
    )

    # Identical normalized ingredients with a new lot code preserves verification.
    db.add_formulation_snapshot(
        seeded_conn,
        pid,
        "INGREDIENTS: wheat flour, cheddar cheese (milk, enzymes, salt)",
        lot_code="LOT-SAME-HASH",
    )
    same_detail = status_engine.evaluate_product(seeded_conn, pid)
    assert same_detail.computed_status == ProductStatus.verified_plant_or_microbial
    assert same_detail.diff_from_verified is None
    assert same_detail.verifications[0].matches_current_snapshot is True

    # Adding mono- and diglycerides flips status to formulation_changed with diff.
    db.add_formulation_snapshot(
        seeded_conn,
        pid,
        "WHEAT FLOUR, CHEDDAR CHEESE (MILK, ENZYMES, SALT), MONO- AND DIGLYCERIDES.",
        lot_code="LOT-DRIFT",
    )
    drift_detail = status_engine.evaluate_product(seeded_conn, pid)
    assert drift_detail.computed_status == ProductStatus.formulation_changed
    assert drift_detail.diff_from_verified is not None
    assert "mono- and diglycerides" in drift_detail.diff_from_verified.added_ingredients
    assert drift_detail.verifications[0].matches_current_snapshot is False


def test_supplier_variability_blocks_green(seeded_conn) -> None:
    pid, sid = db.insert_product_with_snapshot(
        seeded_conn,
        upc="999000111003",
        name="Variable Crackers",
        brand="VarBrand",
        raw_ingredients="WHEAT FLOUR, MONO- AND DIGLYCERIDES, SALT.",
    )
    db.insert_verification(
        seeded_conn,
        product_id=pid,
        formulation_snapshot_id=sid,
        ingredient_name="mono- and diglycerides",
        determination=Determination.plant_or_microbial.value,
        varies_by_supplier=True,
        response_excerpt="Usually plant-based but varies by supplier.",
        expires_at=_iso_day(180),
    )

    detail = status_engine.evaluate_product(seeded_conn, pid)
    assert detail.computed_status == ProductStatus.mushbooh_needs_check
    flag = next(f for f in detail.ingredient_flags if f.canonical_name == "mono- and diglycerides")
    assert flag.resolution_status == FlagResolutionStatus.supplier_varies

    queue = status_engine.build_review_queue(seeded_conn)
    assert any(item.id == pid for item in queue.supplier_variability)


def test_expired_verification_triggers_mushbooh_and_review_queue(seeded_conn) -> None:
    pid, sid = db.insert_product_with_snapshot(
        seeded_conn,
        upc="999000111004",
        name="Old Verified Cheese",
        brand="ExpireBrand",
        raw_ingredients="MILK, ENZYMES, SALT.",
    )
    db.insert_verification(
        seeded_conn,
        product_id=pid,
        formulation_snapshot_id=sid,
        ingredient_name="enzymes",
        determination=Determination.plant_or_microbial.value,
        response_excerpt="Microbial enzymes confirmed in 2024.",
        verified_date=_iso_day(-400),
        expires_at=_iso_day(-15),
    )

    detail = status_engine.evaluate_product(seeded_conn, pid)
    assert detail.computed_status == ProductStatus.mushbooh_needs_check
    assert detail.verifications[0].is_expired is True
    flag = next(f for f in detail.ingredient_flags if f.canonical_name == "enzymes")
    assert flag.resolution_status == FlagResolutionStatus.expired_verification

    queue = status_engine.build_review_queue(seeded_conn)
    assert any(item.id == pid for item in queue.expiring_or_expired)


def test_strictness_profile_kosher_oud_vs_generic_k_and_relaxations(seeded_conn) -> None:
    # Product 1: OU-D kosher with enzymes + mono- and diglycerides + whey + natural flavors + vanilla extract
    pid_oud, _ = db.insert_product_with_snapshot(
        seeded_conn,
        upc="999000111005",
        name="OU-D Cheese Pastry",
        brand="KosherTestBrand",
        raw_ingredients=(
            "WHEAT FLOUR, ENZYMES, MONO- AND DIGLYCERIDES, WHEY, "
            "NATURAL FLAVORS, VANILLA EXTRACT."
        ),
        kosher_symbol="OU-D",
    )
    # Product 2: Generic unsupervised "K" symbol with enzymes
    pid_k, _ = db.insert_product_with_snapshot(
        seeded_conn,
        upc="999000111006",
        name="Generic K Cheese",
        brand="GenericKBrand",
        raw_ingredients="MILK, SALT, ENZYMES.",
        kosher_symbol="K",
    )

    # Under default strict profile, both are mushbooh_needs_check.
    assert status_engine.evaluate_product(seeded_conn, pid_oud).computed_status == (
        ProductStatus.mushbooh_needs_check
    )
    assert status_engine.evaluate_product(seeded_conn, pid_k).computed_status == (
        ProductStatus.mushbooh_needs_check
    )

    # Switch to balanced profile: OU-D resolves enzymes + mono/diglycerides; whey, natural flavors, vanilla become informational.
    balanced = StrictnessProfile(
        preset="balanced",
        treat_oud_enzymes_as_verified=True,
        flag_natural_flavors=False,
        flag_whey_strictly=False,
        flag_vanilla_ethanol=False,
    )
    status_engine.update_strictness_profile(seeded_conn, balanced)

    oud_detail = status_engine.evaluate_product(seeded_conn, pid_oud)
    assert oud_detail.computed_status == ProductStatus.verified_plant_or_microbial
    oud_flags = {f.canonical_name: f.resolution_status for f in oud_detail.ingredient_flags}
    assert oud_flags["enzymes"] == FlagResolutionStatus.resolved_via_kosher_profile
    assert oud_flags["mono- and diglycerides"] == FlagResolutionStatus.resolved_via_kosher_profile
    assert oud_flags["whey"] == FlagResolutionStatus.informational
    assert oud_flags["natural flavors"] == FlagResolutionStatus.informational
    assert oud_flags["vanilla extract"] == FlagResolutionStatus.informational

    # Generic "K" must STILL remain unresolved / mushbooh_needs_check!
    k_detail = status_engine.evaluate_product(seeded_conn, pid_k)
    assert k_detail.computed_status == ProductStatus.mushbooh_needs_check
    assert k_detail.ingredient_flags[0].resolution_status == FlagResolutionStatus.unresolved


def test_brand_policy_resolution_and_expiry(seeded_conn) -> None:
    pid, _ = db.insert_product_with_snapshot(
        seeded_conn,
        upc="999000111007",
        name="Artisan Cheddar",
        brand="PolicyDairy",
        raw_ingredients="PASTEURIZED MILK, CHEESE CULTURE, SALT, ENZYMES.",
    )
    assert status_engine.evaluate_product(seeded_conn, pid).computed_status == (
        ProductStatus.mushbooh_needs_check
    )

    # Expired brand policy must NOT resolve flags.
    db.insert_brand_policy(
        seeded_conn,
        brand="PolicyDairy",
        scope_description="Old expired FAQ",
        applies_to_ingredients=["enzymes", "cheese culture"],
        determination=Determination.plant_or_microbial.value,
        excerpt="Old microbial statement.",
        checked_date=_iso_day(-400),
        expires_at=_iso_day(-5),
    )
    assert status_engine.evaluate_product(seeded_conn, pid).computed_status == (
        ProductStatus.mushbooh_needs_check
    )

    # Fresh brand policy resolves both flags -> verified_plant_or_microbial.
    db.insert_brand_policy(
        seeded_conn,
        brand="PolicyDairy",
        scope_description="Current FAQ: all cheddar lines use microbial enzymes and cultures.",
        applies_to_ingredients=["enzymes", "cheese culture"],
        determination=Determination.plant_or_microbial.value,
        excerpt="All PolicyDairy cheeses use microbial enzymes and vegetarian cultures.",
        checked_date=_iso_day(-1),
        expires_at=_iso_day(364),
    )
    detail = status_engine.evaluate_product(seeded_conn, pid)
    assert detail.computed_status == ProductStatus.verified_plant_or_microbial
    assert all(
        f.resolution_status == FlagResolutionStatus.verified_brand_policy
        for f in detail.ingredient_flags
    )


def test_certified_vegan_resolves_animal_risk_but_excludes_ethanol(seeded_conn) -> None:
    pid, _ = db.insert_product_with_snapshot(
        seeded_conn,
        upc="999000111008",
        name="Vegan Vanilla Cookie",
        brand="GreenBakery",
        raw_ingredients=(
            "WHEAT FLOUR, SUGAR, MONO- AND DIGLYCERIDES, GLYCERIN, "
            "NATURAL FLAVORS, PURE VANILLA EXTRACT."
        ),
        is_certified_vegan=True,
    )
    detail = status_engine.evaluate_product(seeded_conn, pid)
    flags = {f.canonical_name: f.resolution_status for f in detail.ingredient_flags}

    # Vegan resolves animal-origin emulsifiers & flavors.
    assert flags["mono- and diglycerides"] == FlagResolutionStatus.resolved_via_vegan
    assert flags["glycerin"] == FlagResolutionStatus.resolved_via_vegan
    assert flags["natural flavors"] == FlagResolutionStatus.resolved_via_vegan
    # Vegan does NOT resolve ethanol-bearing vanilla extract under strict profile.
    assert flags["vanilla extract"] == FlagResolutionStatus.unresolved
    assert detail.computed_status == ProductStatus.mushbooh_needs_check
