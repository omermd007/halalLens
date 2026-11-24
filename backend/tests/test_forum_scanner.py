"""Unit tests for public forum post parsing, region guards, consensus, and mocked search adapters."""

from __future__ import annotations

from datetime import date

import httpx

from app.services.forum_scanner import (
    PluggableWebForumAdapter,
    RedditForumAdapter,
    aggregate_forum_consensus,
    parse_forum_post,
    scan_public_forums,
)


def test_negation_handling_and_cert_disclaimer() -> None:
    sig = parse_forum_post(
        title="Kraft Mac & Cheese US enzymes reply",
        raw_text=(
            "I emailed Kraft Heinz US customer service about their cheese sauce. "
            "They replied that the product is not halal certified, however they do NOT use "
            "pork or animal rennet, only microbial enzymes."
        ),
        source_platform="reddit",
        source_name="r/halal",
        author="u/checker",
        posted_at="2026-09-01",
        reference_date=date(2026, 11, 20),
    )

    assert sig.claimed_determination == "plant_or_microbial"
    assert sig.evidence_tier == "quoted_company_reply"
    assert sig.region_flag == "us"
    assert sig.freshness == "recent"
    assert "enzymes" in sig.matched_ingredients


def test_questions_and_historical_vs_positive_animal_claims() -> None:
    question_sig = parse_forum_post(
        title="Does Tillamook cheddar use pork gelatin or animal rennet?",
        raw_text="Anyone know if this uses animal enzymes or calf rennet?",
        source_platform="reddit",
        source_name="r/halal",
    )
    assert question_sig.claimed_determination == "unclear"

    historical_sig = parse_forum_post(
        title="Update on cheddar enzymes",
        raw_text="They used to use animal rennet years ago, now all enzymes are 100% microbial.",
        source_platform="reddit",
        source_name="r/halal",
    )
    assert historical_sig.claimed_determination == "plant_or_microbial"

    haram_sig = parse_forum_post(
        title="Haribo Goldbears US gelatin",
        raw_text="Customer service confirmed standard U.S. Goldbears contain porcine gelatin.",
        source_platform="reddit",
        source_name="r/halal",
    )
    assert haram_sig.claimed_determination == "animal_or_haram"
    assert haram_sig.evidence_tier == "quoted_company_reply"
    assert "pork gelatin" in haram_sig.matched_ingredients

    negated_plant_sig = parse_forum_post(
        title="Cheese rennet check",
        raw_text="The company confirmed the cheese is not vegetarian and does not use microbial enzymes.",
        source_platform="forum",
        source_name="HalalCheck",
    )
    assert negated_plant_sig.claimed_determination == "animal_or_haram"


def test_supplier_variability_detection() -> None:
    sig = parse_forum_post(
        title="Mondelez reply on mono- and diglycerides",
        raw_text=(
            "Consumer relations emailed back saying the mono- and diglycerides vary by supplier "
            "and plant, so they can be either plant or animal depending on availability."
        ),
        source_platform="reddit",
        source_name="r/MuslimLounge",
        posted_at="2026-08-10",
        reference_date=date(2026, 11, 20),
    )

    assert sig.claimed_determination == "varies_by_supplier"
    assert sig.evidence_tier == "quoted_company_reply"
    assert "mono- and diglycerides" in sig.matched_ingredients


