"""Pydantic v2 models and enums strictly matching docs/API_CONTRACT.md."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# 1. Enums (lowercase string values)
# ---------------------------------------------------------------------------


class ProductStatus(str, Enum):
    certified_halal = "certified_halal"
    verified_plant_or_microbial = "verified_plant_or_microbial"
    mushbooh_needs_check = "mushbooh_needs_check"
    animal_or_haram = "animal_or_haram"
    formulation_changed = "formulation_changed"


class IngredientRisk(str, Enum):
    haram_animal = "haram_animal"
    mushbooh = "mushbooh"
    caution_context = "caution_context"
    safe = "safe"


class Determination(str, Enum):
    plant_or_microbial = "plant_or_microbial"
    synthetic = "synthetic"
    animal_or_haram = "animal_or_haram"
    varies_by_supplier = "varies_by_supplier"
    unclear = "unclear"


class EvidenceTier(str, Enum):
    official_brand_faq = "official_brand_faq"
    quoted_company_reply = "quoted_company_reply"
    community_anecdote = "community_anecdote"


class RegionFlag(str, Enum):
    us = "us"
    non_us_warning = "non_us_warning"
    unknown = "unknown"


class FreshnessBucket(str, Enum):
    recent = "recent"
    aging = "aging"
    stale = "stale"
    unknown = "unknown"


class OutreachState(str, Enum):
    drafted = "drafted"
    sent_by_user = "sent_by_user"
    reply_logged = "reply_logged"
    closed = "closed"


class FlagResolutionStatus(str, Enum):
    unresolved = "unresolved"
    verified_plant_or_microbial = "verified_plant_or_microbial"
    verified_brand_policy = "verified_brand_policy"
    resolved_via_vegan = "resolved_via_vegan"
    resolved_via_kosher_profile = "resolved_via_kosher_profile"
    confirmed_haram = "confirmed_haram"
    supplier_varies = "supplier_varies"
    expired_verification = "expired_verification"
    formulation_changed = "formulation_changed"
    informational = "informational"


# ---------------------------------------------------------------------------
# 2. Core Domain Models
# ---------------------------------------------------------------------------


class StrictnessProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    preset: str = "strict"
    treat_oud_enzymes_as_verified: bool = False
    flag_natural_flavors: bool = True
    flag_whey_strictly: bool = True
    flag_vanilla_ethanol: bool = True


class IngredientRule(BaseModel):
    id: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    default_risk: IngredientRisk
    us_context_notes: str
    verification_question: str
    kosher_vegan_caveat: str
    strictness_key: str | None = None


class IngredientFlag(BaseModel):
    canonical_name: str
    matched_token: str
    parent_context: str | None = None
    risk: IngredientRisk
    resolution_status: FlagResolutionStatus
    resolution_detail: str
    us_context_notes: str
    verification_question: str
    kosher_vegan_caveat: str
    verification_id: str | None = None
    brand_policy_id: str | None = None


class FormulationSnapshot(BaseModel):
    id: str
    product_id: str
    raw_ingredients: str
    normalized_ingredients: str
    ingredient_hash: str
    source_type: str
    lot_code: str | None = None
    plant_code: str | None = None
    captured_at: str
    is_current: bool


class FormulationDiff(BaseModel):
    previous_snapshot_id: str
    previous_captured_at: str
    added_ingredients: list[str] = Field(default_factory=list)
    removed_ingredients: list[str] = Field(default_factory=list)


class CompanyVerification(BaseModel):
    id: str
    product_id: str
    formulation_snapshot_id: str
    ingredient_name: str
    determination: Determination
    varies_by_supplier: bool = False
    contact_channel: str
    company_contact: str | None = None
    response_excerpt: str
    lot_code: str | None = None
    plant_code: str | None = None
    verified_date: str
    expires_at: str | None = None
    is_expired: bool = False
    matches_current_snapshot: bool = True


class BrandPolicy(BaseModel):
    id: str
    brand: str
    scope_description: str
    applies_to_ingredients: list[str] = Field(default_factory=list)
    determination: Determination
    source_url: str | None = None
    excerpt: str
    checked_date: str
    expires_at: str | None = None
    is_expired: bool = False


class OutreachInquiry(BaseModel):
    id: str
    product_id: str
    formulation_snapshot_id: str
    target_email: str | None = None
    flagged_ingredients: list[str] = Field(default_factory=list)
    generated_subject: str
    generated_body: str
    mode: str = "full_inquiry"
    state: OutreachState = OutreachState.drafted
    created_at: str
    updated_at: str


class ForumSignal(BaseModel):
    id: str
    product_id: str | None = None
    source_platform: str
    source_name: str
    url: str | None = None
    title: str
    author: str | None = None
    posted_at: str | None = None
    raw_excerpt: str
    matched_ingredients: list[str] = Field(default_factory=list)
    claimed_determination: Determination
    evidence_tier: EvidenceTier
    freshness: FreshnessBucket
    region_flag: RegionFlag
    region_notes: str | None = None
    fetched_at: str


class ForumConsensus(BaseModel):
    total_signals: int = 0
    counts_by_determination: dict[str, int] = Field(
        default_factory=lambda: {
            "plant_or_microbial": 0,
            "varies_by_supplier": 0,
            "animal_or_haram": 0,
            "unclear": 0,
        }
    )
    quoted_company_replies: int = 0
    official_brand_faqs: int = 0
    has_conflict: bool = False
    has_non_us_warning: bool = False
    non_us_count: int = 0
    newest_post_date: str | None = None
    summary_line: str = "No community or forum reports logged yet."


class CommunityNote(BaseModel):
    id: str
    product_id: str
    author_label: str
    note_text: str
    confidence_tier: str = "secondary_observation"
    created_at: str


class ProductSummary(BaseModel):
    id: str
    upc: str | None = None
    name: str
    brand: str
    category: str | None = None
    certifier_name: str | None = None
    certifier_status: str | None = None
    kosher_symbol: str | None = None
    is_certified_vegan: bool = False
    computed_status: ProductStatus
    unresolved_count: int = 0
    flagged_ingredient_names: list[str] = Field(default_factory=list)
    forum_signal_count: int = 0
    has_forum_conflict: bool = False
    updated_at: str


class ProductDetail(ProductSummary):
    brand_contact_email: str | None = None
    brand_contact_url: str | None = None
    status_reasons: list[str] = Field(default_factory=list)
    current_snapshot: FormulationSnapshot
    previous_snapshot: FormulationSnapshot | None = None
    diff_from_verified: FormulationDiff | None = None
    ingredient_flags: list[IngredientFlag] = Field(default_factory=list)
    verifications: list[CompanyVerification] = Field(default_factory=list)
    brand_policy: BrandPolicy | None = None
    outreach_inquiries: list[OutreachInquiry] = Field(default_factory=list)
    forum_signals: list[ForumSignal] = Field(default_factory=list)
    forum_consensus: ForumConsensus
    community_notes: list[CommunityNote] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3. REST Request & Response Models
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str = "ok"
    db: str = "ready"
    products_count: int = 0


class ProductListResponse(BaseModel):
    products: list[ProductSummary] = Field(default_factory=list)


class ProductCreateRequest(BaseModel):
    upc: str | None = None
    name: str
    brand: str
    category: str | None = None
    raw_ingredients: str
    source_type: str = "manual"
    certifier_name: str | None = None
    certifier_status: str | None = None
    kosher_symbol: str | None = None
    is_certified_vegan: bool = False
    brand_contact_email: str | None = None
    brand_contact_url: str | None = None
    lot_code: str | None = None
    plant_code: str | None = None


class ScanRequest(BaseModel):
    upc: str
    allow_external: bool = True


class LookupTraceItem(BaseModel):
    tier: str
    status: str
    detail: str


class ScanResponse(BaseModel):
    found: bool
    source: str
    product: ProductDetail | None = None
    lookup_trace: list[LookupTraceItem] = Field(default_factory=list)


class SnapshotCreateRequest(BaseModel):
    raw_ingredients: str
    source_type: str = "manual"
    lot_code: str | None = None
    plant_code: str | None = None


class SnapshotCreateResponse(BaseModel):
    product: ProductDetail
    drift_detected: bool
    added_ingredients: list[str] = Field(default_factory=list)
    removed_ingredients: list[str] = Field(default_factory=list)


class CommunityNoteCreateRequest(BaseModel):
    author_label: str = "Personal Note"
    note_text: str
    confidence_tier: str = "secondary_observation"


class OcrAnalyzeRequest(BaseModel):
    raw_ingredients: str
    product_id: str | None = None
    save_snapshot: bool = False
    lot_code: str | None = None
    plant_code: str | None = None


class OcrAnalyzeResponse(BaseModel):
    normalized_ingredients: str
    ingredient_hash: str
    parsed_tokens: list[str] = Field(default_factory=list)
    flagged_ingredients: list[IngredientFlag] = Field(default_factory=list)
    projected_status: ProductStatus
    status_reasons: list[str] = Field(default_factory=list)
    drift_detected: bool = False
    added_ingredients: list[str] = Field(default_factory=list)
    removed_ingredients: list[str] = Field(default_factory=list)
    updated_product: ProductDetail | None = None


class VerificationCreateRequest(BaseModel):
    product_id: str
    formulation_snapshot_id: str | None = None
    ingredient_name: str
    determination: Determination
    varies_by_supplier: bool = False
    contact_channel: str = "email"
    company_contact: str | None = None
    response_excerpt: str
    lot_code: str | None = None
    plant_code: str | None = None
    verified_date: str | None = None
    expires_at: str | None = None
    outreach_inquiry_id: str | None = None


class OutreachDraftRequest(BaseModel):
    product_id: str
    target_email: str | None = None
    mode: Literal["full_inquiry", "quick_confirmation"] = "full_inquiry"
    reference_forum_signal_id: str | None = None
    save_draft: bool = True


class CooldownWarning(BaseModel):
    active: bool
    message: str
    last_contact_at: str
    days_ago: int


class OutreachDraftResponse(BaseModel):
    inquiry: OutreachInquiry
    mailto_url: str
    cooldown_warning: CooldownWarning | None = None
    unresolved_ingredients: list[str] = Field(default_factory=list)


class OutreachUpdateRequest(BaseModel):
    state: OutreachState


class ForumScanRequest(BaseModel):
    include_live_reddit: bool = False
    subreddits: list[str] | None = None
    custom_query: str | None = None


class ForumSourceCheck(BaseModel):
    source: str
    status: str
    matched_count: int = 0
    detail: str


class ForumScanResponse(BaseModel):
    signals: list[ForumSignal] = Field(default_factory=list)
    consensus: ForumConsensus
    sources_checked: list[ForumSourceCheck] = Field(default_factory=list)
    new_signals_added: int = 0


class ForumParsePostRequest(BaseModel):
    product_id: str | None = None
    source_platform: str = "forum"
    source_name: str
    url: str | None = None
    title: str
    author: str | None = None
    posted_at: str | None = None
    raw_text: str
    save_to_product: bool = False


class ForumParsePostResponse(BaseModel):
    signal: ForumSignal
    consensus: ForumConsensus | None = None


class OutreachQueueItem(OutreachInquiry):
    product_name: str
    brand: str
    upc: str | None = None
    computed_status: ProductStatus
    days_since_update: int = 0


class ReviewQueueCounts(BaseModel):
    total_attention: int = 0
    formulation_changed: int = 0
    expiring_or_expired: int = 0
    supplier_variability: int = 0
    mushbooh_unresolved: int = 0
    pending_outreach: int = 0


class ReviewQueueResponse(BaseModel):
    formulation_changed: list[ProductSummary] = Field(default_factory=list)
    expiring_or_expired: list[ProductSummary] = Field(default_factory=list)
    supplier_variability: list[ProductSummary] = Field(default_factory=list)
    mushbooh_unresolved: list[ProductSummary] = Field(default_factory=list)
    pending_outreach: list[OutreachQueueItem] = Field(default_factory=list)
    counts: ReviewQueueCounts


class IngredientRuleListResponse(BaseModel):
    rules: list[IngredientRule] = Field(default_factory=list)


class BrandPolicyListResponse(BaseModel):
    policies: list[BrandPolicy] = Field(default_factory=list)


class BrandPolicyCreateRequest(BaseModel):
    brand: str
    scope_description: str
    applies_to_ingredients: list[str] = Field(default_factory=list)
    determination: Determination
    source_url: str | None = None
    excerpt: str
    checked_date: str | None = None
    expires_at: str | None = None
