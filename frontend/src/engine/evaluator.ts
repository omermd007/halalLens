import { ANIMAL_Q, RES_META, RULES, SAFE_Q, TRUSTED_KOSHER, canon } from './rules';
import type {
  BrandPolicyRecord,
  ConsensusSummary,
  Determination,
  FlagEvaluation,
  ForumSignalItem,
  ProductEvaluation,
  ProductRecord,
  ProductSnapshot,
  RecipeDiff,
  RuleMatch,
  StatusKey,
  StrictnessSettings,
} from './types';

export const todayISO = (): string => new Date().toISOString().slice(0, 10);

export const uid = (prefix: string): string =>
  `${prefix}_${Math.random().toString(36).slice(2, 8)}${Date.now().toString(36).slice(-4)}`;

export const digitsOf = (s: string | null | undefined): string => String(s || '').replace(/\D/g, '');

export function upcVariants(raw: string): string[] {
  const d = digitsOf(raw);
  const out = new Set<string>([d]);
  if (d.length === 12) out.add('0' + d);
  if (d.length === 13 && d[0] === '0') out.add(d.slice(1));
  if (d.length === 14) {
    out.add(d.slice(1));
    if (d.startsWith('00')) out.add(d.slice(2));
  }
  if (d.length === 11) {
    out.add('0' + d);
    out.add('00' + d);
  }
  return [...out].filter(Boolean);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(String(iso).length <= 10 ? `${iso}T12:00:00` : iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

export function daysBetween(a: string, b: string): number {
  return Math.floor((new Date(b).getTime() - new Date(a).getTime()) / 86400000);
}

export function addMonths(iso: string, months: number): string {
  const d = new Date(`${iso}T12:00:00`);
  d.setMonth(d.getMonth() + months);
  return d.toISOString().slice(0, 10);
}

export function freshnessLabel(postedAt: string): string {
  const days = daysBetween(postedAt, todayISO());
  if (days <= 365) return 'Recent (under 1 yr)';
  if (days <= 730) return '1–2 yrs old';
  return 'Older than 2 yrs';
}

export function normalizeIngredients(raw: string): string {
  return String(raw || '')
    .replace(/_/g, '')
    .replace(/\u00a0/g, ' ')
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u2013\u2014]/g, '-')
    .replace(/^\s*ingredients?\s*(list)?\s*[:\-]\s*/i, '')
    .replace(/[\[\{]/g, '(')
    .replace(/[\]\}]/g, ')')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .replace(/\s*([,;:])\s*/g, '$1 ')
    .replace(/\(\s+/g, '(')
    .replace(/\s+\)/g, ')')
    .replace(/[\s.,;]+$/, '')
    .trim();
}

function splitTop(text: string): string[] {
  const parts: string[] = [];
  let buf = '';
  let depth = 0;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '(') depth++;
    else if (ch === ')') depth = Math.max(0, depth - 1);
    const isSep =
      depth === 0 &&
      (ch === ',' ||
        ch === ';' ||
        (ch === '.' && text[i + 1] === ' ' && !/\d/.test(text[i - 1] || '')));
    if (isSep) {
      if (buf.trim()) parts.push(buf.trim());
      buf = '';
    } else {
      buf += ch;
    }
  }
  if (buf.trim()) parts.push(buf.trim());
  return parts;
}

const THRESHOLD =
  /^(contains\s+)?(less\s+than\s+\d+(\.\d+)?\s*%|\d+(\.\d+)?\s*%\s+or\s+less)\s*(of\s*)?(each\s+of\s+)?(the\s+following\s*)?:?\s*/;
const SKIP_TOKEN =
  /^(contains\s*:|allergens?\s*:|may contain|manufactured (in|on)|produced (in|on)|processed (in|on)|made in a facility|made on equipment|distributed by|contains milk|contains wheat|contains soy)/;

export function parseTokens(
  text: string,
  parent: string | null = null,
  depth = 0
): Array<{ token: string; parent: string | null }> {
  const out: Array<{ token: string; parent: string | null }> = [];
  for (let item of splitTop(text)) {
    item = item
      .replace(THRESHOLD, '')
      .replace(/^(and\/or|and|or)\s+/, '')
      .replace(/[.:]+$/, '')
      .trim();
    if (!item || SKIP_TOKEN.test(item)) continue;
    const open = item.indexOf('(');
    if (open > 0 && item.endsWith(')') && depth < 4) {
      const head = item.slice(0, open).trim();
      const inner = item.slice(open + 1, -1).trim();
      if (/[,;]/.test(inner)) {
        out.push({ token: head, parent });
        out.push(...parseTokens(inner, head, depth + 1));
        continue;
      }
    }
    out.push({ token: item, parent });
  }
  return out;
}

