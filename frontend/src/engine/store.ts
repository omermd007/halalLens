import brandContactsRaw from '../data/brandContacts.json';
import offCacheRaw from '../data/offCache.json';
import { digitsOf, parseForumPost, todayISO, uid, upcVariants } from './evaluator';
import { createSeedProducts, DEFAULT_STRICT, SEED_POLICIES } from './seeds';
import type {
  AppMode,
  BrandContactLookupResult,
  BrandDirectoryEntry,
  BrandPolicyRecord,
  ForumSignalItem,
  HistoryItem,
  LookupStep,
  OffCacheItem,
  ProductRecord,
  ResolvedBrandContact,
  SavedBrandContact,
  StrictnessSettings,
} from './types';

export const OFF_CACHE: OffCacheItem[] = offCacheRaw as OffCacheItem[];
export const CACHE_COUNT = OFF_CACHE.length;

export const BRAND_CONTACTS_DIRECTORY: BrandDirectoryEntry[] =
  brandContactsRaw as BrandDirectoryEntry[];

const CACHE_INDEX = new Map<string, OffCacheItem>();
for (const item of OFF_CACHE) {
  for (const variant of upcVariants(item.upc)) {
    CACHE_INDEX.set(variant, item);
  }
}

export const STORE_KEY = 'halallens.v4';
const PASSCODE_SESSION_KEY = 'halallens.passcode';