def test_non_us_region_guard_and_turkey_meat_false_positive_guard() -> None:
    uk_sig = parse_forum_post(
        title="Bought at Tesco UK",
        raw_text="The UK formulation from Sainsbury's uses microbial enzymes.",
        url="https://example.co.uk/thread/1",
    )
    assert uk_sig.region_flag == "non_us_warning"
    assert uk_sig.region_notes is not None and "UK" in uk_sig.region_notes

    ca_sig = parse_forum_post(
        title="Costco Canada confirmation",
        raw_text="Kraft Dinner bought in Ontario Canada uses microbial rennet.",
    )
    assert ca_sig.region_flag == "non_us_warning"
    assert ca_sig.region_notes is not None and "Canada" in ca_sig.region_notes

    turkey_country_sig = parse_forum_post(
        title="Haribo imported from Turkey",
        raw_text="The Turkish bags made in Turkey use halal beef gelatin.",
    )
    assert turkey_country_sig.region_flag == "non_us_warning"
    assert turkey_country_sig.region_notes is not None and "Turkey" in turkey_country_sig.region_notes

    # Poultry meat ("turkey bacon") in a U.S. post must NOT trigger Turkey non-U.S. warning!
    turkey_meat_sig = parse_forum_post(
        title="Trader Joe's breakfast wrap (US)",
        raw_text=(
            "Checked U.S. Trader Joe's cheese wrap with turkey bacon; "
            "the enzymes are microbial-derived."
        ),
        source_name="r/traderjoes",
    )
    assert turkey_meat_sig.region_flag == "us"


def test_evidence_tiers_and_freshness_buckets() -> None:
    ref = date(2026, 11, 20)

    faq_sig = parse_forum_post(
        title="Annie's Cheese FAQ",
        raw_text="All enzymes are vegetarian microbial.",
        source_platform="web_forum",
        source_name="annies.com",
        url="https://www.annies.com/faq",
        posted_at="2026-06-01",
        reference_date=ref,
    )
    assert faq_sig.evidence_tier == "official_brand_faq"
    assert faq_sig.freshness == "recent"

    aging_sig = parse_forum_post(
        title="Spoke with customer service",
        raw_text="I called customer support and they confirmed plant-derived glycerin.",
        posted_at="2025-05-01",
        reference_date=ref,
    )
    assert aging_sig.evidence_tier == "quoted_company_reply"
    assert aging_sig.freshness == "aging"

    stale_sig = parse_forum_post(
        title="Random comment about snacks",
        raw_text="Pretty sure these chips use vegetable enzymes.",
        posted_at="2023-01-15",
        reference_date=ref,
    )
    assert stale_sig.evidence_tier == "community_anecdote"
    assert stale_sig.freshness == "stale"

    unknown_sig = parse_forum_post(
        title="Undated thread",
        raw_text="Enzymes are microbial.",
        posted_at=None,
        reference_date=ref,
    )
    assert unknown_sig.freshness == "unknown"


def test_aggregate_forum_consensus_conflicts_and_non_us_isolation() -> None:
    # Domestic conflict: U.S. plant_or_microbial vs U.S. varies_by_supplier + 1 non-U.S. warning
    signals = [
        {
            "claimed_determination": "plant_or_microbial",
            "evidence_tier": "quoted_company_reply",
            "region_flag": "us",
            "posted_at": "2026-09-01",
        },
        {
            "claimed_determination": "varies_by_supplier",
            "evidence_tier": "quoted_company_reply",
            "region_flag": "us",
            "posted_at": "2026-10-15",
        },
        {
            "claimed_determination": "plant_or_microbial",
            "evidence_tier": "community_anecdote",
            "region_flag": "non_us_warning",
            "posted_at": "2026-08-01",
        },
    ]
    consensus = aggregate_forum_consensus(signals)
    assert consensus["total_signals"] == 3
    assert consensus["counts_by_determination"]["plant_or_microbial"] == 2
    assert consensus["counts_by_determination"]["varies_by_supplier"] == 1
    assert consensus["quoted_company_replies"] == 2
    assert consensus["has_conflict"] is True
    assert consensus["has_non_us_warning"] is True
    assert consensus["non_us_count"] == 1
    assert consensus["newest_post_date"] == "2026-10-15"
    assert "Conflicting reports" in consensus["summary_line"]
    assert "non-U.S." in consensus["summary_line"]

    # Non-U.S. differing post alone must NOT trigger domestic conflict.
    non_us_only_diff = [
        {
            "claimed_determination": "animal_or_haram",
            "evidence_tier": "quoted_company_reply",
            "region_flag": "us",
            "posted_at": "2026-09-01",
        },
        {
            "claimed_determination": "plant_or_microbial",
            "evidence_tier": "official_brand_faq",
            "region_flag": "non_us_warning",
            "posted_at": "2026-10-01",
        },
    ]
    non_us_consensus = aggregate_forum_consensus(non_us_only_diff)
    assert non_us_consensus["has_conflict"] is False
    assert non_us_consensus["has_non_us_warning"] is True
    assert non_us_consensus["official_brand_faqs"] == 1


