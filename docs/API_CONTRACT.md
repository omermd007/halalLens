# HalalLens Shared API & Data Contract

All backend services, FastAPI routers, and frontend TypeScript clients MUST strictly adhere to these exact field names, enums, and routes.

## 1. Enums (lowercase string values)
- `ProductStatus`:
  - `"certified_halal"`
  - `"verified_plant_or_microbial"`
  - `"mushbooh_needs_check"`
  - `"animal_or_haram"`
  - `"formulation_changed"`
- `IngredientRisk`:
  - `"haram_animal"`
  - `"mushbooh"`
  - `"caution_context"`
  - `"safe"`
- `Determination`:
  - `"plant_or_microbial"`
  - `"synthetic"`
  - `"animal_or_haram"`
  - `"varies_by_supplier"`
  - `"unclear"`
- `EvidenceTier`:
  - `"official_brand_faq"`
  - `"quoted_company_reply"`
  - `"community_anecdote"`
- `RegionFlag`:
  - `"us"`
  - `"non_us_warning"`
  - `"unknown"`
- `FreshnessBucket`:
  - `"recent"` (< 12 months)
  - `"aging"` (12-24 months)
  - `"stale"` (> 24 months)
  - `"unknown"`
- `OutreachState`:
  - `"drafted"`
  - `"sent_by_user"`
  - `"reply_logged"`
  - `"closed"`
- `FlagResolutionStatus`:
  - `"unresolved"`
  - `"verified_plant_or_microbial"`
  - `"verified_brand_policy"`
  - `"resolved_via_vegan"`
  - `"resolved_via_kosher_profile"`
  - `"confirmed_haram"`
  - `"supplier_varies"`
  - `"expired_verification"`
  - `"formulation_changed"`
  - `"informational"`

## 2. Core Models (JSON Shapes)

### `StrictnessProfile`
```json
{
  "preset": "strict",
  "treat_oud_enzymes_as_verified": false,
  "flag_natural_flavors": true,
  "flag_whey_strictly": true,
  "flag_vanilla_ethanol": true
}
```

### `IngredientRule`
```json
{
  "id": "rule_enzymes",
  "canonical_name": "enzymes",
  "aliases": ["enzyme", "microbial enzymes", "animal enzymes", "rennet", "cheese enzymes"],
  "default_risk": "mushbooh",
  "us_context_notes": "In U.S. cheeses and snacks, generic 'enzymes' can be microbial, fermentation-produced chymosin (FPC), or animal rennet (porcine/bovine).",
  "verification_question": "Are the enzymes used in this product 100% microbial/non-animal derived, or are any animal-derived enzymes (porcine/bovine rennet) used?",
  "kosher_vegan_caveat": "OU-D kosher dairy cheeses typically avoid pork rennet, though some kosher agencies permit kosher bovine rennet in select lines; certified vegan rules out animal enzymes.",
  "strictness_key": "oud_enzymes"
}
```

### `IngredientFlag`
```json
{
  "canonical_name": "enzymes",
  "matched_token": "enzymes",
  "parent_context": "cheddar cheese",
  "risk": "mushbooh",
  "resolution_status": "unresolved",
  "resolution_detail": "No active manufacturer verification for this formulation snapshot.",
  "us_context_notes": "...",
  "verification_question": "...",
  "kosher_vegan_caveat": "...",
  "verification_id": null,
  "brand_policy_id": null
}
```

### `FormulationSnapshot`
```json
{
  "id": "snap_123",
  "product_id": "prod_123",
  "raw_ingredients": "ENRICHED MACARONI...",
  "normalized_ingredients": "enriched macaroni...",
  "ingredient_hash": "sha256hex...",
  "source_type": "seed",
  "lot_code": null,
  "plant_code": null,
  "captured_at": "2026-10-01T12:00:00Z",
  "is_current": true
}
```

### `FormulationDiff`
```json
{
  "previous_snapshot_id": "snap_old",
  "previous_captured_at": "2026-01-10T12:00:00Z",
  "added_ingredients": ["mono- and diglycerides", "natural flavors"],
  "removed_ingredients": ["cultured buttermilk"]
}
```