export function normalizeBrandKey(brand: string): string {
  if (!brand) return '';
  return brand
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/['’`]/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

export function isPlaceholderEmail(email: string | null | undefined): boolean {
  if (!email) return false;
  const low = email.trim().toLowerCase();
  if (!low) return false;
  const at = low.lastIndexOf('@');
  if (at < 0) return false;
  const domain = low.slice(at + 1);
  return (
    domain === 'example.com' ||
    domain.endsWith('.example.com') ||
    domain === 'example.org' ||
    domain.endsWith('.example.org') ||
    domain === 'example.net' ||
    domain.endsWith('.example.net')
  );
}

export function matchBrandDirectory(brand: string): BrandDirectoryEntry | null {
  const query = normalizeBrandKey(brand);
  if (!query) return null;

  // 1. Exact normalized match against brand or aliases.
  for (const entry of BRAND_CONTACTS_DIRECTORY) {
    const names = [entry.brand, ...(entry.aliases || [])];
    for (const candidate of names) {
      if (normalizeBrandKey(candidate) === query) {
        return entry;
      }
    }
  }

  // 2. Word-boundary match (longest alias wins to avoid false positives).
  let best: BrandDirectoryEntry | null = null;
  let bestScore = 0;
  const paddedQuery = ` ${query} `;
  for (const entry of BRAND_CONTACTS_DIRECTORY) {
    const names = [entry.brand, ...(entry.aliases || [])];
    for (const candidate of names) {
      const norm = normalizeBrandKey(candidate);
      if (!norm || norm.length < 3) continue;
      const paddedCand = ` ${norm} `;
      if (paddedQuery.includes(paddedCand)) {
        const score = norm.length + 100;
        if (score > bestScore) {
          bestScore = score;
          best = entry;
        }
      } else if (query.length >= 4 && paddedCand.includes(paddedQuery)) {
        const score = query.length;
        if (score > bestScore) {
          bestScore = score;
          best = entry;
        }
      }
    }
  }

  return best;
}

export function resolveBrandContact(
  brand: string,
  savedBook: Record<string, SavedBrandContact>,
  productEmail?: string,
  productContactUrl?: string
): ResolvedBrandContact {
  const key = normalizeBrandKey(brand);
  const dirEntry = matchBrandDirectory(brand);
  const parentKey = dirEntry ? normalizeBrandKey(dirEntry.brand) : '';

  const saved = (key && savedBook[key]) || (parentKey && savedBook[parentKey]) || null;
  const savedEmail = saved && !isPlaceholderEmail(saved.email) ? saved.email.trim() : '';
  const savedUrl = saved?.contact_url?.trim() || '';

  if (saved && (savedEmail || savedUrl)) {
    const mergedUrl = savedUrl || dirEntry?.contact_url || (productContactUrl || '').trim();
    const mergedPhone = saved.phone || dirEntry?.phone || null;
    return {
      brand: saved.brand || brand,
      source: 'saved',
      contact_type: savedEmail ? 'email' : 'web_form',
      email: savedEmail,
      contact_url: mergedUrl,
      phone: mergedPhone,
      matchedParent: dirEntry?.brand || null,
    };
  }

  if (dirEntry) {
    const dirEmail = dirEntry.email && !isPlaceholderEmail(dirEntry.email) ? dirEntry.email.trim() : '';
    return {
      brand: dirEntry.brand,
      source: 'directory',
      contact_type: dirEmail ? 'email' : dirEntry.contact_type,
      email: dirEmail,
      contact_url: dirEntry.contact_url || '',
      phone: dirEntry.phone || null,
      matchedParent: dirEntry.brand,
    };
  }

  const cleanProdEmail =
    productEmail && !isPlaceholderEmail(productEmail) ? productEmail.trim() : '';
  const cleanProdUrl = (productContactUrl || '').trim();
  if (cleanProdEmail || cleanProdUrl) {
    return {
      brand,
      source: 'product',
      contact_type: cleanProdEmail ? 'email' : 'web_form',
      email: cleanProdEmail,
      contact_url: cleanProdUrl,
      phone: null,
      matchedParent: null,
    };
  }

  return {
    brand,
    source: 'unknown',
    contact_type: 'unknown',
    email: '',
    contact_url: '',
    phone: null,
    matchedParent: null,
  };
}

export function upsertSavedBrandContact(
  book: Record<string, SavedBrandContact>,
  brand: string,
  contact: { email: string; contact_url: string; phone?: string | null }
): Record<string, SavedBrandContact> {
  const key = normalizeBrandKey(brand);
  if (!key) return book;
  const cleanEmail = isPlaceholderEmail(contact.email) ? '' : contact.email.trim();
  const cleanUrl = contact.contact_url.trim();
  const next = { ...book };
  if (!cleanEmail && !cleanUrl) {
    delete next[key];
    return next;
  }
  next[key] = {
    brand: brand.trim() || book[key]?.brand || brand,
    email: cleanEmail,
    contact_url: cleanUrl,
    phone: contact.phone ?? book[key]?.phone ?? null,
    updated_at: new Date().toISOString(),
  };
  return next;
}

export function buildBrandSearchUrl(brand: string): string {
  const q = `"${brand.trim()}" consumer care OR customer support contact email`;
  return `https://www.google.com/search?q=${encodeURIComponent(q)}`;
}

export const DEFAULT_PROXY_URL = String(import.meta.env.VITE_PROXY_URL || '')
  .trim()
  .replace(/\/+$/, '');

export function normalizeProxyUrl(raw: string | null | undefined): string {
  const trimmed = String(raw || '').trim();
  if (!trimmed) return '';
  const withProto = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  return withProto.replace(/\/+$/, '');
}

export function getEffectiveProxyUrl(savedProxyUrl?: string): string {
  return normalizeProxyUrl(savedProxyUrl) || DEFAULT_PROXY_URL;
}

export async function testProxyConnection(rawUrl: string): Promise<{
  ok: boolean;
  message: string;
}> {
  const base = normalizeProxyUrl(rawUrl);
  if (!base) {
    return { ok: false, message: 'Enter your Cloudflare Worker URL first.' };
  }
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 6000);
    const res = await fetch(`${base}/health`, {
      signal: ctrl.signal,
      headers: { Accept: 'application/json' },
    });
    clearTimeout(timer);
    if (!res.ok) {
      return { ok: false, message: `Worker responded with HTTP ${res.status}.` };
    }
    const data = (await res.json()) as {
      status?: string;
      capabilities?: { brave_search?: boolean; reddit_oauth?: boolean };
    };
    if (data?.status !== 'ok') {
      return { ok: false, message: 'Unexpected response from worker /health endpoint.' };
    }
    const features = [
      data.capabilities?.reddit_oauth ? 'Reddit OAuth' : 'Reddit archive',
      data.capabilities?.brave_search ? 'Brave Web Search' : 'Web & Halal directories',
      'FAQ extraction',
    ];
    return { ok: true, message: `Connected · ${features.join(' + ')} ready.` };
  } catch {
    return {
      ok: false,
      message: 'Could not reach that Worker URL. Check the URL and ALLOWED_ORIGINS.',
    };
  }
}

