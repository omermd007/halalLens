"""Idempotent seed data for HalalLens U.S. grocery ingredient rules, policies, and prototype products."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app import db
from app.schemas import StrictnessProfile
from app.services.ingredient_parser import compute_ingredient_hash, normalize_ingredients
from app.services.status_engine import STRICTNESS_SETTING_KEY, recompute_all_products

# ---------------------------------------------------------------------------
# 16 U.S. Grocery Ingredient Rules
# ---------------------------------------------------------------------------

INGREDIENT_RULES: list[dict[str, Any]] = [
    {
        "id": "rule_enzymes",
        "canonical_name": "enzymes",
        "aliases": [
            "enzyme",
            "microbial enzymes",
            "non-animal enzymes",
            "animal enzymes",
            "rennet",
            "cheese enzymes",
            "dairy enzymes",
            "microbial rennet",
            "vegetable rennet",
            "animal rennet",
            "chymosin",
            "pepsin",
            "lipase",
        ],
        "default_risk": "mushbooh",
        "us_context_notes": (
            "In U.S. cheeses and snacks, generic 'enzymes' can be microbial, "
            "fermentation-produced chymosin (FPC), or animal rennet (porcine/bovine)."
        ),
        "verification_question": (
            "Are the enzymes used in this product 100% microbial/non-animal derived, "
            "or are any animal-derived enzymes (porcine/bovine rennet) used?"
        ),
        "kosher_vegan_caveat": (
            "OU-D kosher dairy cheeses typically avoid pork rennet, though some kosher "
            "agencies permit kosher bovine rennet in select lines; certified vegan rules out animal enzymes."
        ),
        "strictness_key": "oud_enzymes",
    },
    {
        "id": "rule_cheese_culture",
        "canonical_name": "cheese culture",
        "aliases": [
            "cheese cultures",
            "bacterial culture",
            "bacterial cultures",
            "starter culture",
            "starter cultures",
            "dairy culture",
            "dairy cultures",
            "lactic acid starter culture",
        ],
        "default_risk": "mushbooh",
        "us_context_notes": (
            "Cheese cultures are typically lactic acid bacteria, but in U.S. dairy processing "
            "they are sometimes grown on animal-derived media or paired with undisclosed animal rennet."
        ),
        "verification_question": (
            "Are the cheese cultures grown exclusively on vegetarian/non-animal media "
            "without any animal-derived enzymes or peptones?"
        ),
        "kosher_vegan_caveat": (
            "Kosher dairy certification excludes pork media; certified vegan products do not use dairy cheese cultures."
        ),
        "strictness_key": None,
    },
    {
        "id": "rule_whey",
        "canonical_name": "whey",
        "aliases": [
            "whey powder",
            "sweet whey",
            "dried whey",
            "reduced lactose whey",
            "whey protein",
            "whey protein concentrate",
            "whey protein isolate",
            "demineralized whey",
            "whey solids",
        ],
        "default_risk": "mushbooh",
        "us_context_notes": (
            "Whey is a liquid byproduct of cheesemaking. In the U.S., sweet whey sourced from "
            "cheese made with animal rennet carries rennet-origin concerns unless verified microbial."
        ),
        "verification_question": (
            "Is the whey sourced exclusively from cheeses made with microbial/non-animal enzymes, "
            "or can it come from animal-rennet cheese production?"
        ),
        "kosher_vegan_caveat": (
            "Strict halal consumers check whey's rennet origin; lenient profiles treat whey as informational "
            "or rely on OU-D dairy supervision."
        ),
        "strictness_key": "whey",
    },
    {
        "id": "rule_mono_diglycerides",
        "canonical_name": "mono- and diglycerides",
        "aliases": [
            "mono and diglycerides",
            "mono & diglycerides",
            "mono- & diglycerides",
            "monoglycerides",
            "diglycerides",
            "distilled monoglycerides",
            "vegetable mono- and diglycerides",
            "vegetable mono and diglycerides",
            "plant mono- and diglycerides",
            "e471",
        ],
        "default_risk": "mushbooh",
        "us_context_notes": (
            "Common U.S. bakery and pasta emulsifiers synthesized from fatty acids that may be "
            "soy/palm/vegetable-derived OR animal tallow/lard-derived when unspecified on the label."
        ),
        "verification_question": (
            "Are the mono- and diglycerides 100% plant/vegetable-derived (e.g., soy or palm), "
            "with no animal-derived fatty acids?"
        ),
        "kosher_vegan_caveat": (
            "Reliable kosher certifications (OU/OK/Star-K/Kof-K) on dairy or pareve products "
            "virtually always require vegetable-derived emulsifiers; certified vegan guarantees plant origin."
        ),
        "strictness_key": "oud_enzymes",
    },
    {
        "id": "rule_gelatin",
        "canonical_name": "gelatin",
        "aliases": [
            "gelatine",
            "beef gelatin",
            "bovine gelatin",
            "fish gelatin",
            "kosher fish gelatin",
            "kosher gelatin",
            "hydrolyzed gelatin",
            "gelatin (bovine)",
            "gelatin (fish)",
        ],
        "default_risk": "mushbooh",
        "us_context_notes": (
            "Unqualified 'gelatin' in U.S. candies, marshmallows, yogurts, and capsules is most "
            "commonly porcine or non-zabiha bovine unless explicitly certified halal or fish-derived."
        ),
        "verification_question": (
            "What is the exact species origin of the gelatin (fish, zabiha halal beef, bovine, or porcine), "
            "and is it certified halal or kosher fish gelatin?"
        ),
        "kosher_vegan_caveat": (
            "Kosher fish gelatin is generally acceptable to most Muslims; generic kosher gelatin "
            "may be bovine or hide-derived. Certified vegan products never contain animal gelatin."
        ),
        "strictness_key": None,
    },
    {
        "id": "rule_pork_gelatin",
        "canonical_name": "pork gelatin",
        "aliases": [
            "porcine gelatin",
            "gelatin (porcine)",
            "gelatin (pork)",
            "pork-derived gelatin",
            "porcine-derived gelatin",
            "swine gelatin",
            "pig gelatin",
        ],
        "default_risk": "haram_animal",
        "us_context_notes": (
            "Porcine-derived gelatin is explicitly prohibited (haram) in Islamic dietary law "
            "and is widely used in U.S. conventional gummy candies and marshmallows."
        ),
        "verification_question": (
            "Please confirm whether this U.S. SKU uses porcine gelatin or has been reformulated to "
            "a halal beef, fish, or plant-based gelling agent."
        ),
        "kosher_vegan_caveat": (
            "Absent from all kosher-certified and vegan-certified foods."
        ),
        "strictness_key": None,
    },
    {
        "id": "rule_carmine",
        "canonical_name": "carmine",
        "aliases": [
            "cochineal",
            "cochineal extract",
            "carminic acid",
            "natural red 4",
            "e120",
            "carmine color",
            "crimson lake",
        ],
        "default_risk": "haram_animal",
        "us_context_notes": (
            "Red colorant extracted from crushed cochineal insects (Dactylopius coccus), "
            "commonly used in U.S. strawberry yogurts, candies, and fruit drinks."
        ),
        "verification_question": (
            "Does this product contain insect-derived carmine/cochineal extract, or a plant/synthetic red colorant?"
        ),
        "kosher_vegan_caveat": (
            "Not permitted by mainstream kosher agencies (OU/OK/Star-K) or vegan certifications."
        ),
        "strictness_key": None,
    },
    {
        "id": "rule_lard",
        "canonical_name": "lard",
        "aliases": [
            "pork lard",
            "hydrogenated lard",
            "partially hydrogenated lard",
            "rendered pork fat",
            "pork fat",
            "bacon fat",
        ],
        "default_risk": "haram_animal",
        "us_context_notes": (
            "Rendered pig fat frequently found in traditional U.S. refried beans, flour tortillas, "
            "pie crusts, and boxed pastry mixes."
        ),
        "verification_question": (
            "Please confirm whether any pork lard or animal shortening is used in this SKU."
        ),
        "kosher_vegan_caveat": (
            "Never permitted in kosher or vegan products."
        ),
        "strictness_key": None,
    },
    {
        "id": "rule_l_cysteine",
        "canonical_name": "L-cysteine",
        "aliases": [
            "l-cysteine",
            "l-cysteine hydrochloride",
            "l-cysteine monohydrochloride",
            "cysteine",
            "e920",
        ],
        "default_risk": "mushbooh",
        "us_context_notes": (
            "Dough conditioner in U.S. bagels, pizza crusts, and commercial breads that can be "
            "produced via microbial fermentation or extracted from poultry feathers, hog hair, or human hair."
        ),
        "verification_question": (
            "Is the L-cysteine produced exclusively via microbial/plant fermentation, "
            "or is any of it derived from animal feathers, hair, or porcine sources?"
        ),
        "kosher_vegan_caveat": (
            "Certified vegan guarantees fermentation-derived L-cysteine; kosher status varies by agency."
        ),
        "strictness_key": None,
    },
    {
        "id": "rule_glycerin",
        "canonical_name": "glycerin",
        "aliases": [
            "glycerine",
            "glycerol",
            "vegetable glycerin",
            "vegetable glycerine",
            "plant-based glycerin",
            "plant glycerin",
            "soy-derived glycerin",
            "e422",
        ],
        "default_risk": "mushbooh",
        "us_context_notes": (
            "Humectant and sweetener in U.S. snack bars, soft cookies, and flavor carriers; "
            "may be derived from vegetable oils, petroleum synthesis, or animal fats."
        ),
        "verification_question": (
            "Is the glycerin 100% plant/vegetable-derived or synthetic, with no animal-fat origin?"
        ),
        "kosher_vegan_caveat": (
            "OU/OK/Star-K pareve or dairy products and certified vegan products use plant or synthetic glycerin."
        ),
        "strictness_key": None,
    },
    {
        "id": "rule_natural_flavors",
        "canonical_name": "natural flavors",
        "aliases": [
            "natural flavor",
            "natural flavoring",
            "natural flavorings",
            "natural and artificial flavor",
            "natural and artificial flavors",
            "natural & artificial flavor",
            "natural & artificial flavors",
            "natural vanilla flavor",
            "natural cheese flavor",
        ],
        "default_risk": "mushbooh",
        "us_context_notes": (
            "FDA umbrella term that can include plant extracts, dairy/meat-derived flavor compounds, "
            "or ethyl alcohol as a solvent carrier without separate disclosure."
        ),
        "verification_question": (
            "Are the natural flavors free of animal-derived ingredients (meat/poultry/porcine extracts, "
            "animal glycerin) and free of ethyl alcohol carriers?"
        ),
        "kosher_vegan_caveat": (
            "Certified vegan rules out animal-derived flavors (though not necessarily trace ethanol carriers); "
            "kosher pareve rules out meat/dairy derivatives."
        ),
        "strictness_key": "natural_flavors",
    },
    {
        "id": "rule_confectioners_glaze",
        "canonical_name": "confectioner's glaze",
        "aliases": [
            "confectioners glaze",
            "confectioners' glaze",
            "resinous glaze",
            "pharmaceutical glaze",
            "shellac",
            "lac resin",
            "e904",
        ],
        "default_risk": "mushbooh",
        "us_context_notes": (
            "Shiny coating on U.S. candies, jelly beans, and chocolate-covered nuts made from "
            "lac beetle resin (shellac) often dissolved in food-grade ethanol."
        ),
        "verification_question": (
            "Is the confectioner's glaze derived from insect shellac or plant wax (e.g., carnauba), "
            "and is ethyl alcohol used as the carrier solvent?"
        ),
        "kosher_vegan_caveat": (
            "Certified vegan products avoid insect shellac; kosher agencies often permit shellac, "
            "so kosher symbols do not rule it out."
        ),
        "strictness_key": None,
    },
    {
        "id": "rule_vitamin_d3",
        "canonical_name": "vitamin D3",
        "aliases": [
            "vitamin d3",
            "cholecalciferol",
            "vit d3",
            "vitamin d3 (cholecalciferol)",
            "vitamin d3 (lanolin)",
            "vitamin d3 (lichen)",
        ],
        "default_risk": "mushbooh",
        "us_context_notes": (
            "Commonly fortified into U.S. cereals, orange juice, and dairy. Usually extracted from "
            "sheep's wool lanolin (often accepted by some scholars, avoided by others) or occasionally "
            "stabilized with porcine/bovine gelatin; lichen-derived D3 is plant-based."
        ),
        "verification_question": (
            "What is the source of the Vitamin D3 (lichen/plant vs. sheep lanolin), and is any "
            "animal gelatin used as a carrier or stabilizer?"
        ),
        "kosher_vegan_caveat": (
            "Certified vegan requires lichen/algae D3 and rules out gelatin carriers."
        ),
        "strictness_key": None,
    },
    {
        "id": "rule_ssl",
        "canonical_name": "sodium stearoyl lactylate",
        "aliases": [
            "calcium stearoyl lactylate",
            "stearoyl lactylate",
            "ssl",
            "e481",
            "e482",
            "datem",
        ],
        "default_risk": "mushbooh",
        "us_context_notes": (
            "Dough strengthener and emulsifier in U.S. breads, tortillas, and crackers made from "
            "stearic acid (which can be vegetable-oil or animal-tallow derived) and lactic acid."
        ),
        "verification_question": (
            "Is the stearic acid in the sodium stearoyl lactylate 100% vegetable/plant-derived "
            "with no animal fat origin?"
        ),
        "kosher_vegan_caveat": (
            "Certified vegan guarantees plant origin; major kosher pareve symbols typically require plant stearic acid."
        ),
        "strictness_key": None,
    },
    {
        "id": "rule_vanilla_extract",
        "canonical_name": "vanilla extract",
        "aliases": [
            "pure vanilla extract",
            "organic vanilla extract",
            "madagascar vanilla extract",
            "bourbon vanilla extract",
            "natural vanilla extract",
            "imitation vanilla extract",
            "alcohol-free vanilla extract",
        ],
        "default_risk": "mushbooh",
        "us_context_notes": (
            "Under U.S. FDA Standard of Identity (21 CFR 169.175), pure vanilla extract must "
            "contain at least 35% ethyl alcohol by volume unless labeled alcohol-free; scholarly views vary "
            "on trace cooking/baking ethanol."
        ),
        "verification_question": (
            "Is the vanilla extract alcohol-free/glycerin-based, or does it contain ethyl alcohol "
            "(and what residual ethanol remains in the finished product)?"
        ),
        "kosher_vegan_caveat": (
            "Certified vegan and kosher products frequently contain standard 35%-ethanol vanilla extract; "
            "neither certification rules out ethanol."
        ),
        "strictness_key": "vanilla_ethanol",
    },
    {
        "id": "rule_alcohol_wine",
        "canonical_name": "alcohol / wine",
        "aliases": [
            "ethyl alcohol",
            "ethanol",
            "wine",
            "red wine",
            "white wine",
            "cooking wine",
            "sherry",
            "sherry wine",
            "marsala wine",
            "rice wine",
            "mirin",
            "sake",
            "beer",
            "bourbon",
            "rum",
            "brandy",
            "vodka",
            "whiskey",
            "liqueur",
            "alcohol",
        ],
        "default_risk": "haram_animal",
        "us_context_notes": (
            "Intoxicants such as wine, mirin, beer, spirits, or added ethyl alcohol are prohibited "
            "in Islamic dietary law (note: wine vinegar is handled separately from wine)."
        ),
        "verification_question": (
            "Please confirm whether this product contains added alcoholic beverage ingredients or ethyl alcohol."
        ),
        "kosher_vegan_caveat": (
            "Both vegan and kosher products may freely contain wine, beer, or spirits."
        ),
        "strictness_key": None,
    },
]


def _seed_rules(conn: sqlite3.Connection) -> None:
    for rule in INGREDIENT_RULES:
        conn.execute(
            """
            INSERT OR IGNORE INTO ingredient_rules (
                id, canonical_name, aliases_json, default_risk,
                us_context_notes, verification_question, kosher_vegan_caveat, strictness_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule["id"],
                rule["canonical_name"],
                json.dumps(rule["aliases"]),
                rule["default_risk"],
                rule["us_context_notes"],
                rule["verification_question"],
                rule["kosher_vegan_caveat"],
                rule["strictness_key"],
            ),
        )


