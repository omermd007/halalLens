export type ProductStatus =
  | 'certified_halal'
  | 'verified_plant_or_microbial'
  | 'mushbooh_needs_check'
  | 'animal_or_haram'
  | 'formulation_changed';

export type IngredientRisk = 'haram_animal' | 'mushbooh' | 'caution_context' | 'safe';

export type Determination =
  | 'plant_or_microbial'
  | 'synthetic'
  | 'animal_or_haram'
  | 'varies_by_supplier'
  | 'unclear';

export type EvidenceTier =
  | 'official_brand_faq'
  | 'quoted_company_reply'
  | 'community_anecdote';

export type RegionFlag = 'us' | 'non_us_warning' | 'unknown';

export type FreshnessBucket = 'recent' | 'aging' | 'stale' | 'unknown';

export type OutreachState = 'drafted' | 'sent_by_user' | 'reply_logged' | 'closed';

export type FlagResolutionStatus =
  | 'unresolved'
  | 'verified_plant_or_microbial'
  | 'verified_brand_policy'
  | 'resolved_via_vegan'
  | 'resolved_via_kosher_profile'
  | 'confirmed_haram'
  | 'supplier_varies'
  | 'expired_verification'
  | 'formulation_changed'
  | 'informational';

export type OutreachMode = 'full_inquiry' | 'quick_confirmation';

export type ActiveTab = 'scan' | 'ocr' | 'queue' | 'guide';

export interface StrictnessProfile {
  preset: 'strict' | 'balanced' | 'custom' | string;
  treat_oud_enzymes_as_verified: boolean;
  flag_natural_flavors: boolean;
  flag_whey_strictly: boolean;
  flag_vanilla_ethanol: boolean;
}

export interface IngredientRule {
  id: string;
  canonical_name: string;
  aliases: string[];
  default_risk: IngredientRisk;
  us_context_notes: string;
  verification_question: string;
  kosher_vegan_caveat: string;
  strictness_key: string | null;
}

export interface IngredientFlag {
  canonical_name: string;
  matched_token: string;
  parent_context: string | null;
  risk: IngredientRisk;
  resolution_status: FlagResolutionStatus;
  resolution_detail: string;
  us_context_notes: string;
  verification_question: string;
  kosher_vegan_caveat: string;
  verification_id: string | null;
  brand_policy_id: string | null;
}

export interface FormulationSnapshot {
  id: string;
  product_id: string;
  raw_ingredients: string;
  normalized_ingredients: string;
  ingredient_hash: string;
  source_type: string;
  lot_code: string | null;
  plant_code: string | null;
  captured_at: string;
  is_current: boolean;
}

export interface FormulationDiff {
  previous_snapshot_id: string;
  previous_captured_at: string;
  added_ingredients: string[];
  removed_ingredients: string[];
}

export interface CompanyVerification {
  id: string;
  product_id: string;
  formulation_snapshot_id: string;
  ingredient_name: string;
  determination: Determination;
  varies_by_supplier: boolean;
  contact_channel: string;
  company_contact: string | null;
  response_excerpt: string;
  lot_code: string | null;
  plant_code: string | null;
  verified_date: string;
  expires_at: string | null;
  is_expired: boolean;
  matches_current_snapshot: boolean;
}

export interface BrandPolicy {
  id: string;
  brand: string;
  scope_description: string;
  applies_to_ingredients: string[];
  determination: Determination;
  source_url: string | null;
  excerpt: string;
  checked_date: string;
  expires_at: string | null;
  is_expired: boolean;
}

export interface OutreachInquiry {
  id: string;
  product_id: string;
  formulation_snapshot_id: string;
  target_email: string | null;
  flagged_ingredients: string[];
  generated_subject: string;
  generated_body: string;
  mode: OutreachMode | string;
  state: OutreachState;
  created_at: string;
  updated_at: string;
}

export interface ForumSignal {
  id: string;
  product_id: string | null;
  source_platform: string;
  source_name: string;
  url: string | null;
  title: string;
  author: string | null;
  posted_at: string | null;
  raw_excerpt: string;
  matched_ingredients: string[];
  claimed_determination: Determination;
  evidence_tier: EvidenceTier;
  freshness: FreshnessBucket;
  region_flag: RegionFlag;
  region_notes: string | null;
  fetched_at: string;
}

export interface ForumConsensus {
  total_signals: number;
  counts_by_determination: Record<string, number>;
  quoted_company_replies: number;
  official_brand_faqs: number;
  has_conflict: boolean;
  has_non_us_warning: boolean;
  non_us_count: number;
  newest_post_date: string | null;
  summary_line: string;
}

export interface CommunityNote {
  id: string;
  product_id: string;
  author_label: string;
  note_text: string;
  confidence_tier: string;
  created_at: string;
}

export interface ProductSummary {
  id: string;
  upc: string | null;
  name: string;
  brand: string;
  category: string | null;
  certifier_name: string | null;
  certifier_status: string | null;
  kosher_symbol: string | null;
  is_certified_vegan: boolean;
  computed_status: ProductStatus;
  unresolved_count: number;
  flagged_ingredient_names: string[];
  forum_signal_count: number;
  has_forum_conflict: boolean;
  updated_at: string;
}

