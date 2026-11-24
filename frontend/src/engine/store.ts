import offCacheRaw from '../data/offCache.json';
import { digitsOf, parseForumPost, todayISO, uid, upcVariants } from './evaluator';
import { createSeedProducts, DEFAULT_STRICT, SEED_POLICIES } from './seeds';
import type {
  AppMode,
  BrandPolicyRecord,
  ForumSignalItem,
  HistoryItem,
  LookupStep,
  OffCacheItem,
  ProductRecord,
  StrictnessSettings,
} from './types';

export const OFF_CACHE: OffCacheItem[] = offCacheRaw as OffCacheItem[];
export const CACHE_COUNT = OFF_CACHE.length;

const CACHE_INDEX = new Map<string, OffCacheItem>();
for (const item of OFF_CACHE) {
  for (const variant of upcVariants(item.upc)) {
    CACHE_INDEX.set(variant, item);
  }
}

export const STORE_KEY = 'halallens.v4';
const PASSCODE_SESSION_KEY = 'halallens.passcode';

export interface PersistedState {
  products: ProductRecord[];
  policies: BrandPolicyRecord[];
  strict: StrictnessSettings;
  history: HistoryItem[];
  usdaApiKey: string;
  showExamples: boolean;
}

export function loadPersistedState(): PersistedState {
  const defaults: PersistedState = {
    products: createSeedProducts(),
    policies: JSON.parse(JSON.stringify(SEED_POLICIES)),
    strict: { ...DEFAULT_STRICT },
    history: [],
    usdaApiKey: '',
    showExamples: true,
  };
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return defaults;
    const d = JSON.parse(raw) as Partial<PersistedState>;
    return {
      products: Array.isArray(d.products) ? d.products : defaults.products,
      policies: Array.isArray(d.policies) ? d.policies : defaults.policies,
      strict: d.strict ? { ...DEFAULT_STRICT, ...d.strict } : defaults.strict,
      history: Array.isArray(d.history) ? d.history : [],
      usdaApiKey: typeof d.usdaApiKey === 'string' ? d.usdaApiKey : '',
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
  sourceKind: string;
  sourceLabel: string;
}): ProductRecord {
  const sid = uid('s');
  return {
    id: uid('p'),
    upc: o.upc,
    name: o.name || `Product ${o.upc}`,
    brand: o.brand || 'Unknown brand',
    category: o.category || 'Grocery',
    cert: o.cert || (o.halal ? 'Halal label (confirm symbol on package)' : null),
    kosher: normKosher(o.kosher),
    vegan: Boolean(o.vegan),
    email: '',
    contact_url: '',
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

async function liveOFF(digits: string) {
  for (const v of upcVariants(digits)) {
    const d = (await fetchJSON(
      `https://world.openfoodfacts.org/api/v2/product/${encodeURIComponent(v)}.json?fields=code,product_name,brands,categories_tags_en,ingredients_text_en,ingredients_text,labels_tags`
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
      };
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

export async function liveRedditForumScan(product: ProductRecord): Promise<{
  ok: boolean;
  added: ForumSignalItem[];
  message: string;
}> {
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
      message: 'Live Reddit scan was blocked by the browser. Use the Reddit / Web links and "Paste a post".',
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
    products: d.products,
    policies: Array.isArray(d.policies) ? d.policies : [],
    strict: d.strict ? { ...DEFAULT_STRICT, ...d.strict } : { ...DEFAULT_STRICT },
    history: Array.isArray(d.history) ? d.history : [],
    usdaApiKey: typeof d.usdaApiKey === 'string' ? d.usdaApiKey : '',
    showExamples: typeof d.showExamples === 'boolean' ? d.showExamples : true,
  };
}
