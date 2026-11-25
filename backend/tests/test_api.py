"""End-to-end FastAPI integration tests covering all 19 HalalLens REST endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import barcode_lookup, forum_scanner
from app.services.barcode_lookup import ExternalLookupCandidate, LookupTraceStep
from app.services.forum_scanner import ParsedForumSignal, SourceCheckStatus


def test_health_and_api_404_returns_json(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["db"] == "ready"
    assert data["products_count"] == 8

    missing = client.get("/api/nonexistent-endpoint")
    assert missing.status_code == 404
    assert "application/json" in missing.headers.get("content-type", "")


def test_list_and_get_products_with_filters(client: TestClient) -> None:
    all_res = client.get("/api/products")
    assert all_res.status_code == 200
    products = all_res.json()["products"]
    assert len(products) == 8

    filtered = client.get("/api/products", params={"q": "Kraft", "status": "mushbooh_needs_check"})
    assert filtered.status_code == 200
    items = filtered.json()["products"]
    assert len(items) == 1
    assert items[0]["id"] == "prod_kraft_mac"

    detail = client.get("/api/products/prod_kraft_mac")
    assert detail.status_code == 200
    body = detail.json()
    assert body["upc"] == "021000658831"
    assert body["computed_status"] == "mushbooh_needs_check"
    assert body["forum_consensus"]["total_signals"] == 3
    assert body["forum_consensus"]["has_conflict"] is True

    not_found = client.get("/api/products/prod_does_not_exist")
    assert not_found.status_code == 404


def test_scan_local_hit_and_ean13_variant(client: TestClient) -> None:
    res = client.post("/api/scan", json={"upc": "021000658831", "allow_external": False})
    assert res.status_code == 200
    body = res.json()
    assert body["found"] is True
    assert body["source"] == "local_db"
    assert body["product"]["id"] == "prod_kraft_mac"
    assert body["lookup_trace"][0]["tier"] == "local_db"
    assert body["lookup_trace"][0]["status"] == "hit"

    # 13-digit EAN-13 leading-zero variant of same U.S. UPC-A still hits Tier 1 local DB.
    ean_res = client.post("/api/scan", json={"upc": "0021000658831", "allow_external": False})
    assert ean_res.status_code == 200
    assert ean_res.json()["found"] is True
    assert ean_res.json()["product"]["id"] == "prod_kraft_mac"


def test_scan_mocked_external_usda_auto_import_and_subsequent_local_hit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_lookup(upc: str, **_kwargs):
        return (
            ExternalLookupCandidate(
                upc="038000138416",
                name="Frosted Mini-Wheats Original",
                brand="Kellogg's",
                category="Breakfast Cereal",
                raw_ingredients="WHOLE GRAIN WHEAT, SUGAR, CONTAINS 2% OR LESS OF BROWN RICE SYRUP, GELATIN, BHT.",
                source_type="usda_fdc",
                kosher_symbol=None,
                is_certified_vegan=False,
            ),
            [
                LookupTraceStep(
                    tier="usda_fdc",
                    status="hit",
                    detail="Matched USDA FDC branded food 'Frosted Mini-Wheats Original'.",
                )
            ],
        )

    monkeypatch.setattr(barcode_lookup, "lookup_external_barcode", fake_lookup)

    res = client.post("/api/scan", json={"upc": "038000138416", "allow_external": True})
    assert res.status_code == 200
    body = res.json()
    assert body["found"] is True
    assert body["source"] == "usda_fdc"
    assert body["product"]["brand"] == "Kellogg's"
    assert body["product"]["computed_status"] == "mushbooh_needs_check"
    assert "gelatin" in body["product"]["flagged_ingredient_names"]
    assert [t["tier"] for t in body["lookup_trace"]] == ["local_db", "usda_fdc"]

    # Second scan hits local SQLite immediately without calling external lookup.
    second = client.post("/api/scan", json={"upc": "038000138416", "allow_external": False})
    assert second.status_code == 200
    assert second.json()["found"] is True
    assert second.json()["source"] == "local_db"


def test_scan_missing_upc_then_create_product_and_duplicate_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_miss(_upc: str, **_kwargs):
        return (
            None,
            [
                LookupTraceStep(tier="usda_fdc", status="miss", detail="Not in USDA FDC."),
                LookupTraceStep(tier="open_food_facts", status="miss", detail="Not in OFF."),
            ],
        )

    monkeypatch.setattr(barcode_lookup, "lookup_external_barcode", fake_miss)

    scan_res = client.post("/api/scan", json={"upc": "777000123456", "allow_external": True})
    assert scan_res.status_code == 200
    scan_body = scan_res.json()
    assert scan_body["found"] is False
    assert scan_body["source"] == "not_found"
    assert scan_body["product"] is None
    assert len(scan_body["lookup_trace"]) == 3

    create_payload = {
        "upc": "777000123456",
        "name": "White Cheddar Popcorn",
        "brand": "SmartTest",
        "category": "Snacks",
        "raw_ingredients": "POPCORN, VEGETABLE OIL, CHEDDAR CHEESE (MILK, CHEESE CULTURES, SALT, ENZYMES), WHEY.",
        "kosher_symbol": "OU-D",
        "is_certified_vegan": False,
        "brand_contact_email": "help@smarttest.test",
    }
    created = client.post("/api/products", json=create_payload)
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["upc"] == "777000123456"
    assert created_body["computed_status"] == "mushbooh_needs_check"
    assert sorted(created_body["flagged_ingredient_names"]) == ["cheese culture", "enzymes", "whey"]

    # Duplicate UPC must return 409 Conflict.
    dup = client.post("/api/products", json=create_payload)
    assert dup.status_code == 409


def test_snapshot_submission_triggers_formulation_changed(client: TestClient) -> None:
    # Annie's starts as verified_plant_or_microbial with an active verification on snap_annies_mac_v1.
    before = client.get("/api/products/prod_annies_mac").json()
    assert before["computed_status"] == "verified_plant_or_microbial"

    snap_res = client.post(
        "/api/products/prod_annies_mac/snapshots",
        json={
            "raw_ingredients": (
                "ORGANIC PASTA (ORGANIC WHEAT FLOUR), CHEDDAR CHEESE (PASTEURIZED MILK, "
                "CHEESE CULTURE, SALT, ENZYMES), WHEY, BUTTER (PASTEURIZED CREAM, SALT), "
                "NONFAT MILK, SALT, SODIUM PHOSPHATE, MONO- AND DIGLYCERIDES, NATURAL FLAVORS."
            ),
            "source_type": "label_ocr",
            "lot_code": "ANN-2026-DRIFT",
            "plant_code": "US-12",
        },
    )
    assert snap_res.status_code == 200
    body = snap_res.json()
    assert body["drift_detected"] is True
    assert "mono- and diglycerides" in body["added_ingredients"]
    assert "natural flavors" in body["added_ingredients"]
    assert body["product"]["computed_status"] == "formulation_changed"
    assert body["product"]["diff_from_verified"] is not None
    assert body["product"]["current_snapshot"]["lot_code"] == "ANN-2026-DRIFT"


def test_verifications_transition_kraft_to_green_and_supplier_variability_keeps_amber(
    client: TestClient,
) -> None:
    # 1. Draft an outreach inquiry on Kraft so we can link it when logging a reply.
    draft_res = client.post(
        "/api/outreach/draft",
        json={"product_id": "prod_kraft_mac", "mode": "full_inquiry", "save_draft": True},
    )
    assert draft_res.status_code == 200
    inquiry_id = draft_res.json()["inquiry"]["id"]

    patch_res = client.patch(f"/api/outreach/{inquiry_id}", json={"state": "sent_by_user"})
    assert patch_res.status_code == 200
    assert patch_res.json()["state"] == "sent_by_user"

    # 2. Log verification for enzymes using expires_months (testing expires_months support).
    v1 = client.post(
        "/api/verifications",
        json={
            "product_id": "prod_kraft_mac",
            "ingredient_name": "enzymes",
            "determination": "plant_or_microbial",
            "varies_by_supplier": False,
            "contact_channel": "web_form",
            "company_contact": "Kraft Heinz Consumer Care",
            "response_excerpt": "Enzymes are 100% microbial across all U.S. plants.",
            "expires_months": 12,
            "outreach_inquiry_id": inquiry_id,
        },
    )
    assert v1.status_code == 201
    v1_body = v1.json()
    # Still mushbooh because cheese culture and whey are unresolved.
    assert v1_body["computed_status"] == "mushbooh_needs_check"
    assert v1_body["unresolved_count"] == 2
    assert v1_body["verifications"][0]["expires_at"] is not None
    # Linked outreach inquiry automatically transitioned to reply_logged!
    linked = next(o for o in v1_body["outreach_inquiries"] if o["id"] == inquiry_id)
    assert linked["state"] == "reply_logged"

    # 3. Log cheese culture and whey with explicit expires_at -> Kraft turns verified_plant_or_microbial!
    for ing in ("cheese culture", "whey"):
        res = client.post(
            "/api/verifications",
            json={
                "product_id": "prod_kraft_mac",
                "ingredient_name": ing,
                "determination": "plant_or_microbial",
                "varies_by_supplier": False,
                "contact_channel": "email",
                "response_excerpt": f"{ing} is verified microbial/vegetarian across U.S. facilities.",
                "expires_at": "2028-01-01",
            },
        )
        assert res.status_code == 201

    final_kraft = client.get("/api/products/prod_kraft_mac").json()
    assert final_kraft["computed_status"] == "verified_plant_or_microbial"
    assert final_kraft["unresolved_count"] == 0

    # 4. Logging varies_by_supplier on a new product keeps mushbooh_needs_check (blocks green).
    created = client.post(
        "/api/products",
        json={
            "upc": "888000111222",
            "name": "Cheddar Pretzel Bites",
            "brand": "SnackCo",
            "category": "Snacks",
            "raw_ingredients": "ENRICHED FLOUR, SALT, MONO- AND DIGLYCERIDES.",
        },
    ).json()
    var_res = client.post(
        "/api/verifications",
        json={
            "product_id": created["id"],
            "ingredient_name": "mono- and diglycerides",
            "determination": "varies_by_supplier",
            "varies_by_supplier": True,
            "contact_channel": "phone",
            "response_excerpt": "Sourcing varies by regional plant supplier.",
            "expires_months": 6,
        },
    )
    assert var_res.status_code == 201
    assert var_res.json()["computed_status"] == "mushbooh_needs_check"


def test_community_notes_and_outreach_404(client: TestClient) -> None:
    note_res = client.post(
        "/api/products/prod_kraft_mac/notes",
        json={
            "author_label": "Shopper Check",
            "note_text": "Verified OU-D printed on 12-pack box at Target.",
            "confidence_tier": "secondary_observation",
        },
    )
    assert note_res.status_code == 201
    note = note_res.json()
    assert note["product_id"] == "prod_kraft_mac"
    assert note["author_label"] == "Shopper Check"

    detail = client.get("/api/products/prod_kraft_mac").json()
    assert any(n["id"] == note["id"] for n in detail["community_notes"])

    missing_outreach = client.patch("/api/outreach/out_missing", json={"state": "closed"})
    assert missing_outreach.status_code == 404


def test_ocr_analyze_preview_and_save_snapshot(client: TestClient) -> None:
    # Preview mode without saving
    preview = client.post(
        "/api/ocr/analyze",
        json={
            "raw_ingredients": "WATER, SUGAR, GELATIN (PORCINE), CITRIC ACID.",
            "save_snapshot": False,
        },
    )
    assert preview.status_code == 200
    p_body = preview.json()
    assert p_body["projected_status"] == "animal_or_haram"
    assert p_body["updated_product"] is None
    assert any(f["canonical_name"] == "pork gelatin" for f in p_body["flagged_ingredients"])

    # Save mode attached to Cabot Cheddar introducing drift
    saved = client.post(
        "/api/ocr/analyze",
        json={
            "raw_ingredients": "PASTEURIZED MILK, CHEESE CULTURES, SALT, ENZYMES, NATURAL FLAVORS.",
            "product_id": "prod_cabot_cheddar",
            "save_snapshot": True,
            "lot_code": "CAB-OCR-99",
            "plant_code": "VT-02",
        },
    )
    assert saved.status_code == 200
    s_body = saved.json()
    assert s_body["drift_detected"] is True
    assert "natural flavors" in s_body["added_ingredients"]
    assert s_body["updated_product"] is not None
    assert s_body["updated_product"]["current_snapshot"]["lot_code"] == "CAB-OCR-99"
    assert s_body["updated_product"]["computed_status"] == "mushbooh_needs_check"


def test_forum_parse_post_and_mocked_forum_scan_deduplication(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. Preview parse-post without saving
    preview = client.post(
        "/api/forums/parse-post",
        json={
            "source_platform": "reddit",
            "source_name": "r/halal",
            "title": "Called company about U.S. cheddar enzymes",
            "author": "u/test_user",
            "posted_at": "2026-10-01",
            "raw_text": "I emailed customer service; they do NOT use animal rennet, only microbial enzymes.",
            "save_to_product": False,
        },
    )
    assert preview.status_code == 200
    p_body = preview.json()
    assert p_body["signal"]["claimed_determination"] == "plant_or_microbial"
    assert p_body["signal"]["evidence_tier"] == "quoted_company_reply"
    assert p_body["consensus"] is None

    # 2. Save parse-post to Kraft Mac & Cheese
    saved = client.post(
        "/api/forums/parse-post",
        json={
            "product_id": "prod_kraft_mac",
            "source_platform": "reddit",
            "source_name": "r/halal",
            "url": "https://www.reddit.com/r/halal/comments/custom_parse_1/",
            "title": "Confirmed U.S. Kraft enzymes are microbial",
            "author": "u/test_user",
            "posted_at": "2026-10-15",
            "raw_text": "Consumer relations confirmed US Kraft Mac & Cheese enzymes are microbial.",
            "save_to_product": True,
        },
    )
    assert saved.status_code == 200
    s_body = saved.json()
    assert s_body["signal"]["product_id"] == "prod_kraft_mac"
    assert s_body["consensus"]["total_signals"] == 4

    # 3. Mock forum scan returning 2 new signals; second call deduplicates cleanly to 0 new.
    def fake_scan_public_forums(**_kwargs):
        return (
            [
                ParsedForumSignal(
                    source_platform="reddit",
                    source_name="r/Costco",
                    url="https://www.reddit.com/r/Costco/comments/new_kraft_1/",
                    title="Costco US Kraft Mac & Cheese enzyme check",
                    author="u/costco_shopper",
                    posted_at="2026-10-20",
                    raw_excerpt="Company confirmed US version uses microbial enzymes.",
                    matched_ingredients=["enzymes"],
                    claimed_determination="plant_or_microbial",
                    evidence_tier="quoted_company_reply",
                    freshness="recent",
                    region_flag="us",
                    region_notes="References U.S. distribution",
                ),
                ParsedForumSignal(
                    source_platform="web_forum",
                    source_name="halalguide.example.org",
                    url="https://halalguide.example.org/kraft-mac",
                    title="Kraft Mac & Cheese whey discussion",
                    author=None,
                    posted_at="2026-09-10",
                    raw_excerpt="Whey source may vary by supplier.",
                    matched_ingredients=["whey"],
                    claimed_determination="varies_by_supplier",
                    evidence_tier="community_anecdote",
                    freshness="recent",
                    region_flag="us",
                    region_notes="References U.S. distribution",
                ),
            ],
            [
                SourceCheckStatus(
                    source="r/Costco",
                    status="ok",
                    matched_count=1,
                    detail="Found 1 thread.",
                ),
                SourceCheckStatus(
                    source="web_search_brave",
                    status="ok",
                    matched_count=1,
                    detail="Matched 1 page.",
                ),
            ],
        )

    monkeypatch.setattr(forum_scanner, "scan_public_forums", fake_scan_public_forums)

    scan1 = client.post(
        "/api/forums/scan/prod_kraft_mac",
        json={"include_live_reddit": True, "subreddits": ["Costco"]},
    )
    assert scan1.status_code == 200
    body1 = scan1.json()
    assert body1["new_signals_added"] == 2
    assert body1["consensus"]["total_signals"] == 6
    assert len(body1["sources_checked"]) == 2

    # Second identical scan must add 0 duplicates.
    scan2 = client.post(
        "/api/forums/scan/prod_kraft_mac",
        json={"include_live_reddit": True, "subreddits": ["Costco"]},
    )
    assert scan2.status_code == 200
    assert scan2.json()["new_signals_added"] == 0
    assert scan2.json()["consensus"]["total_signals"] == 6


def test_ingredients_strictness_profile_review_queue_and_brand_policy(client: TestClient) -> None:
    # 1. Ingredient rules listing & search filter
    all_rules = client.get("/api/ingredients").json()["rules"]
    assert len(all_rules) == 16
    enzyme_rules = client.get("/api/ingredients", params={"q": "rennet"}).json()["rules"]
    assert any(r["canonical_name"] == "enzymes" for r in enzyme_rules)

    # 2. Review queue checks seeded buckets
    queue = client.get("/api/review-queue").json()
    assert queue["counts"]["formulation_changed"] == 1
    assert queue["formulation_changed"][0]["id"] == "prod_goodles_cheddy"
    assert any(p["id"] == "prod_oreo_original" for p in queue["supplier_variability"])
    assert any(p["id"] == "prod_kraft_mac" for p in queue["mushbooh_unresolved"])
    assert queue["counts"]["pending_outreach"] >= 1
    assert queue["counts"]["total_attention"] >= 4

    # 3. Strictness profile GET & PUT recalculates Kraft flags live
    prof = client.get("/api/settings/profile").json()
    assert prof["preset"] == "strict"
    assert prof["treat_oud_enzymes_as_verified"] is False

    updated_prof = client.put(
        "/api/settings/profile",
        json={
            "preset": "balanced",
            "treat_oud_enzymes_as_verified": True,
            "flag_natural_flavors": False,
            "flag_whey_strictly": False,
            "flag_vanilla_ethanol": False,
        },
    )
    assert updated_prof.status_code == 200
    assert updated_prof.json()["treat_oud_enzymes_as_verified"] is True

    kraft_after_profile = client.get("/api/products/prod_kraft_mac").json()
    flag_map = {f["canonical_name"]: f["resolution_status"] for f in kraft_after_profile["ingredient_flags"]}
    assert flag_map["enzymes"] == "resolved_via_kosher_profile"
    assert flag_map["whey"] == "informational"
    assert flag_map["cheese culture"] == "unresolved"
    assert kraft_after_profile["unresolved_count"] == 1

    # 4. Brand policies GET & POST recomputes all products immediately
    existing_policies = client.get("/api/brand-policies").json()["policies"]
    assert len(existing_policies) == 2

    new_pol = client.post(
        "/api/brand-policies",
        json={
            "brand": "Kraft",
            "scope_description": "All U.S. Kraft Mac & Cheese dairy cultures, enzymes, and whey are vegetarian.",
            "applies_to_ingredients": ["enzymes", "cheese culture", "whey"],
            "determination": "plant_or_microbial",
            "source_url": "https://www.kraftheinz.com/faq",
            "excerpt": "Kraft Heinz U.S. confirms vegetarian microbial enzymes and cultures.",
            "expires_months": 12,
        },
    )
    assert new_pol.status_code == 201
    pol_body = new_pol.json()
    assert pol_body["brand"] == "Kraft"
    assert pol_body["is_expired"] is False

    # Kraft should now be verified_plant_or_microbial via BrandPolicy + profile!
    kraft_resolved = client.get("/api/products/prod_kraft_mac").json()
    assert kraft_resolved["computed_status"] == "verified_plant_or_microbial"
    assert kraft_resolved["unresolved_count"] == 0


def test_scan_mocked_open_food_facts_vegan_auto_import(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_off_lookup(upc: str, **_kwargs):
        return (
            ExternalLookupCandidate(
                upc="085239012345",
                name="Organic Oat Milk Chocolate",
                brand="PlantChoc",
                category="Confections",
                raw_ingredients="ORGANIC CANE SUGAR, COCOA BUTTER, OAT FLOUR, MONO- AND DIGLYCERIDES.",
                source_type="open_food_facts",
                kosher_symbol="OU-Pareve",
                is_certified_vegan=True,
            ),
            [
                LookupTraceStep(tier="usda_fdc", status="miss", detail="Not in USDA FDC."),
                LookupTraceStep(
                    tier="open_food_facts",
                    status="hit",
                    detail="Matched Open Food Facts product 'Organic Oat Milk Chocolate'.",
                ),
            ],
        )

    monkeypatch.setattr(barcode_lookup, "lookup_external_barcode", fake_off_lookup)

    res = client.post("/api/scan", json={"upc": "085239012345", "allow_external": True})
    assert res.status_code == 200
    body = res.json()
    assert body["found"] is True
    assert body["source"] == "open_food_facts"
    assert body["product"]["is_certified_vegan"] is True
    assert body["product"]["kosher_symbol"] == "OU-Pareve"
    # Certified vegan resolves mono- and diglycerides automatically -> verified_plant_or_microbial.
    assert body["product"]["computed_status"] == "verified_plant_or_microbial"


def test_identical_snapshot_no_drift_and_validation_errors(client: TestClient) -> None:
    cabot = client.get("/api/products/prod_cabot_cheddar").json()
    same_res = client.post(
        "/api/products/prod_cabot_cheddar/snapshots",
        json={
            "raw_ingredients": cabot["current_snapshot"]["raw_ingredients"].lower(),
            "source_type": "manual",
        },
    )
    assert same_res.status_code == 200
    assert same_res.json()["drift_detected"] is False
    assert same_res.json()["added_ingredients"] == []
    assert same_res.json()["removed_ingredients"] == []

    # Validation guardrails
    assert (
        client.post(
            "/api/ocr/analyze",
            json={"raw_ingredients": "MILK, ENZYMES", "save_snapshot": True},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/forums/parse-post",
            json={
                "source_name": "r/halal",
                "title": "Test",
                "raw_text": "Enzymes are microbial.",
                "save_to_product": True,
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/products",
            json={"name": "  ", "brand": "Test", "raw_ingredients": "SALT"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/verifications",
            json={
                "product_id": "prod_missing",
                "ingredient_name": "enzymes",
                "determination": "plant_or_microbial",
                "response_excerpt": "Microbial.",
            },
        ).status_code
        == 404
    )


def test_spa_root_serves_html_when_dist_built(client: TestClient) -> None:
    root_res = client.get("/")
    assert root_res.status_code == 200
    assert "text/html" in root_res.headers.get("content-type", "")
    assert "HalalLens" in root_res.text or "root" in root_res.text

    # Non-API SPA deep link falls back to index.html, while /api/* never returns HTML.
    spa_res = client.get("/products/prod_kraft_mac")
    assert spa_res.status_code == 200
    assert "text/html" in spa_res.headers.get("content-type", "")

    api_404 = client.get("/api/products/prod_kraft_mac/unknown_subroute")
    assert api_404.status_code == 404
    assert "application/json" in api_404.headers.get("content-type", "")