### `CompanyVerification`
```json
{
  "id": "ver_123",
  "product_id": "prod_123",
  "formulation_snapshot_id": "snap_123",
  "ingredient_name": "enzymes",
  "determination": "plant_or_microbial",
  "varies_by_supplier": false,
  "contact_channel": "email",
  "company_contact": "consumer.relations@kraftheinz.com",
  "response_excerpt": "The enzymes used in this product are microbial.",
  "lot_code": null,
  "plant_code": null,
  "verified_date": "2026-09-15",
  "expires_at": "2027-09-15",
  "is_expired": false,
  "matches_current_snapshot": true
}
```

### `BrandPolicy`
```json
{
  "id": "bp_annies",
  "brand": "Annie's",
  "scope_description": "All Annie's mac & cheese and cheddar products use non-animal microbial enzymes.",
  "applies_to_ingredients": ["enzymes", "cheese culture", "whey"],
  "determination": "plant_or_microbial",
  "source_url": "https://www.annies.com/faq",
  "excerpt": "All enzymes used in Annie's cheese products are microbial/vegetarian.",
  "checked_date": "2026-08-01",
  "expires_at": "2027-08-01",
  "is_expired": false
}
```

### `OutreachInquiry`
```json
{
  "id": "out_123",
  "product_id": "prod_123",
  "formulation_snapshot_id": "snap_123",
  "target_email": "consumer.relations@kraftheinz.com",
  "flagged_ingredients": ["enzymes", "cheese culture", "whey"],
  "generated_subject": "Ingredient Source Inquiry: Kraft Original Macaroni & Cheese (UPC 021000658831)",
  "generated_body": "...",
  "mode": "full_inquiry",
  "state": "drafted",
  "created_at": "2026-11-20T15:00:00Z",
  "updated_at": "2026-11-20T15:00:00Z"
}
```

### `ForumSignal`
```json
{
  "id": "fs_123",
  "product_id": "prod_123",
  "source_platform": "reddit",
  "source_name": "r/halal",
  "url": "https://www.reddit.com/r/halal/comments/example",
  "title": "Called Kraft about Original Mac & Cheese enzymes (US)",
  "author": "u/us_halal_shopper",
  "posted_at": "2026-07-18",
  "raw_excerpt": "I emailed Kraft Heinz US customer service last week...",
  "matched_ingredients": ["enzymes", "whey"],
  "claimed_determination": "plant_or_microbial",
  "evidence_tier": "quoted_company_reply",
  "freshness": "recent",
  "region_flag": "us",
  "region_notes": "Mentions U.S. distribution",
  "fetched_at": "2026-11-20T10:00:00Z"
}
```

### `ForumConsensus`
```json
{
  "total_signals": 3,
  "counts_by_determination": {
    "plant_or_microbial": 2,
    "varies_by_supplier": 1,
    "animal_or_haram": 0,
    "unclear": 0
  },
  "quoted_company_replies": 2,
  "official_brand_faqs": 0,
  "has_conflict": true,
  "has_non_us_warning": true,
  "non_us_count": 1,
  "newest_post_date": "2026-09-12",
  "summary_line": "2 report plant/microbial (2 quoted replies), 1 reports varies by supplier • Conflicting reports • 1 non-U.S. thread flagged."
}
```

### `CommunityNote`
```json
{
  "id": "note_123",
  "product_id": "prod_123",
  "author_label": "Personal Note",
  "note_text": "Checked box at Costco Nov 2026; OU-D symbol on top flap.",
  "confidence_tier": "secondary_observation",
  "created_at": "2026-11-18T09:00:00Z"
}
```

### `ProductSummary`
```json
{
  "id": "prod_kraft_mac",
  "upc": "021000658831",
  "name": "Original Macaroni & Cheese Dinner",
  "brand": "Kraft",
  "category": "Mac & Cheese",
  "certifier_name": null,
  "certifier_status": null,
  "kosher_symbol": "OU-D",
  "is_certified_vegan": false,
  "computed_status": "mushbooh_needs_check",
  "unresolved_count": 3,
  "flagged_ingredient_names": ["cheese culture", "enzymes", "whey"],
  "forum_signal_count": 3,
  "has_forum_conflict": true,
  "updated_at": "2026-11-20T12:00:00Z"
}
```