export async function lookupBrandContactFromApi(
  brand: string,
  options?: { proxyUrl?: string; appMode?: AppMode }
): Promise<BrandContactLookupResult | null> {
  const effectiveProxy = getEffectiveProxyUrl(options?.proxyUrl);
  const endpoint = effectiveProxy
    ? `${effectiveProxy}/brand-contact?brand=${encodeURIComponent(brand.trim())}`
    : options?.appMode === 'api'
      ? `/api/brands/lookup-contact?brand=${encodeURIComponent(brand.trim())}`
      : '';

  if (!endpoint) return null;

  try {
    const passcode = effectiveProxy ? '' : getSavedPasscode();
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    const res = await fetch(endpoint, {
      signal: ctrl.signal,
      headers: {
        Accept: 'application/json',
        ...(passcode ? { 'X-Passcode': passcode } : {}),
      },
    });
    clearTimeout(timer);
    if (!res.ok) return null;
    return (await res.json()) as BrandContactLookupResult;
  } catch {
    return null;
  }
}

function sanitizeProductContacts(products: ProductRecord[]): ProductRecord[] {
  return products.map((p) => {
    const hasPlaceholder = isPlaceholderEmail(p.email);
    const dir = matchBrandDirectory(p.brand);
    const cleanOutreach = Array.isArray(p.outreach)
      ? p.outreach.map((o) =>
          isPlaceholderEmail(o.to) ? { ...o, to: dir?.email || '' } : o
        )
      : [];
    if (!hasPlaceholder && cleanOutreach === p.outreach) return p;
    const nextEmail = hasPlaceholder ? dir?.email || '' : p.email;
    const nextUrl =
      hasPlaceholder && dir?.contact_url ? dir.contact_url : p.contact_url;
    return {
      ...p,
      email: nextEmail,
      contact_url: nextUrl,
      outreach: cleanOutreach,
    };
  });
}

function sanitizeSavedBrandContacts(
  raw: Record<string, SavedBrandContact> | undefined
): Record<string, SavedBrandContact> {
  if (!raw || typeof raw !== 'object') return {};
  const cleaned: Record<string, SavedBrandContact> = {};
  for (const [k, v] of Object.entries(raw)) {
    if (!v || typeof v !== 'object') continue;
    const email = isPlaceholderEmail(v.email) ? '' : String(v.email || '').trim();
    const contact_url = String(v.contact_url || '').trim();
    if (!email && !contact_url) continue;
    cleaned[k] = {
      brand: String(v.brand || k),
      email,
      contact_url,
      phone: v.phone ? String(v.phone) : null,
      updated_at: String(v.updated_at || new Date().toISOString()),
    };
  }
  return cleaned;
}

export interface PersistedState {
  products: ProductRecord[];
  policies: BrandPolicyRecord[];
  brandContacts: Record<string, SavedBrandContact>;
  strict: StrictnessSettings;
  history: HistoryItem[];
  usdaApiKey: string;
  proxyUrl: string;
  showExamples: boolean;
}

export function loadPersistedState(): PersistedState {
  const defaults: PersistedState = {
    products: createSeedProducts(),
    policies: JSON.parse(JSON.stringify(SEED_POLICIES)),
    brandContacts: {},
    strict: { ...DEFAULT_STRICT },
    history: [],
    usdaApiKey: '',
    proxyUrl: DEFAULT_PROXY_URL,
    showExamples: true,
  };
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return defaults;
    const d = JSON.parse(raw) as Partial<PersistedState>;
    return {
      products: Array.isArray(d.products)
        ? sanitizeProductContacts(d.products)
        : defaults.products,
      policies: Array.isArray(d.policies) ? d.policies : defaults.policies,
      brandContacts: sanitizeSavedBrandContacts(d.brandContacts),
      strict: d.strict ? { ...DEFAULT_STRICT, ...d.strict } : defaults.strict,
      history: Array.isArray(d.history) ? d.history : [],
      usdaApiKey: typeof d.usdaApiKey === 'string' ? d.usdaApiKey : '',
      proxyUrl: typeof d.proxyUrl === 'string' ? normalizeProxyUrl(d.proxyUrl) : DEFAULT_PROXY_URL,
      showExamples: typeof d.showExamples === 'boolean' ? d.showExamples : true,
    };
  } catch {
    return defaults;
  }
}