export interface ProductDetail extends ProductSummary {
  brand_contact_email: string | null;
  brand_contact_url: string | null;
  status_reasons: string[];
  current_snapshot: FormulationSnapshot;
  previous_snapshot: FormulationSnapshot | null;
  diff_from_verified: FormulationDiff | null;
  ingredient_flags: IngredientFlag[];
  verifications: CompanyVerification[];
  brand_policy: BrandPolicy | null;
  outreach_inquiries: OutreachInquiry[];
  forum_signals: ForumSignal[];
  forum_consensus: ForumConsensus;
  community_notes: CommunityNote[];
}

export interface LookupTraceStep {
  tier: string;
  status: string;
  detail: string;
}

export interface ScanResponse {
  found: boolean;
  source: string;
  product: ProductDetail | null;
  lookup_trace: LookupTraceStep[];
}

export interface SnapshotCreateRequest {
  raw_ingredients: string;
  source_type: string;
  lot_code?: string | null;
  plant_code?: string | null;
}

export interface SnapshotCreateResponse {
  product: ProductDetail;
  drift_detected: boolean;
  added_ingredients: string[];
  removed_ingredients: string[];
}

export interface ProductCreateRequest {
  upc: string;
  name: string;
  brand: string;
  category: string;
  raw_ingredients: string;
  certifier_name?: string | null;
  certifier_status?: string | null;
  kosher_symbol?: string | null;
  is_certified_vegan?: boolean;
  brand_contact_email?: string | null;
  brand_contact_url?: string | null;
  lot_code?: string | null;
  plant_code?: string | null;
}

export interface NoteCreateRequest {
  author_label: string;
  note_text: string;
  confidence_tier?: string;
}

export interface OcrAnalyzeRequest {
  raw_ingredients: string;
  product_id?: string | null;
  save_snapshot?: boolean;
  lot_code?: string | null;
  plant_code?: string | null;
}

export interface OcrAnalyzeResponse {
  normalized_ingredients: string;
  ingredient_hash: string;
  parsed_tokens: string[];
  flagged_ingredients: IngredientFlag[];
  projected_status: ProductStatus;
  status_reasons: string[];
  drift_detected: boolean;
  added_ingredients: string[];
  removed_ingredients: string[];
  updated_product: ProductDetail | null;
}

export interface VerificationCreateRequest {
  product_id: string;
  formulation_snapshot_id?: string | null;
  ingredient_name: string;
  determination: Determination;
  varies_by_supplier: boolean;
  contact_channel: string;
  company_contact?: string | null;
  response_excerpt: string;
  verified_date?: string | null;
  expires_at?: string | null;
  lot_code?: string | null;
  plant_code?: string | null;
  outreach_inquiry_id?: string | null;
}

export interface CooldownWarning {
  active: boolean;
  message: string;
  last_contact_at: string;
  days_ago: number;
}

export interface OutreachDraftRequest {
  product_id: string;
  target_email?: string;
  mode?: OutreachMode;
  reference_forum_signal_id?: string | null;
  save_draft?: boolean;
}

export interface OutreachDraftResponse {
  inquiry: OutreachInquiry;
  mailto_url: string;
  cooldown_warning: CooldownWarning | null;
  unresolved_ingredients: string[];
}

export interface ForumSourceCheck {
  source: string;
  status: string;
  matched_count: number;
  detail: string;
}

export interface ForumScanRequest {
  include_live_reddit?: boolean;
  subreddits?: string[];
  custom_query?: string;
}

export interface ForumScanResponse {
  signals: ForumSignal[];
  consensus: ForumConsensus;
  sources_checked: ForumSourceCheck[];
  new_signals_added: number;
}

export interface ForumParsePostRequest {
  product_id?: string | null;
  source_platform?: string;
  source_name: string;
  url?: string | null;
  title: string;
  author?: string | null;
  posted_at?: string | null;
  raw_text: string;
  save_to_product?: boolean;
}

export interface ForumParsePostResponse {
  signal: ForumSignal;
  consensus: ForumConsensus | null;
}

export interface OutreachQueueItem extends OutreachInquiry {
  product_name: string;
  brand: string;
  upc: string | null;
  computed_status: ProductStatus;
  days_since_update: number;
}

export interface ReviewQueueCounts {
  total_attention: number;
  formulation_changed: number;
  expiring_or_expired: number;
  supplier_variability: number;
  mushbooh_unresolved: number;
  pending_outreach: number;
}

export interface ReviewQueueResponse {
  formulation_changed: ProductSummary[];
  expiring_or_expired: ProductSummary[];
  supplier_variability: ProductSummary[];
  mushbooh_unresolved: ProductSummary[];
  pending_outreach: OutreachQueueItem[];
  counts: ReviewQueueCounts;
}

export interface BrandPolicyCreateRequest {
  brand: string;
  scope_description: string;
  applies_to_ingredients: string[];
  determination: Determination;
  source_url?: string | null;
  excerpt: string;
  checked_date?: string | null;
  expires_at?: string | null;
}

export interface HealthResponse {
  status: string;
  db: string;
  products_count: number;
}