def _seed_brand_policies(conn: sqlite3.Connection, today: datetime) -> None:
    now_iso = today.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    checked_annies = (today - timedelta(days=75)).date().isoformat()
    expires_annies = (today + timedelta(days=290)).date().isoformat()
    checked_cabot = (today - timedelta(days=60)).date().isoformat()
    expires_cabot = (today + timedelta(days=305)).date().isoformat()

    policies = [
        {
            "id": "bp_annies",
            "brand": "Annie's",
            "scope_description": (
                "Illustrative prototype seed policy: Annie's U.S. mac & cheese and cheddar "
                "lines state they use vegetarian/microbial enzymes and vegetarian-sourced dairy cultures/whey."
            ),
            "applies_to_ingredients": ["enzymes", "cheese culture", "whey"],
            "determination": "plant_or_microbial",
            "source_url": "https://www.annies.com/faq",
            "excerpt": (
                "[Prototype seed excerpt] Annie's FAQ states that all enzymes used in Annie's "
                "macaroni & cheese products are microbial/non-animal derived."
            ),
            "checked_date": checked_annies,
            "expires_at": expires_annies,
        },
        {
            "id": "bp_cabot",
            "brand": "Cabot Creamery",
            "scope_description": (
                "Illustrative prototype seed policy: Cabot Creamery U.S. cheddar cheeses use "
                "microbial rennet/enzymes and non-animal lactic starter cultures."
            ),
            "applies_to_ingredients": ["enzymes", "cheese culture"],
            "determination": "plant_or_microbial",
            "source_url": "https://cabotcreamery.com/pages/faq",
            "excerpt": (
                "[Prototype seed excerpt] Cabot Creamery FAQ notes that Cabot cheddars are "
                "made with vegetarian microbial enzymes (no animal rennet)."
            ),
            "checked_date": checked_cabot,
            "expires_at": expires_cabot,
        },
    ]

    for pol in policies:
        conn.execute(
            """
            INSERT OR IGNORE INTO brand_policies (
                id, brand, scope_description, applies_to_ingredients_json,
                determination, source_url, excerpt, checked_date, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pol["id"],
                pol["brand"],
                pol["scope_description"],
                json.dumps(pol["applies_to_ingredients"]),
                pol["determination"],
                pol["source_url"],
                pol["excerpt"],
                pol["checked_date"],
                pol["expires_at"],
                now_iso,
            ),
        )


def _insert_seed_product(
    conn: sqlite3.Connection,
    *,
    product_id: str,
    upc: str,
    name: str,
    brand: str,
    category: str,
    certifier_name: str | None,
    certifier_status: str | None,
    kosher_symbol: str | None,
    is_certified_vegan: bool,
    brand_contact_email: str | None,
    brand_contact_url: str | None,
    created_at: str,
    updated_at: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO products (
            id, upc, name, brand, category, certifier_name, certifier_status,
            kosher_symbol, is_certified_vegan, brand_contact_email, brand_contact_url,
            computed_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product_id,
            upc,
            name,
            brand,
            category,
            certifier_name,
            certifier_status,
            kosher_symbol,
            1 if is_certified_vegan else 0,
            brand_contact_email,
            brand_contact_url,
            "mushbooh_needs_check",
            created_at,
            updated_at,
        ),
    )


def _insert_seed_snapshot(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str,
    product_id: str,
    raw_ingredients: str,
    source_type: str,
    captured_at: str,
    is_current: bool,
    lot_code: str | None = None,
    plant_code: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO formulation_snapshots (
            id, product_id, raw_ingredients, normalized_ingredients,
            ingredient_hash, source_type, lot_code, plant_code, captured_at, is_current
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            product_id,
            raw_ingredients,
            normalize_ingredients(raw_ingredients),
            compute_ingredient_hash(raw_ingredients),
            source_type,
            lot_code,
            plant_code,
            captured_at,
            1 if is_current else 0,
        ),
    )


def _seed_products_and_records(conn: sqlite3.Connection, now: datetime) -> None:
    def iso_ts(days_ago: int) -> str:
        return (now - timedelta(days=days_ago)).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def iso_day(delta_days: int) -> str:
        return (now + timedelta(days=delta_days)).date().isoformat()

    # -----------------------------------------------------------------------
    # 1. Kraft Original Macaroni & Cheese Dinner -> mushbooh_needs_check
    # -----------------------------------------------------------------------
    _insert_seed_product(
        conn,
        product_id="prod_kraft_mac",
        upc="021000658831",
        name="Original Macaroni & Cheese Dinner",
        brand="Kraft",
        category="Mac & Cheese",
        certifier_name=None,
        certifier_status=None,
        kosher_symbol="OU-D",
        is_certified_vegan=False,
        brand_contact_email=None,
        brand_contact_url="https://contactus.kraftheinz.com/en-us",
        created_at=iso_ts(45),
        updated_at=iso_ts(4),
    )
    _insert_seed_snapshot(
        conn,
        snapshot_id="snap_kraft_mac_v1",
        product_id="prod_kraft_mac",
        raw_ingredients=(
            "ENRICHED MACARONI (WHEAT FLOUR, DURUM FLOUR, NIACIN, FERROUS SULFATE [IRON], "
            "THIAMIN MONONITRATE [VITAMIN B1], RIBOFLAVIN [VITAMIN B2], FOLIC ACID), "
            "CHEESE SAUCE MIX (WHEY, MILKFAT, SALT, MILK PROTEIN CONCENTRATE, SODIUM TRIPHOSPHATE, "
            "CONTAINS LESS THAN 2% OF TAPIOCA FLOUR, CITRIC ACID, LACTIC ACID, SODIUM PHOSPHATE, "
            "CALCIUM PHOSPHATE, WITH PAPRIKA, TURMERIC, AND ANNATTO ADDED FOR COLOR, "
            "ENZYMES, CHEESE CULTURE)."
        ),
        source_type="seed",
        captured_at=iso_ts(45),
        is_current=True,
    )
    # 3 seeded forum signals: U.S. quoted reply (plant_or_microbial), U.S. varies_by_supplier, Canada non_us_warning
    kraft_signals = [
        (
            "fs_kraft_1",
            "prod_kraft_mac",
            "reddit",
            "r/halal",
            "https://www.reddit.com/r/halal/comments/kraft_mac_us_seed",
            "Emailed Kraft Heinz US about Original Mac & Cheese enzymes",
            "u/us_halal_shopper",
            iso_day(-95),
            (
                "[Illustrative prototype seed] I emailed Kraft Heinz U.S. customer service last month; "
                "they replied that the enzymes used in Kraft Original Mac & Cheese are microbial-derived."
            ),
            ["enzymes", "whey"],
            "plant_or_microbial",
            "quoted_company_reply",
            "recent",
            "us",
            "Explicitly references U.S. Kraft Heinz distribution",
            iso_ts(5),
        ),
        (
            "fs_kraft_2",
            "prod_kraft_mac",
            "forum",
            "HalalConsumerUS",
            "https://example.org/forum/kraft-mac-supplier-note",
            "Kraft Mac & Cheese whey/enzymes supplier variability report (US)",
            "amin_chicago",
            iso_day(-140),
            (
                "[Illustrative prototype seed] When I called Kraft U.S. consumer relations, the rep "
                "said enzyme and whey sourcing can vary by plant/supplier and advised checking per lot."
            ),
            ["enzymes", "whey", "cheese culture"],
            "varies_by_supplier",
            "quoted_company_reply",
            "recent",
            "us",
            "U.S. consumer call report noting supplier variability",
            iso_ts(5),
        ),
        (
            "fs_kraft_3",
            "prod_kraft_mac",
            "reddit",
            "r/HalalCanada",
            "https://www.reddit.com/r/HalalCanada/comments/kraft_dinner_ca_seed",
            "Kraft Dinner (KD) Canada enzymes confirmation",
            "u/toronto_eats",
            iso_day(-65),
            (
                "[Illustrative prototype seed] Kraft Heinz Canada confirmed Canadian KD uses microbial "
                "enzymes — note Canadian Kraft Dinner formulation differs from U.S. Kraft Mac & Cheese."
            ),
            ["enzymes"],
            "plant_or_microbial",
            "community_anecdote",
            "recent",
            "non_us_warning",
            "Mentions Canada / Kraft Dinner (KD); non-U.S. formulation may differ",
            iso_ts(5),
        ),
    ]
    for sig in kraft_signals:
        conn.execute(
            """
            INSERT OR IGNORE INTO forum_signals (
                id, product_id, source_platform, source_name, url, title, author,
                posted_at, raw_excerpt, matched_ingredients_json, claimed_determination,
                evidence_tier, freshness, region_flag, region_notes, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sig[0], sig[1], sig[2], sig[3], sig[4], sig[5], sig[6],
                sig[7], sig[8], json.dumps(sig[9]), sig[10],
                sig[11], sig[12], sig[13], sig[14], sig[15],
            ),
        )

    conn.execute(
        """
        INSERT OR IGNORE INTO community_notes (
            id, product_id, author_label, note_text, confidence_tier, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "note_kraft_1",
            "prod_kraft_mac",
            "Personal Note",
            (
                "[Illustrative prototype seed] Checked 7.25 oz box at Costco; OU-D symbol printed on "
                "top flap, but enzymes and whey remain unverified directly for this lot."
            ),
            "secondary_observation",
            iso_ts(6),
        ),
    )

    # -----------------------------------------------------------------------
    # 2. Annie's Shells & Real Aged Cheddar -> verified_plant_or_microbial
    # -----------------------------------------------------------------------
    _insert_seed_product(
        conn,
        product_id="prod_annies_mac",
        upc="013562300143",
        name="Shells & Real Aged Cheddar",
        brand="Annie's",
        category="Mac & Cheese",
        certifier_name=None,
        certifier_status=None,
        kosher_symbol=None,
        is_certified_vegan=False,
        brand_contact_email=None,
        brand_contact_url="https://ask.generalmills.com/s/",
        created_at=iso_ts(50),
        updated_at=iso_ts(8),
    )
    _insert_seed_snapshot(
        conn,
        snapshot_id="snap_annies_mac_v1",
        product_id="prod_annies_mac",
        raw_ingredients=(
            "ORGANIC PASTA (ORGANIC WHEAT FLOUR), CHEDDAR CHEESE (PASTEURIZED MILK, "
            "CHEESE CULTURE, SALT, ENZYMES), WHEY, BUTTER (PASTEURIZED CREAM, SALT), "
            "NONFAT MILK, SALT, SODIUM PHOSPHATE, ANNATTO EXTRACT (FOR COLOR)."
        ),
        source_type="seed",
        captured_at=iso_ts(50),
        is_current=True,
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO company_verifications (
            id, product_id, formulation_snapshot_id, ingredient_name, determination,
            varies_by_supplier, contact_channel, company_contact, response_excerpt,
            lot_code, plant_code, verified_date, expires_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ver_annies_enzymes",
            "prod_annies_mac",
            "snap_annies_mac_v1",
            "enzymes",
            "plant_or_microbial",
            0,
            "web_form",
            "General Mills / Annie's Consumer Services",
            (
                "[Illustrative prototype seed] General Mills / Annie's confirmed all enzymes "
                "used in Shells & Real Aged Cheddar are 100% microbial/non-animal across U.S. plants."
            ),
            None,
            None,
            iso_day(-35),
            iso_day(330),
            iso_ts(35),
        ),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO forum_signals (
            id, product_id, source_platform, source_name, url, title, author,
            posted_at, raw_excerpt, matched_ingredients_json, claimed_determination,
            evidence_tier, freshness, region_flag, region_notes, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "fs_annies_faq",
            "prod_annies_mac",
            "brand_faq",
            "Annie's Official FAQ",
            "https://www.annies.com/faq",
            "Are the enzymes in Annie's Mac & Cheese vegetarian?",
            "Annie's Homegrown",
            iso_day(-75),
            (
                "[Illustrative prototype seed] Official FAQ confirms Annie's uses microbial, "
                "non-animal enzymes in all U.S. cheddar mac & cheese varieties."
            ),
            json.dumps(["enzymes", "cheese culture"]),
            "plant_or_microbial",
            "official_brand_faq",
            "recent",
            "us",
            "Official U.S. brand FAQ statement",
            iso_ts(10),
        ),
    )

    # -----------------------------------------------------------------------
    # 3. Goodles Cheddy Mac -> formulation_changed (2 snapshots + drafted outreach)
    # -----------------------------------------------------------------------
    _insert_seed_product(
        conn,
        product_id="prod_goodles_cheddy",
        upc="850031990012",
        name="Cheddy Mac",
        brand="Goodles",
        category="Mac & Cheese",
        certifier_name=None,
        certifier_status=None,
        kosher_symbol=None,
        is_certified_vegan=False,
        brand_contact_email="help@goodles.com",
        brand_contact_url="https://www.goodles.com/contact/",
        created_at=iso_ts(180),
        updated_at=iso_ts(3),
    )
    _insert_seed_snapshot(
        conn,
        snapshot_id="snap_goodles_v1",
        product_id="prod_goodles_cheddy",
        raw_ingredients=(
            "GOODER NOODLES (WHEAT FLOUR, CHICKPEA PROTEIN, WHEAT PROTEIN, NUTRIENTS EXTRACTED FROM BROCCOLI), "
            "CHEDDAR CHEESE (PASTEURIZED MILK, CHEESE CULTURE, SALT, ENZYMES), "
            "CULTURED BUTTERMILK, WHEY, BUTTER, SALT, SODIUM PHOSPHATE, ANNATTO EXTRACT."
        ),
        source_type="seed",
        captured_at=iso_ts(180),
        is_current=False,
        lot_code="GL-2601A",
    )
    _insert_seed_snapshot(
        conn,
        snapshot_id="snap_goodles_v2",
        product_id="prod_goodles_cheddy",
        raw_ingredients=(
            "GOODER NOODLES (WHEAT FLOUR, CHICKPEA PROTEIN, WHEAT PROTEIN, NUTRIENTS EXTRACTED FROM BROCCOLI), "
            "CHEDDAR CHEESE (PASTEURIZED MILK, CHEESE CULTURE, SALT, ENZYMES), "
            "WHEY, BUTTER, SALT, SODIUM PHOSPHATE, MONO- AND DIGLYCERIDES, NATURAL FLAVORS, ANNATTO EXTRACT."
        ),
        source_type="ocr",
        captured_at=iso_ts(3),
        is_current=True,
        lot_code="GL-2611C",
    )
    for idx, ing_name in enumerate(["enzymes", "cheese culture", "whey"], start=1):
        conn.execute(
            """
            INSERT OR IGNORE INTO company_verifications (
                id, product_id, formulation_snapshot_id, ingredient_name, determination,
                varies_by_supplier, contact_channel, company_contact, response_excerpt,
                lot_code, plant_code, verified_date, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"ver_goodles_v1_{idx}",
                "prod_goodles_cheddy",
                "snap_goodles_v1",
                ing_name,
                "plant_or_microbial",
                0,
                "email",
                "help@goodles.com",
                (
                    f"[Illustrative prototype seed] Goodles confirmed {ing_name} in the prior "
                    f"Cheddy Mac formulation (lot GL-2601A) was 100% microbial/vegetarian."
                ),
                "GL-2601A",
                None,
                iso_day(-165),
                iso_day(200),
                iso_ts(165),
            ),
        )
    # Seed 1 drafted outreach inquiry on Goodles so Review Queue pending_outreach has real data.
    conn.execute(
        """
        INSERT OR IGNORE INTO outreach_inquiries (
            id, product_id, formulation_snapshot_id, target_email,
            flagged_ingredients_json, generated_subject, generated_body,
            mode, state, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "out_goodles_drift_1",
            "prod_goodles_cheddy",
            "snap_goodles_v2",
            "help@goodles.com",
            json.dumps(["cheese culture", "enzymes", "mono- and diglycerides", "natural flavors", "whey"]),
            "Ingredient Source Inquiry: Goodles Cheddy Mac (UPC 850031990012)",
            (
                "Hello Goodles Consumer Relations Team,\n\n"
                "I noticed a recent label update on U.S. Goodles Cheddy Mac (UPC 850031990012, Lot GL-2611C) "
                "adding mono- and diglycerides and natural flavors. Could you please confirm whether the "
                "mono- and diglycerides, natural flavors, enzymes, cheese culture, and whey in this updated "
                "formulation are 100% plant/microbial derived and consistent across U.S. suppliers?\n\n"
                "Thank you!"
            ),
            "full_inquiry",
            "drafted",
            iso_ts(2),
            iso_ts(2),
        ),
    )

    # -----------------------------------------------------------------------
    # 4. Saffron Road Chicken Tikka Masala -> certified_halal
    # -----------------------------------------------------------------------
    _insert_seed_product(
        conn,
        product_id="prod_saffron_tikka",
        upc="815652010014",
        name="Chicken Tikka Masala",
        brand="Saffron Road",
        category="Frozen Entrees",
        certifier_name="IFANCA",
        certifier_status="active",
        kosher_symbol=None,
        is_certified_vegan=False,
        brand_contact_email="customerservice@saffronroad.com",
        brand_contact_url="https://www.saffronroad.com/pages/contact",
        created_at=iso_ts(40),
        updated_at=iso_ts(12),
    )
    _insert_seed_snapshot(
        conn,
        snapshot_id="snap_saffron_tikka_v1",
        product_id="prod_saffron_tikka",
        raw_ingredients=(
            "COOKED BASMATI RICE (WATER, BASMATI RICE), ROASTED WHITE MEAT CHICKEN "
            "(HALAL CHICKEN BREAST, WATER, RICE STARCH, SEA SALT), TOMATO PUREE, "
            "HEAVY CREAM, ONIONS, GREEK YOGURT (CULTURED PASTEURIZED MILK), "
            "GARLIC, GINGER, GARAM MASALA SPICES, CILANTRO, CANOLA OIL, SEA SALT."
        ),
        source_type="seed",
        captured_at=iso_ts(40),
        is_current=True,
    )

    # -----------------------------------------------------------------------
    # 5. Haribo Goldbears Gummi Candy (U.S.) -> animal_or_haram
    # -----------------------------------------------------------------------
    _insert_seed_product(
        conn,
        product_id="prod_haribo_us",
        upc="042238302124",
        name="Goldbears Gummi Candy (U.S.)",
        brand="Haribo",
        category="Candy",
        certifier_name=None,
        certifier_status=None,
        kosher_symbol=None,
        is_certified_vegan=False,
        brand_contact_email=None,
        brand_contact_url="https://www.haribo.com/en-us/about-us/contact",
        created_at=iso_ts(60),
        updated_at=iso_ts(7),
    )
    _insert_seed_snapshot(
        conn,
        snapshot_id="snap_haribo_us_v1",
        product_id="prod_haribo_us",
        raw_ingredients=(
            "GLUCOSE SYRUP, SUGAR, GELATIN (PORCINE), DEXTROSE, CITRIC ACID, CORN STARCH, "
            "ARTIFICIAL AND NATURAL FLAVORS, PALM KERNEL OIL, CARNAUBA WAX, "
            "WHITE BEESWAX, YELLOW BEESWAX, COLORED WITH FRUIT AND VEGETABLE JUICE."
        ),
        source_type="seed",
        captured_at=iso_ts(60),
        is_current=True,
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO company_verifications (
            id, product_id, formulation_snapshot_id, ingredient_name, determination,
            varies_by_supplier, contact_channel, company_contact, response_excerpt,
            lot_code, plant_code, verified_date, expires_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ver_haribo_us_gelatin",
            "prod_haribo_us",
            "snap_haribo_us_v1",
            "pork gelatin",
            "animal_or_haram",
            0,
            "faq",
            "Haribo of America Consumer Care",
            (
                "[Illustrative prototype seed] Haribo USA confirms standard U.S. retail Goldbears "
                "contain pork-derived (porcine) gelatin and are not halal certified."
            ),
            None,
            None,
            iso_day(-30),
            iso_day(335),
            iso_ts(30),
        ),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO forum_signals (
            id, product_id, source_platform, source_name, url, title, author,
            posted_at, raw_excerpt, matched_ingredients_json, claimed_determination,
            evidence_tier, freshness, region_flag, region_notes, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "fs_haribo_turkey_warn",
            "prod_haribo_us",
            "reddit",
            "r/halal",
            "https://www.reddit.com/r/halal/comments/haribo_turkey_vs_us_seed",
            "PSA: Turkey-made Halal Haribo Goldbears vs standard U.S. bags",
            "u/grocery_checker",
            iso_day(-50),
            (
                "[Illustrative prototype seed] Only specialty bags imported from Turkey with the "
                "Halal beef-gelatin seal are halal. Standard U.S. Haribo Goldbears (UPC 042238302124) "
                "use pork gelatin."
            ),
            json.dumps(["pork gelatin", "gelatin"]),
            "animal_or_haram",
            "quoted_company_reply",
            "recent",
            "non_us_warning",
            "Contrasts Turkey halal export SKU with standard U.S. porcine SKU",
            iso_ts(7),
        ),
    )

    # -----------------------------------------------------------------------
    # 6. Trader Joe's Mini Marshmallows -> verified_plant_or_microbial (vegan)
    # -----------------------------------------------------------------------
    _insert_seed_product(
        conn,
        product_id="prod_tj_marshmallows",
        upc="00547198",
        name="Mini Marshmallows",
        brand="Trader Joe's",
        category="Baking & Snacks",
        certifier_name=None,
        certifier_status=None,
        kosher_symbol="OU-Pareve",
        is_certified_vegan=True,
        brand_contact_email=None,
        brand_contact_url="https://www.traderjoes.com/home/contact-us/product-feedback.html",
        created_at=iso_ts(35),
        updated_at=iso_ts(14),
    )
    _insert_seed_snapshot(
        conn,
        snapshot_id="snap_tj_marshmallows_v1",
        product_id="prod_tj_marshmallows",
        raw_ingredients=(
            "TAPIOCA SYRUP, CANE SUGAR, FILTERED WATER, TAPIOCA STARCH, CARRAGEENAN, "
            "SOY PROTEIN, NATURAL VANILLA FLAVOR."
        ),
        source_type="seed",
        captured_at=iso_ts(35),
        is_current=True,
    )

    # -----------------------------------------------------------------------
    # 7. Nabisco Oreo Original Cookies -> mushbooh_needs_check (varies_by_supplier)
    # -----------------------------------------------------------------------
    _insert_seed_product(
        conn,
        product_id="prod_oreo_original",
        upc="044000032029",
        name="Oreo Original Chocolate Sandwich Cookies",
        brand="Nabisco",
        category="Cookies & Snacks",
        certifier_name=None,
        certifier_status=None,
        kosher_symbol="OU-D",
        is_certified_vegan=False,
        brand_contact_email=None,
        brand_contact_url="https://www.mondelezinternational.com/contact-us/consumers/",
        created_at=iso_ts(30),
        updated_at=iso_ts(5),
    )
    _insert_seed_snapshot(
        conn,
        snapshot_id="snap_oreo_original_v1",
        product_id="prod_oreo_original",
        raw_ingredients=(
            "UNBLEACHED ENRICHED FLOUR (WHEAT FLOUR, NIACIN, REDUCED IRON, THIAMINE MONONITRATE, "
            "RIBOFLAVIN, FOLIC ACID), SUGAR, PALM OIL, SOYBEAN AND/OR CANOLA OIL, "
            "COCOA (PROCESSED WITH ALKALI), HIGH FRUCTOSE CORN SYRUP, "
            "LEAVENING (BAKING SODA, CALCIUM PHOSPHATE), SALT, SOY LECITHIN, CHOCOLATE, "
            "NATURAL FLAVORS, ARTIFICIAL FLAVOR."
        ),
        source_type="seed",
        captured_at=iso_ts(30),
        is_current=True,
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO company_verifications (
            id, product_id, formulation_snapshot_id, ingredient_name, determination,
            varies_by_supplier, contact_channel, company_contact, response_excerpt,
            lot_code, plant_code, verified_date, expires_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ver_oreo_nat_flavors",
            "prod_oreo_original",
            "snap_oreo_original_v1",
            "natural flavors",
            "varies_by_supplier",
            1,
            "web_form",
            "Mondelez U.S. Consumer Care",
            (
                "[Illustrative prototype seed] Mondelez U.S. consumer relations noted that "
                "flavor carriers for natural flavors can vary by U.S. plant/supplier and cannot "
                "be guaranteed halal-certified across all lines."
            ),
            None,
            None,
            iso_day(-20),
            iso_day(345),
            iso_ts(20),
        ),
    )

    # -----------------------------------------------------------------------
    # 8. Cabot Seriously Sharp Cheddar Cheese -> verified_plant_or_microbial (BrandPolicy)
    # -----------------------------------------------------------------------
    _insert_seed_product(
        conn,
        product_id="prod_cabot_cheddar",
        upc="078354701025",
        name="Seriously Sharp Cheddar Cheese",
        brand="Cabot Creamery",
        category="Dairy & Cheese",
        certifier_name=None,
        certifier_status=None,
        kosher_symbol="OU-D",
        is_certified_vegan=False,
        brand_contact_email="info@cabotcheese.com",
        brand_contact_url="https://cabotcreamery.gorgias.help/en-US",
        created_at=iso_ts(25),
        updated_at=iso_ts(9),
    )
    _insert_seed_snapshot(
        conn,
        snapshot_id="snap_cabot_cheddar_v1",
        product_id="prod_cabot_cheddar",
        raw_ingredients="PASTEURIZED MILK, CHEESE CULTURES, SALT, ENZYMES.",
        source_type="seed",
        captured_at=iso_ts(25),
        is_current=True,
    )


def seed_database(conn: sqlite3.Connection, include_examples: bool | None = None) -> None:
    """Idempotently populate rules, default strictness profile, and (optionally) prototype products."""
    from app import config

    now = datetime.now(timezone.utc)
    now_iso = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    # Ensure default strictness profile exists without overwriting user modifications.
    default_profile = StrictnessProfile()
    conn.execute(
        """
        INSERT OR IGNORE INTO user_settings (key, value_json, updated_at)
        VALUES (?, ?, ?)
        """,
        (STRICTNESS_SETTING_KEY, json.dumps(default_profile.model_dump()), now_iso),
    )

    _seed_rules(conn)
    seed_examples = config.should_seed_examples() if include_examples is None else include_examples
    if seed_examples:
        _seed_brand_policies(conn, now)
        _seed_products_and_records(conn, now)
    recompute_all_products(conn)
    conn.commit()