export function savePersistedState(state: PersistedState): void {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(state));
  } catch {
    // ignore quota errors
  }
}

export function getSavedPasscode(): string {
  try {
    return sessionStorage.getItem(PASSCODE_SESSION_KEY) || '';
  } catch {
    return '';
  }
}

export function setSavedPasscode(code: string): void {
  try {
    if (code) sessionStorage.setItem(PASSCODE_SESSION_KEY, code);
    else sessionStorage.removeItem(PASSCODE_SESSION_KEY);
  } catch {
    // ignore
  }
}

export async function detectBackendMode(): Promise<{
  mode: AppMode;
  passcodeRequired: boolean;
  authenticated: boolean;
}> {
  if (import.meta.env.VITE_STANDALONE === 'true') {
    return { mode: 'standalone', passcodeRequired: false, authenticated: true };
  }
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 2200);
    const passcode = getSavedPasscode();
    const res = await fetch('/api/auth/status', {
      signal: ctrl.signal,
      headers: passcode ? { 'X-Passcode': passcode } : {},
    });
    clearTimeout(t);
    if (!res.ok) return { mode: 'standalone', passcodeRequired: false, authenticated: true };
    const data = (await res.json()) as { passcode_required: boolean; authenticated: boolean };
    return {
      mode: 'api',
      passcodeRequired: Boolean(data.passcode_required),
      authenticated: Boolean(data.authenticated),
    };
  } catch {
    return { mode: 'standalone', passcodeRequired: false, authenticated: true };
  }
}

export async function verifyServerPasscode(code: string): Promise<boolean> {
  try {
    const res = await fetch('/api/auth/status', {
      headers: { 'X-Passcode': code },
    });
    if (!res.ok) return false;
    const data = (await res.json()) as { authenticated: boolean };
    if (data.authenticated) setSavedPasscode(code);
    return Boolean(data.authenticated);
  } catch {
    return false;
  }
}

export function pickCacheExamples(count = 6): OffCacheItem[] {
  const preferred = ['0021000612239', '0021000010615', '0898248001428', '0034360006143', '0041757025397', '0077901008569'];
  const picked: OffCacheItem[] = [];
  for (const upc of preferred) {
    const hit = CACHE_INDEX.get(upc);
    if (hit) picked.push(hit);
  }
  for (const item of OFF_CACHE) {
    if (picked.length >= count) break;
    if (!picked.includes(item) && item.name.length <= 42) picked.push(item);
  }
  return picked.slice(0, count);
}

function normKosher(k: string | null | undefined): string | null {
  if (!k) return null;
  const s = String(k).toLowerCase();
  if (s.includes('ou-d') || s.includes('ou d')) return 'OU-D';
  if (s.includes('ou-p') || s.includes('pareve')) return 'OU-Pareve';
  if (s.includes('star-k')) return 'Star-K';
  if (s.includes('kof-k')) return 'KOF-K';
  if (s.includes('ok-d')) return 'OK-D';
  if (s.includes('kosher')) return 'Kosher';
  return k;
}