export function fingerprint(raw: string): string {
  const str = normalizeIngredients(raw);
  let h1 = 0xdeadbeef ^ str.length;
  let h2 = 0x41c6ce57 ^ str.length;
  for (let i = 0; i < str.length; i++) {
    const c = str.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 2654435761);
    h2 = Math.imul(h2 ^ c, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return ((h2 >>> 0).toString(16).padStart(8, '0') + (h1 >>> 0).toString(16).padStart(8, '0')).slice(0, 12);
}

export function computeDiff(oldRaw: string, newRaw: string): { added: string[]; removed: string[] } {
  const a = new Set(parseTokens(normalizeIngredients(oldRaw)).map((t) => t.token));
  const b = new Set(parseTokens(normalizeIngredients(newRaw)).map((t) => t.token));
  return {
    added: [...b].filter((x) => !a.has(x)).sort(),
    removed: [...a].filter((x) => !b.has(x)).sort(),
  };
}

function hasAnimalQualifier(c: string): boolean {
  if (!ANIMAL_Q.test(c)) return false;
  // Avoid matching "non animal" or "animal free"
  const cleaned = c.replace(/ non animal /g, ' ').replace(/ animal free /g, ' ');
  return ANIMAL_Q.test(cleaned);
}

export function matchRules(raw: string): RuleMatch[] {
  const found = new Map<string, { rule: typeof RULES[number]; risk: 'haram' | 'meat' | 'mushbooh'; token: string; parent: string | null; aliases: Set<string>; safe: boolean }>();
  const rank = { haram: 3, meat: 2, mushbooh: 1 } as const;

  for (const t of parseTokens(normalizeIngredients(raw))) {
    const c = canon(t.token);
    let hits: Array<{ r: typeof RULES[number]; a: string }> = [];
    for (const r of RULES) {
      if (r.exclude && r.exclude.test(c)) continue;
      const a = r.aliasCanon.find((al) => c.includes(` ${al} `));
      if (a) hits.push({ r, a });
    }
    hits = hits.filter(
      (h) => !hits.some((o) => o !== h && o.a.length > h.a.length && ` ${o.a} `.includes(` ${h.a} `))
    );
    for (const { r, a } of hits) {
      let risk = r.risk;
      if ((r.id === 'meat' || r.id === 'pork') && / flavou?r(s|ing)? /.test(c) && !/ (pork|lard|bacon fat) /.test(c)) {
        risk = 'mushbooh';
      }
      const safe = risk === 'mushbooh' && SAFE_Q.test(c) && !hasAnimalQualifier(c);
      const prev = found.get(r.id);
      if (!prev) {
        found.set(r.id, { rule: r, risk, token: t.token, parent: t.parent, aliases: new Set([a]), safe });
      } else {
        prev.aliases.add(a);
        if (!safe) prev.safe = false;
        if (rank[risk] > rank[prev.risk]) {
          prev.risk = risk;
          prev.token = t.token;
          prev.parent = t.parent;
        }
      }
    }
  }

  if (found.has('cheese') && (found.has('enzymes') || found.has('cheese_culture'))) found.delete('cheese');
  if (found.has('pork_gelatin')) found.delete('gelatin');
  return [...found.values()].map((item) => ({ ...item, aliases: [...item.aliases] }));
}

export function currentSnap(p: ProductRecord): ProductSnapshot | undefined {
  return p.snapshots.find((s) => s.is_current) || p.snapshots[p.snapshots.length - 1];
}

export function activePolicy(brand: string, policies: BrandPolicyRecord[]): BrandPolicyRecord | null {
  const target = String(brand || '').toLowerCase();
  const today = todayISO();
  return policies.find((bp) => bp.brand.toLowerCase() === target && bp.expires_at >= today) || null;
}

export function consensusOf(signals: ForumSignalItem[] = []): ConsensusSummary {
  const counts: Record<Determination, number> = {
    plant_or_microbial: 0,
    varies_by_supplier: 0,
    animal_or_haram: 0,
    halal_slaughter: 0,
    unclear: 0,
  };
  let quoted = 0;
  let faq = 0;
  let nonUs = 0;
  const us = new Set<Determination>();

  for (const s of signals) {
    counts[s.determination] = (counts[s.determination] || 0) + 1;
    if (s.tier === 'quoted_company_reply') quoted++;
    if (s.tier === 'official_brand_faq') faq++;
    if (s.region === 'non_us') nonUs++;
    else if (s.determination !== 'unclear') us.add(s.determination);
  }
  const conflict =
    us.has('plant_or_microbial') && (us.has('animal_or_haram') || us.has('varies_by_supplier'));

  const parts: string[] = [];
  if (counts.plant_or_microbial) parts.push(`${counts.plant_or_microbial} say plant/microbial`);
  if (counts.varies_by_supplier) parts.push(`${counts.varies_by_supplier} say it varies`);
  if (counts.animal_or_haram) parts.push(`${counts.animal_or_haram} say animal`);
  return {
    total: signals.length,
    counts,
    quoted,
    faq,
    nonUs,
    conflict,
    line: parts.join(' · ') || 'No community reports yet.',
  };
}

export function parseForumPost(
  title: string,
  body: string,
  source: string,
  url: string
): ForumSignalItem {
  const text = `${title || ''}. ${body || ''}`;
  const low = canon(text);
  const ingredients = RULES.filter((r) => r.aliasCanon.some((a) => low.includes(` ${a} `))).map((r) => r.name);

  let det: Determination = 'unclear';
  if (
    /(varies by (supplier|plant|location)|depends on (the )?supplier|multiple suppliers|either (plant|vegetable) or animal|plant or animal|animal or (plant|vegetable)|can'?t guarantee|cannot guarantee|different suppliers)/i.test(
      text
    )
  ) {
    det = 'varies_by_supplier';
  } else if (
    /(do(es)? not (use|contain) (any )?(pork|animal|porcine)|no (animal|pork) (rennet|enzymes|gelatin|derived)|not (porcine|animal[- ]derived|from (pigs|pork|animals))|non[- ]animal|microbial (enzymes|rennet)|vegetarian rennet|vegetable rennet|100% (plant|vegetable)|plant[- ]based|vegetable[- ]derived|fermentation[- ]produced|suitable for vegetarians|fish gelatin|halal beef gelatin)/i.test(
      text
    )
  ) {
    det = 'plant_or_microbial';
  } else if (
    /(porcine|pork gelatin|animal rennet|calf rennet|pepsin|beef tallow|lard|contains animal|derived from (pork|pigs|beef|animals)|is haram|not halal|uses animal)/i.test(
      text
    )
  ) {
    det = 'animal_or_haram';
  }

  let tier: ForumSignalItem['tier'] = 'community_anecdote';
  if (/faq|official (site|website|statement)/i.test(`${source} ${text}`)) {
    tier = 'official_brand_faq';
  } else if (
    /(i emailed|i e-mailed|i called|i contacted|i messaged|customer (service|care|support)|consumer (relations|care)|they (replied|responded|emailed back|said)|rep (said|told)|company confirmed|their response|got a reply)/i.test(
      text
    )
  ) {
    tier = 'quoted_company_reply';
  }

  let region: ForumSignalItem['region'] = 'unknown';
  let notes: string | null = null;
  const nonUs = text.match(
    /\b(UK|U\.K\.|United Kingdom|Britain|British|Canada|Canadian|Toronto|Ontario|Europe|European|EU|Germany|German|Australia|Australian|Turkey|Turkish|Malaysia|Indonesia|Tesco|Sainsbury'?s|Asda|Loblaws|Kraft Dinner|KD)\b/
  );
  if (nonUs && !/turkey (bacon|breast|sandwich|meat|sausage|jerky)/i.test(text)) {
    region = 'non_us';
    notes = `Mentions “${nonUs[0]}”. Products sold outside the U.S. often use different recipes.`;
  } else if (
    /\b(U\.S\.|US version|USA|United States|American|Costco|Trader Joe'?s|Kroger|Target|Walmart|Publix|Safeway|H-E-B)\b/i.test(
      text
    )
  ) {
    region = 'us';
    notes = 'Refers to the U.S. product';
  }

  return {
    id: uid('fs'),
    platform: url && /reddit/i.test(url) ? 'reddit' : 'pasted',
    source: source || 'Pasted post',
    url: url || null,
    title: title || 'Pasted discussion',
    author: null,
    posted_at: todayISO(),
    excerpt: String(body || '').slice(0, 480),
    ingredients: ingredients.length ? ingredients : ['(none named)'],
    determination: det,
    tier,
    region,
    region_notes: notes,
  };
}

export function evaluateProduct(
  p: ProductRecord,
  policies: BrandPolicyRecord[],
  strict: StrictnessSettings
): ProductEvaluation {
  const cur = currentSnap(p);
  const raw = (cur?.raw_ingredients || '').trim();
  const today = todayISO();
  const policy = activePolicy(p.brand, policies);
  const certified = Boolean(p.cert);
  const kosherTrusted = Boolean(p.kosher && TRUSTED_KOSHER.has(String(p.kosher).toUpperCase().replace(/\s+/g, '')));

  let diff: RecipeDiff | null = null;
  const sorted = [...p.verifications].sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const latest = sorted[0];
  if (latest && cur && latest.snap !== cur.id) {
    const old = p.snapshots.find((s) => s.id === latest.snap);
    if (old && fingerprint(old.raw_ingredients) !== fingerprint(raw)) {
      const d = computeDiff(old.raw_ingredients, raw);
      diff = {
        since: old.captured_at,
        verified: latest.date,
        oldFp: fingerprint(old.raw_ingredients),
        added: d.added,
        removed: d.removed,
      };
    }
  }

  const flags: FlagEvaluation[] = [];
  let hasHaram = false;
  let hasMeat = false;
  let varies = false;
  let unresolved = false;

  for (const m of raw ? matchRules(raw) : []) {
    const r = m.rule;
    let res: FlagEvaluation['res'] = 'unresolved';
    let detail = 'No confirmation yet for this label.';
    const v = cur && p.verifications.find((x) => x.snap === cur.id && x.ingredient === r.id);

    if (m.risk === 'haram') {
      hasHaram = true;
      res = 'haram';
      detail = 'Listed on the label.';
    } else if (m.risk === 'meat') {
      if (certified) {
        res = 'cert';
        detail = `Covered by ${p.cert} halal certification.`;
      } else if (v && v.determination === 'halal_slaughter') {
        res = 'verified';
        detail = `Brand confirmed halal slaughter (${fmtDate(v.date)}).`;
      } else {
        hasMeat = true;
        res = 'haram';
        detail = 'Meat without halal certification.';
      }
    } else if (certified) {
      res = 'cert';
      detail = `Covered by ${p.cert} halal certification.`;
    } else if (v) {
      if (v.determination === 'animal_or_haram') {
        hasHaram = true;
        res = 'haram';
        detail = `Brand confirmed animal source (${fmtDate(v.date)}).`;
      } else if (v.varies || v.determination === 'varies_by_supplier') {
        varies = true;
        unresolved = true;
        res = 'varies';
        detail = `Brand said it varies by supplier (${fmtDate(v.date)}).`;
      } else if (v.expires && v.expires < today) {
        unresolved = true;
        res = 'expired';
        detail = `Confirmation expired ${fmtDate(v.expires)}.`;
      } else {
        res = 'verified';
        detail = `Brand confirmed plant/microbial (${fmtDate(v.date)}).`;
      }
    } else if (r.strict === 'whey' && !strict.whey) {
      res = 'info';
      detail = 'Info only with your current settings.';
    } else if (r.strict === 'nf' && !strict.nf) {
      res = 'info';
      detail = 'Info only with your current settings.';
    } else if (r.strict === 'ethanol' && !strict.ethanol) {
      res = 'info';
      detail = 'Info only with your current settings.';
    } else if (m.safe) {
      res = 'label';
      detail = `The label says “${m.token}”.`;
    } else if (p.vegan && r.strict !== 'ethanol') {
      res = 'vegan';
      detail = 'Covered by vegan certification.';
    } else if (policy && policy.ingredients.includes(r.id)) {
      res = 'policy';
      detail = `${policy.brand} brand policy (checked ${fmtDate(policy.checked_date)}).`;
    } else if (strict.oud && r.strict === 'oud' && kosherTrusted) {
      res = 'kosher';
      detail = `Accepted via ${p.kosher} (your setting).`;
    } else if (diff) {
      unresolved = true;
      res = 'recheck';
      detail = 'Recipe changed since your last confirmation.';
    } else {
      unresolved = true;
    }

    flags.push({ ...m, id: r.id, res, detail, tone: RES_META[res].tone });
  }

  let status: StatusKey;
  let summary: string;
  const names = (arr: FlagEvaluation[]) => arr.map((f) => f.rule.name).join(', ');
  const unresolvedFlags = flags.filter((f) => ['unresolved', 'varies', 'expired', 'recheck'].includes(f.res));

  if (!raw) {
    status = 'mushbooh_needs_check';
    summary = 'We found the product but no ingredient list. Add the label to check it.';
  } else if (hasHaram || hasMeat) {
    status = 'animal_or_haram';
    summary = `Contains ${names(flags.filter((f) => f.res === 'haram'))}.`;
  } else if (diff) {
    status = 'formulation_changed';
    summary = `The ingredients changed since you verified this on ${fmtDate(diff.verified)}. Re-check before buying.`;
  } else if (certified) {
    status = 'certified_halal';
    summary = `Certified by ${p.cert}. Still glance at the package for the symbol.`;
  } else if (varies || unresolved) {
    status = 'mushbooh_needs_check';
    const n = unresolvedFlags.length;
    summary =
      varies && n === 1 && unresolvedFlags[0].res === 'varies'
        ? `The brand said ${unresolvedFlags[0].rule.name} varies by supplier, so it can't be guaranteed.`
        : `${n} ingredient${n === 1 ? '' : 's'} could come from animals: ${names(unresolvedFlags)}.`;
  } else {
    status = 'verified_plant_or_microbial';
    summary =
      flags.filter((f) => f.res !== 'info').length === 0
        ? 'No doubtful ingredients found on this label.'
        : 'Every doubtful ingredient is confirmed plant/microbial or covered by a certification.';
  }

  return {
    p,
    cur,
    raw,
    fp: raw ? fingerprint(raw) : null,
    flags,
    status,
    summary,
    diff,
    policy,
    unresolvedFlags,
    consensus: consensusOf(p.signals),
  };
}

export function queueOf(evals: ProductEvaluation[]) {
  const today = todayISO();
  const soon = addMonths(today, 1);
  const changed = evals.filter((e) => e.status === 'formulation_changed');
  const check = evals.filter((e) => e.status === 'mushbooh_needs_check');
  const waiting = evals.filter((e) => e.p.outreach.some((o) => o.state === 'sent' || o.state === 'drafted'));
  const expiring = evals.filter((e) =>
    e.p.verifications.some((v) => v.expires && v.expires >= today && v.expires <= soon)
  );
  return { changed, check, waiting, expiring, count: changed.length + check.length };
}

export function buildOutreachDraft(
  ev: ProductEvaluation,
  allProducts: ProductRecord[],
  mode: 'full' | 'quick' = 'full',
  sigId?: string
): {
  to: string;
  subject: string;
  body: string;
  warnings: string[];
} {
  const p = ev.p;
  const targets = ev.unresolvedFlags.length ? ev.unresolvedFlags : ev.flags.filter((f) => f.res !== 'info');
  const sig = sigId ? p.signals.find((s) => s.id === sigId) : undefined;
  const today = todayISO();

  const warnings: string[] = [];
  const lastProd = p.outreach.find((o) => o.state === 'sent' && daysBetween(o.created_at, today) < 30);
  if (lastProd) warnings.push(`You already contacted ${p.brand} about this product within the last 30 days.`);
  const lastBrand = allProducts.some(
    (other) =>
      other.id !== p.id &&
      other.brand.toLowerCase() === p.brand.toLowerCase() &&
      other.outreach.some((o) => o.state === 'sent' && daysBetween(o.created_at, today) < 14)
  );
  if (lastBrand) warnings.push(`You contacted ${p.brand} about another item within the last 14 days.`);

  const subject =
    mode === 'quick'
      ? `Quick confirmation: ${p.brand} ${p.name} (UPC ${p.upc})`
      : `Ingredient source question: ${p.brand} ${p.name} (UPC ${p.upc})`;

  const lines: string[] = [
    `Hello ${p.brand} Consumer Care,`,
    '',
    `I'm checking the U.S. version of ${p.brand} ${p.name} (UPC ${p.upc}${ev.cur?.lot_code ? `, lot ${ev.cur.lot_code}` : ''}) for halal dietary requirements.`,
    '',
  ];

  if (mode === 'quick' && sig) {
    lines.push(
      `Online consumers have shared a note from ${sig.source} (${fmtDate(sig.posted_at)}) regarding ${sig.ingredients.join(', ')}. Could you please confirm whether the current U.S. formulation is still 100% plant- or microbial-derived, and whether sourcing varies by plant or supplier?`
    );
  } else {
    if (ev.diff) {
      lines.push(
        `I noticed the ingredient list on a recent package changed${ev.diff.added.length ? ` (added: ${ev.diff.added.slice(0, 4).join(', ')})` : ''}.`
      );
      lines.push('');
    }
    lines.push('Could you please clarify the source of the following ingredient(s) in the current U.S. product?');
    for (const f of targets) {
      lines.push(`• ${f.rule.name}: ${f.rule.question}`);
    }
    lines.push('');
    lines.push('Also, does the source of these ingredients vary by manufacturing plant or supplier?');
  }

  lines.push('', 'Thank you very much for your help!');

  return {
    to: p.email || '',
    subject,
    body: lines.join('\n'),
    warnings,
  };
}