### `ProductDetail`
Extends `ProductSummary` with:
- `brand_contact_email: string | null`
- `brand_contact_url: string | null`
- `status_reasons: string[]`
- `current_snapshot: FormulationSnapshot`
- `previous_snapshot: FormulationSnapshot | null`
- `diff_from_verified: FormulationDiff | null`
- `ingredient_flags: IngredientFlag[]`
- `verifications: CompanyVerification[]`
- `brand_policy: BrandPolicy | null`
- `outreach_inquiries: OutreachInquiry[]`
- `forum_signals: ForumSignal[]`
- `forum_consensus: ForumConsensus`
- `community_notes: CommunityNote[]`

## 3. REST Endpoints

| Method | Path | Request Body / Query | Response Body |
| :--- | :--- | :--- | :--- |
| GET | `/api/health` | — | `{"status": "ok", "db": "ready", "products_count": int}` |
| GET | `/api/products` | `?q=&status=` | `{"products": ProductSummary[]}` |
| GET | `/api/products/{product_id}` | — | `ProductDetail` |
| POST | `/api/products` | `ProductCreateRequest` | `ProductDetail` (201) |
| POST | `/api/scan` | `{"upc": str, "allow_external": bool}` | `{"found": bool, "source": str, "product": ProductDetail \| null, "lookup_trace": [{"tier": str, "status": str, "detail": str}]}` |
| POST | `/api/products/{product_id}/snapshots` | `{"raw_ingredients": str, "source_type": str, "lot_code"?: str, "plant_code"?: str}` | `{"product": ProductDetail, "drift_detected": bool, "added_ingredients": str[], "removed_ingredients": str[]}` |
| POST | `/api/products/{product_id}/notes` | `{"author_label": str, "note_text": str, "confidence_tier"?: str}` | `CommunityNote` (201) |
| POST | `/api/ocr/analyze` | `{"raw_ingredients": str, "product_id"?: str, "save_snapshot"?: bool, "lot_code"?: str, "plant_code"?: str}` | `{"normalized_ingredients": str, "ingredient_hash": str, "parsed_tokens": str[], "flagged_ingredients": IngredientFlag[], "projected_status": ProductStatus, "status_reasons": str[], "drift_detected": bool, "added_ingredients": str[], "removed_ingredients": str[], "updated_product": ProductDetail \| null}` |
| POST | `/api/verifications` | `VerificationCreateRequest` | `ProductDetail` (201) |
| POST | `/api/outreach/draft` | `{"product_id": str, "target_email"?: str, "mode"?: "full_inquiry" \| "quick_confirmation", "reference_forum_signal_id"?: str, "save_draft"?: bool}` | `{"inquiry": OutreachInquiry, "mailto_url": str, "cooldown_warning": {"active": bool, "message": str, "last_contact_at": str, "days_ago": int} \| null, "unresolved_ingredients": str[]}` |
| PATCH | `/api/outreach/{inquiry_id}` | `{"state": OutreachState}` | `OutreachInquiry` |
| POST | `/api/forums/scan/{product_id}` | `{"include_live_reddit"?: bool, "subreddits"?: str[], "custom_query"?: str}` | `{"signals": ForumSignal[], "consensus": ForumConsensus, "sources_checked": [{"source": str, "status": str, "matched_count": int, "detail": str}], "new_signals_added": int}` |
| POST | `/api/forums/parse-post` | `{"product_id"?: str, "source_platform"?: str, "source_name": str, "url"?: str, "title": str, "author"?: str, "posted_at"?: str, "raw_text": str, "save_to_product"?: bool}` | `{"signal": ForumSignal, "consensus": ForumConsensus \| null}` |
| GET | `/api/review-queue` | — | `{"formulation_changed": ProductSummary[], "expiring_or_expired": ProductSummary[], "supplier_variability": ProductSummary[], "mushbooh_unresolved": ProductSummary[], "pending_outreach": OutreachQueueItem[], "counts": {"total_attention": int, "formulation_changed": int, "expiring_or_expired": int, "supplier_variability": int, "mushbooh_unresolved": int, "pending_outreach": int}}` |
| GET | `/api/ingredients` | `?q=` | `{"rules": IngredientRule[]}` |
| GET | `/api/brand-policies` | — | `{"policies": BrandPolicy[]}` |
| POST | `/api/brand-policies` | `BrandPolicyCreateRequest` | `BrandPolicy` (201) |
| GET | `/api/settings/profile` | — | `StrictnessProfile` |
| PUT | `/api/settings/profile` | `StrictnessProfile` | `StrictnessProfile` |