export function makeProductFromLookup(o: {
  upc: string;
  name: string;
  brand: string;
  category?: string;
  ingredients?: string;
  vegan?: boolean;
  halal?: boolean;
  cert?: string | null;
  kosher?: string | null;
  image_url?: string | null;
  sourceKind: string;
  sourceLabel: string;
  brandContacts?: Record<string, SavedBrandContact>;
}): ProductRecord {
  const sid = uid('s');
  const resolved = resolveBrandContact(o.brand || '', o.brandContacts || {});
  return {
    id: uid('p'),
    upc: o.upc,
    name: o.name || `Product ${o.upc}`,
    brand: o.brand || 'Unknown brand',
    category: o.category || 'Grocery',
    cert: o.cert || (o.halal ? 'Halal label (confirm symbol on package)' : null),
    kosher: normKosher(o.kosher),
    vegan: Boolean(o.vegan),
    email: resolved.email,
    contact_url: resolved.contact_url,
    image_url: o.image_url || null,
    source: { kind: o.sourceKind, label: o.sourceLabel },
    snapshots: [
      {
        id: sid,
        raw_ingredients: o.ingredients || '',
        source_type: o.sourceKind,
        lot_code: null,
        plant_code: null,
        captured_at: new Date().toISOString(),
        is_current: true,
      },
    ],
    verifications: [],
    outreach: [],
    signals: [],
    notes: [],
  };
}

async function fetchJSON(url: string, ms = 7000): Promise<unknown | null> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    clearTimeout(timer);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    clearTimeout(timer);
    throw new Error('offline');
  }
}

function pickOffImageUrl(p: Record<string, unknown>): string | null {
  for (const key of ['image_front_small_url', 'image_thumb_url', 'image_front_url']) {
    const val = p[key];
    if (typeof val === 'string' && val.startsWith('https://')) {
      return val;
    }
  }
  return null;
}

async function liveOFF(digits: string) {
  for (const v of upcVariants(digits)) {
    const d = (await fetchJSON(
      `https://world.openfoodfacts.org/api/v2/product/${encodeURIComponent(v)}.json?fields=code,product_name,brands,categories_tags_en,ingredients_text_en,ingredients_text,labels_tags,image_front_small_url,image_front_url,image_thumb_url`
    )) as { status?: number; product?: Record<string, unknown> } | null;
    if (d && d.status === 1 && d.product) {
      const p = d.product;
      const tags = (Array.isArray(p.labels_tags) ? p.labels_tags : []).map((t) => String(t).toLowerCase());
      const cats = Array.isArray(p.categories_tags_en) ? p.categories_tags_en : [];
      return {
        upc: String(p.code || digits),
        name: String(p.product_name || `Product ${digits}`),
        brand: String(p.brands || 'Unknown brand').split(',')[0].trim(),
        category: String(cats[cats.length - 1] || 'Grocery').replace(/^en:/, '').replace(/-/g, ' '),
        ingredients: String(p.ingredients_text_en || p.ingredients_text || '').trim(),
        vegan: tags.some((t) => t.includes('vegan')),
        halal: tags.some((t) => t.includes('halal')),
        kosher: tags.find((t) => t.includes('kosher'))?.replace(/^en:/, '') || null,
        image_url: pickOffImageUrl(p),
      };
    }
  }
  return null;
}

export async function fetchProductThumbnail(
  upc: string,
  proxyUrl?: string | null
): Promise<string | null> {
  const digits = digitsOf(upc);
  if (digits.length < 8) return null;

  // 1. Direct Open Food Facts thumbnail lookup (free, fast, CORS-friendly)
  for (const v of upcVariants(digits)) {
    try {
      const d = (await fetchJSON(
        `https://world.openfoodfacts.org/api/v2/product/${encodeURIComponent(v)}.json?fields=image_front_small_url,image_front_url,image_thumb_url`,
        5500
      )) as { status?: number; product?: Record<string, unknown> } | null;
      if (d && d.status === 1 && d.product) {
        const img = pickOffImageUrl(d.product);
        if (img) return img;
      }
    } catch {
      break;
    }
  }

  // 2. Cloudflare Worker /product-image fallback (UPCitemdb + 7-day edge cache)
  const effectiveProxy = getEffectiveProxyUrl(proxyUrl ?? undefined);
  if (effectiveProxy) {
    try {
      const d = (await fetchJSON(
        `${effectiveProxy}/product-image?upc=${encodeURIComponent(digits)}`,
        6000
      )) as { image_url?: string | null } | null;
      if (d?.image_url && d.image_url.startsWith('https://')) {
        return d.image_url;
      }
    } catch {
      // ignore
    }
  }

  return null;
}