def test_mocked_reddit_and_web_adapters_and_scan_orchestrator() -> None:
    def reddit_handler(request: httpx.Request) -> httpx.Response:
        if "/r/halal/" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "children": [
                            {
                                "data": {
                                    "title": "Kraft Mac & Cheese US enzymes confirmed microbial",
                                    "selftext": (
                                        "I emailed Kraft Heinz US customer service and they "
                                        "confirmed they do NOT use animal rennet, only microbial enzymes."
                                    ),
                                    "permalink": "/r/halal/comments/abc123/kraft_us/",
                                    "author": "halal_tester",
                                    "created_utc": 1785000000,
                                }
                            },
                            {
                                "data": {
                                    "title": "Unrelated car repair question",
                                    "selftext": "My Honda brake pads squeak.",
                                    "permalink": "/r/halal/comments/xyz999/car/",
                                    "author": "driver",
                                    "created_utc": 1785000000,
                                }
                            },
                        ]
                    }
                },
            )
        return httpx.Response(429, json={"message": "Too Many Requests"})

    def brave_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "url": "https://www.kraftheinz.example.com/faq",
                            "title": "Kraft Heinz US Ingredient FAQ",
                            "description": "Our US cheddar enzymes are 100% microbial.",
                            "page_age": "2026-08-15T00:00:00",
                        },
                        # Duplicate URL of Reddit thread to verify cross-adapter dedup
                        {
                            "url": "https://old.reddit.com/r/halal/comments/abc123/kraft_us",
                            "title": "Duplicate Reddit Thread",
                            "description": "Duplicate enzymes post.",
                            "page_age": "2026-07-24",
                        },
                    ]
                }
            },
        )

    reddit_client = httpx.Client(transport=httpx.MockTransport(reddit_handler))
    web_client = httpx.Client(transport=httpx.MockTransport(brave_handler))
    try:
        reddit_adapter = RedditForumAdapter(
            subreddits=["halal", "MuslimLounge", "Costco"],
            client=reddit_client,
        )
        web_adapter = PluggableWebForumAdapter(api_key="test-token", client=web_client)

        signals, statuses = scan_public_forums(
            product_name="Original Macaroni & Cheese Dinner",
            brand="Kraft",
            flagged_ingredients=["enzymes", "whey"],
            include_live_reddit=True,
            reddit_adapter=reddit_adapter,
            web_adapter=web_adapter,
        )
    finally:
        reddit_client.close()
        web_client.close()

    # Cross-adapter duplicate Reddit URL was removed; 1 Reddit + 1 Brand FAQ remain.
    assert len(signals) == 2
    assert signals[0].evidence_tier == "official_brand_faq"
    assert signals[1].evidence_tier == "quoted_company_reply"
    assert signals[1].author == "u/halal_tester"

    status_by_src = {st.source: st.status for st in statuses}
    assert status_by_src["r/halal"] == "ok"
    assert status_by_src["r/MuslimLounge"] == "rate_limited"
    assert status_by_src["r/Costco"] == "rate_limited"
    assert status_by_src["web_search_brave"] == "ok"

    # Unconfigured web adapter skips cleanly without hitting network.
    unconfigured = PluggableWebForumAdapter(api_key="")
    web_sigs, web_st = unconfigured.search("Mac & Cheese", "Kraft", ["enzymes"])
    assert web_sigs == []
    assert web_st.status == "skipped_unconfigured"
