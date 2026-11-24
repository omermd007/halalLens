"""Unit tests for deterministic ingredient normalization, parsing, rule matching, and diffing."""

from __future__ import annotations

from app import db
from app.services.ingredient_parser import (
    compute_ingredient_diff,
    compute_ingredient_hash,
    match_ingredient_rules,
    normalize_ingredients,
    parse_ingredient_tokens,
)


def test_normalization_and_hash_stability() -> None:
    raw_a = "INGREDIENTS: Enriched Flour [Wheat Flour, Niacin*], Cheddar Cheese (Milk, Enzymes)."
    raw_b = "  ingredients - enriched flour (wheat flour, niacin), cheddar cheese (milk, enzymes)  "

    norm_a = normalize_ingredients(raw_a)
    norm_b = normalize_ingredients(raw_b)

    assert norm_a == norm_b
    assert norm_a == "enriched flour (wheat flour, niacin), cheddar cheese (milk, enzymes)"
    assert compute_ingredient_hash(raw_a) == compute_ingredient_hash(raw_b)
    assert len(compute_ingredient_hash(raw_a)) == 64


def test_parenthetical_nesting_and_allergen_footer_skip(seeded_conn) -> None:
    raw = (
        "INGREDIENTS: PASTA (WHEAT FLOUR), "
        "CHEESE SAUCE (CHEDDAR CHEESE (PASTEURIZED MILK, CHEESE CULTURE, SALT, ENZYMES), "
        "CONTAINS LESS THAN 2% OF WHEY, NATURAL FLAVORS). "
        "CONTAINS: MILK."
    )
    tokens = parse_ingredient_tokens(raw)
    token_map = {t["token"]: t for t in tokens}

    assert "enzymes" in token_map
    assert token_map["enzymes"]["parent_context"] == "cheddar cheese"
    assert token_map["enzymes"]["depth"] == 2
    assert "cheese culture" in token_map
    assert token_map["cheese culture"]["parent_context"] == "cheddar cheese"
    assert "whey" in token_map
    assert token_map["whey"]["parent_context"] == "cheese sauce"
    assert "natural flavors" in token_map
    # FDA allergen declaration footer ("CONTAINS: MILK") is skipped.
    assert not any("contains:" in t["token"] or t["token"] == "milk" for t in tokens)

    # Colon variant ("CONTAINS LESS THAN 2% OF: WHEY") still matches whey rule reliably.
    rules = db.fetch_all_ingredient_rules(seeded_conn)
    colon_matches = {
        m["canonical_name"]
        for m in match_ingredient_rules("CONTAINS LESS THAN 2% OF: WHEY, NATURAL FLAVORS.", rules)
    }
    assert {"whey", "natural flavors"}.issubset(colon_matches)


def test_compound_tokens_and_inline_qualifiers(seeded_conn) -> None:
    rules = db.fetch_all_ingredient_rules(seeded_conn)
    raw = (
        "WHEAT FLOUR, MONO- AND DIGLYCERIDES, SODIUM STEAROYL LACTYLATE, "
        "VITAMIN D3 (CHOLECALCIFEROL), CONFECTIONER'S GLAZE, L-CYSTEINE."
    )
    matches = match_ingredient_rules(raw, rules)
    matched_names = {m["canonical_name"] for m in matches}

    assert "mono- and diglycerides" in matched_names
    assert "sodium stearoyl lactylate" in matched_names
    assert "vitamin D3" in matched_names
    assert "confectioner's glaze" in matched_names
    assert "L-cysteine" in matched_names


def test_explicit_label_qualifiers_mark_mushbooh_safe_but_never_haram(seeded_conn) -> None:
    rules = db.fetch_all_ingredient_rules(seeded_conn)
    raw = (
        "MILK, MICROBIAL ENZYMES, VEGETABLE MONO- AND DIGLYCERIDES, "
        "KOSHER FISH GELATIN, ALCOHOL-FREE VANILLA EXTRACT, PLANT-DERIVED GLYCERIN."
    )
    matches = {m["canonical_name"]: m for m in match_ingredient_rules(raw, rules)}

    assert matches["enzymes"]["explicit_label_safe"] is True
    assert matches["mono- and diglycerides"]["explicit_label_safe"] is True
    assert matches["gelatin"]["explicit_label_safe"] is True
    assert matches["vanilla extract"]["explicit_label_safe"] is True
    assert matches["glycerin"]["explicit_label_safe"] is True

    # Animal/porcine cues must NEVER be marked safe, and porcine gelatin escalates to haram_animal.
    haram_raw = "SUGAR, GELATIN (PORCINE), ANIMAL ENZYMES, CARMINE, LARD."
    haram_matches = {m["canonical_name"]: m for m in match_ingredient_rules(haram_raw, rules)}
    assert "pork gelatin" in haram_matches
    assert "gelatin" not in haram_matches  # suppressed by more specific pork gelatin match
    assert haram_matches["pork gelatin"]["default_risk"] == "haram_animal"
    assert haram_matches["pork gelatin"]["explicit_label_safe"] is False
    assert haram_matches["enzymes"]["explicit_label_safe"] is False
    assert haram_matches["carmine"]["default_risk"] == "haram_animal"
    assert haram_matches["lard"]["default_risk"] == "haram_animal"


def test_unresolved_duplicate_overrides_explicitly_safe_occurrence(seeded_conn) -> None:
    rules = db.fetch_all_ingredient_rules(seeded_conn)
    raw = (
        "CHEDDAR CHEESE (MILK, MICROBIAL ENZYMES), "
        "PARMESAN CHEESE (MILK, SALT, ENZYMES)."
    )
    matches = {m["canonical_name"]: m for m in match_ingredient_rules(raw, rules)}
    assert "enzymes" in matches
    assert matches["enzymes"]["explicit_label_safe"] is False
    assert matches["enzymes"]["matched_token"] == "enzymes"


def test_false_positive_guards(seeded_conn) -> None:
    rules = db.fetch_all_ingredient_rules(seeded_conn)
    raw = (
        "WATER, PREGELATINIZED CORN STARCH, RED WINE VINEGAR, "
        "WHITE WINE VINEGAR, SUGAR ALCOHOL (SORBITOL), STEARYL ALCOHOL, "
        "ALCOHOL-FREE BOTANICAL EXTRACT."
    )
    matches = match_ingredient_rules(raw, rules)
    matched_names = {m["canonical_name"] for m in matches}

    assert "gelatin" not in matched_names
    assert "pork gelatin" not in matched_names
    assert "alcohol / wine" not in matched_names


def test_compute_ingredient_diff() -> None:
    old_raw = (
        "WHEAT FLOUR, CHEDDAR CHEESE (MILK, CHEESE CULTURE, SALT, ENZYMES), "
        "CULTURED BUTTERMILK, WHEY, BUTTER."
    )
    new_raw = (
        "WHEAT FLOUR, CHEDDAR CHEESE (MILK, CHEESE CULTURE, SALT, ENZYMES), "
        "WHEY, BUTTER, MONO- AND DIGLYCERIDES, NATURAL FLAVORS."
    )

    added, removed = compute_ingredient_diff(old_raw, new_raw)
    assert added == ["mono- and diglycerides", "natural flavors"]
    assert removed == ["cultured buttermilk"]

    # Whitespace/case differences produce empty diff.
    same_added, same_removed = compute_ingredient_diff(old_raw, old_raw.lower() + "  ")
    assert same_added == []
    assert same_removed == []