async function liveUSDA(digits: string, apiKey: string) {
  const key = apiKey.trim() || 'DEMO_KEY';
  const d = (await fetchJSON(
    `https://api.nal.usda.gov/fdc/v1/foods/search?api_key=${encodeURIComponent(key)}&query=${encodeURIComponent(digits)}&dataType=Branded&pageSize=5`
  )) as { foods?: Array<Record<string, unknown>> } | null;
  if (!d || !Array.isArray(d.foods)) return null;
  const variants = new Set(upcVariants(digits));
  const hit = d.foods.find((f) => variants.has(digitsOf(String(f.gtinUpc || ''))));
  if (!hit) return null;
  return {
    upc: String(hit.gtinUpc || digits),
    name: String(hit.description || `Product ${digits}`),
    brand: String(hit.brandName || hit.brandOwner || 'Unknown brand'),
    category: String(hit.foodCategory || 'Grocery'),
    ingredients: String(hit.ingredients || '').trim(),
    vegan: false,
    halal: false,
    kosher: null,
  };
}

export async function runUpcWaterfall(params: {
  rawInput: string;
  products: ProductRecord[];
  brandContacts?: Record<string, SavedBrandContact>;
  usdaApiKey: string;
  onSteps: (steps: LookupStep[]) => void;
}): Promise<{ product: ProductRecord | null; imported: boolean; steps: LookupStep[] }> {
  const digits = digitsOf(params.rawInput);
  const variants = new Set(upcVariants(digits));

  const steps: LookupStep[] = [
    { label: 'Your saved products', detail: 'Checking your list…', state: 'run' },
    { label: `Offline U.S. catalog · ${CACHE_COUNT} real products`, detail: 'Waiting', state: 'wait' },
    { label: 'Open Food Facts · live search', detail: 'Waiting', state: 'wait' },
    { label: 'USDA FoodData Central · live search', detail: 'Waiting', state: 'wait' },
  ];
  const emit = () => params.onSteps(steps.map((s) => ({ ...s })));
  emit();

  // 1. Saved products
  const localHit = params.products.find((p) => upcVariants(p.upc).some((v) => variants.has(v)));
  if (localHit) {
    steps[0] = { ...steps[0], state: 'hit', detail: `Found: ${localHit.brand} ${localHit.name}` };
    emit();
    return { product: localHit, imported: false, steps };
  }
  steps[0] = { ...steps[0], state: 'miss', detail: 'Not saved yet' };
  steps[1] = { ...steps[1], state: 'run', detail: 'Searching offline catalog…' };
  emit();

  // 2. Embedded offline U.S. catalog
  let cacheHit: OffCacheItem | undefined;
  for (const v of variants) {
    if (CACHE_INDEX.has(v)) {
      cacheHit = CACHE_INDEX.get(v);
      break;
    }
  }
  if (cacheHit) {
    const imported = makeProductFromLookup({
      ...cacheHit,
      sourceKind: 'off_cache',
      sourceLabel: 'Open Food Facts (offline U.S. catalog)',
      brandContacts: params.brandContacts,
    });
    steps[1] = { ...steps[1], state: 'hit', detail: `Found: ${imported.brand} ${imported.name}` };
    emit();
    return { product: imported, imported: true, steps };
  }
  steps[1] = { ...steps[1], state: 'miss', detail: 'Not in the offline catalog' };
  steps[2] = { ...steps[2], state: 'run', detail: 'Querying world.openfoodfacts.org…' };
  emit();

  // 3. Live Open Food Facts
  try {
    const hit = await liveOFF(digits);
    if (hit) {
      const imported = makeProductFromLookup({
        ...hit,
        sourceKind: 'off_live',
        sourceLabel: 'Open Food Facts (live)',
        brandContacts: params.brandContacts,
      });
      steps[2] = { ...steps[2], state: 'hit', detail: `Found: ${imported.brand} ${imported.name}` };
      emit();
      return { product: imported, imported: true, steps };
    }
    steps[2] = { ...steps[2], state: 'miss', detail: 'No match' };
  } catch {
    steps[2] = { ...steps[2], state: 'blocked', detail: 'Offline or blocked' };
  }

  steps[3] = { ...steps[3], state: 'run', detail: 'Querying api.nal.usda.gov…' };
  emit();

  // 4. Live USDA FoodData Central
  try {
    const hit = await liveUSDA(digits, params.usdaApiKey);
    if (hit) {
      const imported = makeProductFromLookup({
        ...hit,
        sourceKind: 'usda_live',
        sourceLabel: 'USDA FoodData Central (live)',
        brandContacts: params.brandContacts,
      });
      steps[3] = { ...steps[3], state: 'hit', detail: `Found: ${imported.brand} ${imported.name}` };
      emit();
      return { product: imported, imported: true, steps };
    }
    steps[3] = { ...steps[3], state: 'miss', detail: 'No match' };
  } catch {
    steps[3] = { ...steps[3], state: 'blocked', detail: 'Offline or rate-limited (add a free USDA key in Settings)' };
  }

  emit();
  return { product: null, imported: false, steps };
}

