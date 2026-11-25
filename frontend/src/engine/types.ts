export type StatusKey =
  | 'certified_halal'
  | 'verified_plant_or_microbial'
  | 'mushbooh_needs_check'
  | 'formulation_changed'
  | 'animal_or_haram';

export type Tone = 'halal' | 'ok' | 'doubt' | 'changed' | 'haram' | 'neutral';

export type ResolutionKey =
  | 'haram'
  | 'unresolved'
  | 'varies'
  | 'expired'
  | 'recheck'
  | 'verified'
  | 'label'
  | 'vegan'
  | 'policy'
  | 'kosher'
  | 'cert'
  | 'info';

export type RuleRisk = 'haram' | 'meat' | 'mushbooh';

export interface IngredientRuleDef {
  id: string;
  name: string;
  risk: RuleRisk;
  strict?: 'oud' | 'whey' | 'nf' | 'ethanol';
  aliases: string[];
  aliasCanon: string[];
  exclude?: RegExp;
  plain: string;
  context: string;
  kosher: string;
  question: string;
}

export interface ProductSnapshot {
  id: string;
  raw_ingredients: string;
  source_type: string;
  lot_code: string | null;
  plant_code: string | null;
  captured_at: string;
  is_current: boolean;
}

export type Determination =
  | 'plant_or_microbial'
  | 'varies_by_supplier'
  | 'animal_or_haram'
  | 'halal_slaughter'
  | 'unclear';

export interface ProductVerification {
  id: string;
  snap: string;
  ingredient: string;
  determination: Determination;
  varies: boolean;
  channel: string;
  contact: string;
  excerpt: string;
  lot_code?: string | null;
  date: string;
  expires: string | null;
}

export interface OutreachItem {
  id: string;
  snap: string;
  to: string;
  subject: string;
  body: string;
  mode: 'full' | 'quick';
  state: 'drafted' | 'sent' | 'replied';
  created_at: string;
}

export interface ForumSignalItem {
  id: string;
  platform: string;
  source: string;
  url: string | null;
  title: string;
  author: string | null;
  posted_at: string;
  excerpt: string;
  ingredients: string[];
  determination: Determination;
  tier: 'official_brand_faq' | 'quoted_company_reply' | 'community_anecdote';
  region: 'us' | 'non_us' | 'unknown';
  region_notes: string | null;
}

export interface ProductNote {
  id: string;
  text: string;
  at: string;
}

export interface ProductRecord {
  id: string;
  upc: string;
  name: string;
  brand: string;
  category: string;
  cert: string | null;
  kosher: string | null;
  vegan: boolean;
  email: string;
  contact_url: string;
  is_example?: boolean;
  source: { kind: string; label: string };
  snapshots: ProductSnapshot[];
  verifications: ProductVerification[];
  outreach: OutreachItem[];
  signals: ForumSignalItem[];
  notes: ProductNote[];
}

export interface BrandPolicyRecord {
  id: string;
  brand: string;
  scope: string;
  ingredients: string[];
  determination: Determination;
  source_url: string;
  excerpt: string;
  checked_date: string;
  expires_at: string;
}

export interface StrictnessSettings {
  preset: 'strict' | 'balanced';
  oud: boolean;
  whey: boolean;
  nf: boolean;
  ethanol: boolean;
}

export interface RuleMatch {
  rule: IngredientRuleDef;
  risk: RuleRisk;
  token: string;
  parent: string | null;
  aliases: string[];
  safe: boolean;
}

export interface FlagEvaluation extends RuleMatch {
  id: string;
  res: ResolutionKey;
  detail: string;
  tone: Tone;
}

export interface RecipeDiff {
  since: string;
  verified: string;
  oldFp: string;
  added: string[];
  removed: string[];
}

export interface ConsensusSummary {
  total: number;
  counts: Record<Determination, number>;
  quoted: number;
  faq: number;
  nonUs: number;
  conflict: boolean;
  line: string;
}

export interface ProductEvaluation {
  p: ProductRecord;
  cur: ProductSnapshot | undefined;
  raw: string;
  fp: string | null;
  flags: FlagEvaluation[];
  status: StatusKey;
  summary: string;
  diff: RecipeDiff | null;
  policy: BrandPolicyRecord | null;
  unresolvedFlags: FlagEvaluation[];
  consensus: ConsensusSummary;
}

export interface HistoryItem {
  id: string;
  upc: string;
  name: string;
  brand: string;
  at: string;
}

export interface LookupStep {
  label: string;
  detail: string;
  state: 'wait' | 'run' | 'hit' | 'miss' | 'blocked';
}

export interface LookupTrace {
  digits: string;
  steps: LookupStep[];
  notFound?: boolean;
}

export interface OffCacheItem {
  upc: string;
  name: string;
  brand: string;
  category: string;
  ingredients: string;
  vegan?: boolean;
  halal?: boolean;
  kosher?: string | null;
}

export type ViewName = 'scan' | 'product' | 'label' | 'todo' | 'learn';

export type AppMode = 'standalone' | 'api';

export type BrandContactType = 'email' | 'web_form';

export interface BrandDirectoryEntry {
  brand: string;
  aliases: string[];
  contact_type: BrandContactType;
  email: string | null;
  contact_url: string;
  phone?: string | null;
}

export interface SavedBrandContact {
  brand: string;
  email: string;
  contact_url: string;
  phone?: string | null;
  updated_at: string;
}

export interface ResolvedBrandContact {
  brand: string;
  source: 'saved' | 'directory' | 'product' | 'unknown';
  contact_type: BrandContactType | 'unknown';
  email: string;
  contact_url: string;
  phone: string | null;
  matchedParent: string | null;
}

export interface BrandContactLookupResult {
  brand: string;
  matched_query: string;
  source: 'verified_directory' | 'web_lookup' | 'not_found';
  verified: boolean;
  contact_type: BrandContactType | 'unknown';
  email: string | null;
  contact_url: string | null;
  phone: string | null;
  search_url: string;
  note: string | null;
}