interface WorkerScanItem {
  platform?: string;
  source?: string;
  url?: string;
  title?: string;
  author?: string | null;
  posted_at?: string | null;
  excerpt?: string;
}

export async function liveRedditForumScan(
  product: ProductRecord,
  options?: {
    flaggedIngredients?: string[];
    proxyUrl?: string;
    appMode?: AppMode;
  }
): Promise<{
  ok: boolean;
  added: ForumSignalItem[];
  message: string;
}> {
  const effectiveProxy = getEffectiveProxyUrl(options?.proxyUrl);

  // 1. Cloudflare Worker multi-source scan (Reddit + Brand FAQs + U.S. Halal directories + Web)
  if (effectiveProxy) {
    try {
      const qs = new URLSearchParams({
        brand: product.brand,
        product: product.name,
      });
      if (options?.flaggedIngredients?.length) {
        qs.set('ingredients', options.flaggedIngredients.slice(0, 4).join(','));
      }
      const data = (await fetchJSON(`${effectiveProxy}/scan?${qs.toString()}`, 12000)) as {
        ok?: boolean;
        items?: WorkerScanItem[];
      } | null;

      const items = Array.isArray(data?.items) ? data.items : [];
      const added: ForumSignalItem[] = [];
      const existingUrls = new Set(
        product.signals.map((s) => (s.url || '').toLowerCase()).filter(Boolean)
      );

      for (const item of items) {
        const url = String(item.url || '').trim();
        if (url && existingUrls.has(url.toLowerCase())) continue;
        if (url) existingUrls.add(url.toLowerCase());

        const sig = parseForumPost(
          String(item.title || ''),
          String(item.excerpt || ''),
          String(item.source || 'Web'),
          url
        );
        if (item.platform) sig.platform = item.platform;
        if (item.platform === 'brand_faq') sig.tier = 'official_brand_faq';
        if (item.author) sig.author = String(item.author);
        if (item.posted_at && /^\d{4}-\d{2}-\d{2}/.test(item.posted_at)) {
          sig.posted_at = item.posted_at.slice(0, 10);
        }
        added.push(sig);
      }

      if (!added.length) {
        return {
          ok: true,
          added: [],
          message: 'Scanned Reddit, brand FAQs & halal sites — no new matching results found.',
        };
      }

      const buckets = new Set<string>();
      for (const s of added) {
        if (s.platform === 'brand_faq') buckets.add('Brand FAQ');
        else if (s.platform === 'halal_directory') buckets.add('Halal directories');
        else if (s.platform === 'reddit') buckets.add('Reddit');
        else buckets.add('Web');
      }
      const sourceSummary = Array.from(buckets).join(', ');
      return {
        ok: true,
        added,
        message: `Added ${added.length} result${added.length === 1 ? '' : 's'} from ${sourceSummary}.`,
      };
    } catch {
      return {
        ok: false,
        added: [],
        message:
          'Could not reach your live scan proxy URL. Check Settings → Multi-site live scan proxy URL.',
      };
    }
  }

  // 2. FastAPI backend server-side scanner (when hosted full-stack)
  if (options?.appMode === 'api') {
    try {
      const passcode = getSavedPasscode();
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 12000);
      const res = await fetch(`/api/forums/scan/${encodeURIComponent(product.id)}`, {
        method: 'POST',
        signal: ctrl.signal,
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          ...(passcode ? { 'X-Passcode': passcode } : {}),
        },
        body: JSON.stringify({ include_live_reddit: true }),
      });
      clearTimeout(timer);
      if (res.ok) {
        const data = (await res.json()) as {
          signals?: Array<Record<string, unknown>>;
        };
        const existingUrls = new Set(
          product.signals.map((s) => (s.url || '').toLowerCase()).filter(Boolean)
        );
        const added: ForumSignalItem[] = [];
        for (const s of data.signals || []) {
          const url = String(s.url || '').trim();
          if (url && existingUrls.has(url.toLowerCase())) continue;
          const sig = parseForumPost(
            String(s.title || ''),
            String(s.raw_excerpt || ''),
            String(s.source_name || 'Forum'),
            url
          );
          if (s.source_platform) sig.platform = String(s.source_platform);
          if (s.author) sig.author = String(s.author);
          if (typeof s.posted_at === 'string' && s.posted_at) sig.posted_at = s.posted_at.slice(0, 10);
          added.push(sig);
        }
        return {
          ok: true,
          added,
          message: added.length
            ? `Added ${added.length} community/web result${added.length === 1 ? '' : 's'}.`
            : 'No new matching posts found.',
        };
      }
    } catch {
      // fall through
    }
  }

  // 3. Direct browser fallback (works only if browser/network permits reddit.com CORS)
  const q = encodeURIComponent(`${product.brand} ${product.name.split(' ').slice(0, 3).join(' ')} halal`);
  try {
    const data = (await fetchJSON(
      `https://www.reddit.com/search.json?q=${q}&sort=relevance&limit=6`,
      6500
    )) as { data?: { children?: Array<{ data: Record<string, unknown> }> } } | null;

    const children = data?.data?.children || [];
    const added: ForumSignalItem[] = [];
    for (const ch of children) {
      const post = ch.data;
      const url = `https://www.reddit.com${String(post.permalink || '')}`;
      if (product.signals.some((s) => s.url === url)) continue;
      const sig = parseForumPost(
        String(post.title || ''),
        String(post.selftext || ''),
        `r/${String(post.subreddit || 'reddit')}`,
        url
      );
      sig.author = post.author ? `u/${String(post.author)}` : null;
      if (typeof post.created_utc === 'number') {
        sig.posted_at = new Date(post.created_utc * 1000).toISOString().slice(0, 10);
      }
      added.push(sig);
    }
    return {
      ok: true,
      added,
      message: added.length
        ? `Added ${added.length} Reddit post${added.length === 1 ? '' : 's'}.`
        : 'No new matching Reddit posts found.',
    };
  } catch {
    return {
      ok: false,
      added: [],
      message:
        'Live scan blocked by browser (CORS). Add your free Cloudflare Worker URL in Settings for live Reddit + Web scanning, or use Reddit / Web + "Paste a post".',
    };
  }
}

export function exportBackupJson(state: PersistedState): void {
  const payload = {
    app: 'HalalLens',
    version: 4,
    exported_at: new Date().toISOString(),
    data: state,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `halallens-backup-${todayISO()}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function parseBackupFile(file: File): Promise<PersistedState> {
  const text = await file.text();
  const parsed = JSON.parse(text) as { data?: Partial<PersistedState> } & Partial<PersistedState>;
  const d = parsed.data || parsed;
  if (!Array.isArray(d.products)) {
    throw new Error('This file does not look like a HalalLens backup.');
  }
  return {
    products: sanitizeProductContacts(d.products),
    policies: Array.isArray(d.policies) ? d.policies : [],
    brandContacts: sanitizeSavedBrandContacts(d.brandContacts),
    strict: d.strict ? { ...DEFAULT_STRICT, ...d.strict } : { ...DEFAULT_STRICT },
    history: Array.isArray(d.history) ? d.history : [],
    usdaApiKey: typeof d.usdaApiKey === 'string' ? d.usdaApiKey : '',
    proxyUrl: typeof d.proxyUrl === 'string' ? normalizeProxyUrl(d.proxyUrl) : DEFAULT_PROXY_URL,
    showExamples: typeof d.showExamples === 'boolean' ? d.showExamples : true,
  };
}
