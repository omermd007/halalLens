import { Fragment } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  Database,
  ExternalLink,
  FileText,
  FlaskConical,
  Globe,
  Mail,
  Plus,
  RefreshCw,
  Reply,
  Search,
} from 'lucide-react';
import { fmtDate, freshnessLabel } from '../engine/evaluator';
import { RES_META, RULE_BY_ID, STATUS_META } from '../engine/rules';
import { CACHE_COUNT } from '../engine/store';
import type { FlagEvaluation, ProductEvaluation, Tone } from '../engine/types';
import { StatusGlyph } from './StatusIcon';

function HighlightedIngredients({ raw, flags }: { raw: string; flags: FlagEvaluation[] }) {
  if (!raw) {
    return <span className="muted">No ingredient list saved yet.</span>;
  }
  const phrases: Array<{ phrase: string; tone: Tone }> = [];
  for (const f of flags) {
    if (f.res === 'info') continue;
    for (const alias of f.aliases) {
      phrases.push({ phrase: alias, tone: f.tone });
    }
  }
  phrases.sort((a, b) => b.phrase.length - a.phrase.length);
  if (!phrases.length) return <>{raw.toLowerCase()}</>;

  const lower = raw.toLowerCase();
  const escaped = phrases.map((p) =>
    p.phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '[\\s\\-]+')
  );
  const re = new RegExp(`(${escaped.join('|')})`, 'gi');
  const parts = lower.split(re);

  return (
    <>
      {parts.map((part, idx) => {
        if (idx % 2 === 1) {
          const norm = part.replace(/[\s\-]+/g, ' ').toLowerCase();
          const hit = phrases.find((p) => p.phrase === norm) || phrases[0];
          return (
            <mark key={idx} className={`hl tone-${hit.tone}`}>
              {part}
            </mark>
          );
        }
        return <Fragment key={idx}>{part}</Fragment>;
      })}
    </>
  );
}

const SIG_DET: Record<string, { tone: Tone; label: string }> = {
  plant_or_microbial: { tone: 'ok', label: 'Says plant/microbial' },
  varies_by_supplier: { tone: 'doubt', label: 'Says it varies' },
  animal_or_haram: { tone: 'haram', label: 'Says animal' },
  halal_slaughter: { tone: 'halal', label: 'Says halal slaughter' },
  unclear: { tone: 'neutral', label: 'Unclear' },
};

const TIER_LABEL: Record<string, string> = {
  official_brand_faq: 'Official brand FAQ',
  quoted_company_reply: 'Quotes a brand reply',
  community_anecdote: 'Personal anecdote',
};

export function ProductDetailView({
  ev,
  onBack,
  onOpenDraft,
  onOpenLog,
  onCompareLabel,
  onSimulateChange,
  onLiveForumScan,
  onOpenPasteForum,
  scanningForum,
}: {
  ev: ProductEvaluation;
  onBack: () => void;
  onOpenDraft: (mode: 'full' | 'quick', sigId?: string) => void;
  onOpenLog: (ingredientId?: string) => void;
  onCompareLabel: () => void;
  onSimulateChange: () => void;
  onLiveForumScan: () => void;
  onOpenPasteForum: () => void;
  scanningForum: boolean;
}) {
  const { p, cur, flags, diff, consensus } = ev;
  const st = STATUS_META[ev.status];
  const q = encodeURIComponent(`${p.brand} ${p.name.split(' ').slice(0, 4).join(' ')} halal`);
  const redditUrl = `https://www.reddit.com/search/?q=${q}`;
  const webUrl = `https://www.google.com/search?q=${q}+enzymes+OR+gelatin+OR+ingredients`;

  const timeline = [
    ...p.verifications.map((v) => ({
      at: v.date,
      tone: (v.determination === 'animal_or_haram' ? 'haram' : v.varies ? 'doubt' : 'ok') as Tone,
      title: `Reply: ${(RULE_BY_ID[v.ingredient]?.name || v.ingredient)} — ${v.determination.replace(/_/g, ' ')}`,
      meta: `${v.contact || p.brand} (${v.channel}) · ${fmtDate(v.date)}${v.expires ? ` · valid until ${fmtDate(v.expires)}` : ''}`,
      text: v.excerpt,
    })),
    ...p.outreach.map((o) => ({
      at: o.created_at,
      tone: 'doubt' as Tone,
      title: `Email ${o.state}: ${o.subject}`,
      meta: fmtDate(o.created_at),
      text: o.to ? `To ${o.to}` : '',
    })),
    ...p.notes.map((n) => ({
      at: n.at,
      tone: 'neutral' as Tone,
      title: 'Note',
      meta: fmtDate(n.at),
      text: n.text,
    })),
  ].sort((a, b) => String(b.at).localeCompare(String(a.at)));

  return (
    <div className="stack fadein">
      <div>
        <button className="back" type="button" onClick={onBack}>
          <ChevronLeft size={18} />
          Back
        </button>
      </div>

      <div className="detail-grid">
        <div className="stack">
          <section className={`verdict tone-${st.tone}`}>
            <div className="verdict-top">
              <div className="verdict-ic">
                <StatusGlyph status={ev.status} size={28} />
              </div>
              <div>
                <div className="verdict-label">Verdict</div>
                <h1>{st.title}</h1>
                <p className="verdict-sum">{ev.summary}</p>
              </div>
            </div>

            <div className="verdict-prod">
              <div className="verdict-name">
                <small>{p.brand}</small>
                {p.name}
              </div>
              <span className="tag mono">UPC {p.upc}</span>
              {p.cert && <span className="tag">Certifier: {p.cert}</span>}
              {p.kosher && <span className="tag">Kosher: {p.kosher}</span>}
              {p.vegan && <span className="tag">Vegan</span>}
              <span className="tag">
                <Database size={13} />
                {p.source?.label || 'Saved'}
              </span>
            </div>

            {diff && (
              <div className="drift">
                <div className="drift-title">
                  <RefreshCw size={15} />
                  Recipe changed since your {fmtDate(diff.verified)} confirmation
                </div>
                <div className="chips mt8">
                  {diff.added.map((x) => (
                    <span key={`a-${x}`} className="diffchip diff-add">
                      + {x}
                    </span>
                  ))}
                  {diff.removed.map((x) => (
                    <span key={`r-${x}`} className="diffchip diff-rem">
                      − {x}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </section>

          <section className="card">
            <div className="card-head">
              <div>
                <div className="eyebrow">Ingredient check</div>
                <div className="title">What we found</div>
              </div>
              <div className="legend">
                <span>
                  <i className="chip-dot" style={{ background: 'var(--haram)' }} />
                  Not halal
                </span>
                <span>
                  <i className="chip-dot" style={{ background: 'var(--doubt)' }} />
                  Doubtful
                </span>
                <span>
                  <i className="chip-dot" style={{ background: 'var(--ok)' }} />
                  OK / confirmed
                </span>
              </div>
            </div>

            {flags.length ? (
              flags.map((f) => {
                const rm = RES_META[f.res];
                const canLog = f.res !== 'haram' || f.risk === 'meat';
                return (
                  <div key={f.id} className={`ing tone-${f.tone}`}>
                    <span className="ing-dot" />
                    <div>
                      <div className="ing-top">
                        <div className="ing-name">
                          {f.rule.name}
                          {f.parent && <span>in {f.parent}</span>}
                        </div>
                        <div className="row" style={{ gap: 6 }}>
                          <span className="pill">{rm.label}</span>
                          {canLog && (
                            <button
                              className="btn btn-ghost btn-sm"
                              type="button"
                              onClick={() => onOpenLog(f.id)}
                            >
                              <Reply size={14} />
                              Log reply
                            </button>
                          )}
                        </div>
                      </div>
                      <p className="ing-plain">{f.rule.plain}</p>
                      <div className="ing-res">{f.detail}</div>
                      <details className="more">
                        <summary>
                          <ChevronRight size={14} />
                          Details &amp; what to ask the brand
                        </summary>
                        <div className="more-grid">
                          <div>
                            <b>U.S. label context</b>
                            {f.rule.context}
                          </div>
                          <div>
                            <b>Kosher / vegan note</b>
                            {f.rule.kosher}
                          </div>
                          <div>
                            <b>Question for the brand</b>
                            {f.rule.question}
                          </div>
                        </div>
                      </details>
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="empty">
                {ev.raw ? (
                  'No doubtful or animal-derived ingredients were found on this label.'
                ) : (
                  <>
                    <div>No ingredient list yet for this barcode.</div>
                    <button className="btn btn-primary btn-sm mt12" type="button" onClick={onCompareLabel}>
                      <Plus size={15} />
                      Add ingredient list
                    </button>
                  </>
                )}
              </div>
            )}
          </section>

          <section className="card">
            <div className="card-head">
              <div>
                <div className="eyebrow">From the package</div>
                <div className="title">Full ingredient list</div>
              </div>
              {ev.fp && <span className="tag mono">Label ID {ev.fp}</span>}
            </div>
            <div className="inglist">
              <HighlightedIngredients raw={ev.raw} flags={flags} />
            </div>
            <div
              className="row between"
              style={{ padding: '12px 20px', borderTop: '1px solid var(--line)' }}
            >
              <span className="small muted">
                Captured {fmtDate(cur?.captured_at)}
                {cur?.lot_code ? ` · Lot ${cur.lot_code}` : ''}
              </span>
              <button className="btn btn-outline btn-sm" type="button" onClick={onCompareLabel}>
                <RefreshCw size={14} />
                Box looks different? Compare label
              </button>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <div>
                <div className="eyebrow">Community · advisory only</div>
                <div className="title">What people are saying</div>
              </div>
              <div className="row" style={{ gap: 6 }}>
                <a className="btn btn-outline btn-sm" href={redditUrl} target="_blank" rel="noreferrer">
                  <ExternalLink size={14} />
                  Reddit
                </a>
                <a className="btn btn-outline btn-sm" href={webUrl} target="_blank" rel="noreferrer">
                  <Globe size={14} />
                  Web
                </a>
                <button
                  className="btn btn-outline btn-sm"
                  type="button"
                  disabled={scanningForum}
                  onClick={onLiveForumScan}
                >
                  <Search size={14} />
                  {scanningForum ? 'Scanning…' : 'Live scan'}
                </button>
                <button className="btn btn-primary btn-sm" type="button" onClick={onOpenPasteForum}>
                  <Plus size={14} />
                  Paste a post
                </button>
              </div>
            </div>

            {p.signals.length > 0 && (
              <div className="consensus">
                <div style={{ fontWeight: 700, fontSize: 14 }}>{consensus.line}</div>
                <div className="row mt8" style={{ gap: 6 }}>
                  {consensus.faq > 0 && (
                    <span className="pill tone-halal">{consensus.faq} brand FAQ</span>
                  )}
                  {consensus.quoted > 0 && (
                    <span className="pill tone-ok">
                      {consensus.quoted} quoted brand repl{consensus.quoted === 1 ? 'y' : 'ies'}
                    </span>
                  )}
                  {consensus.conflict && (
                    <span className="pill tone-haram">Reports disagree</span>
                  )}
                  {consensus.nonUs > 0 && (
                    <span className="pill tone-doubt">{consensus.nonUs} non-U.S. post</span>
                  )}
                </div>
                <div className="small muted mt8">
                  Community posts never change the verdict on their own — use them as leads, then confirm with the brand.
                </div>
              </div>
            )}

            {p.signals.length ? (
              p.signals.map((s) => {
                const det = SIG_DET[s.determination] || SIG_DET.unclear;
                return (
                  <div className="sig" key={s.id}>
                    <div className="row between" style={{ alignItems: 'flex-start' }}>
                      <div>
                        <div className="sig-title">{s.title}</div>
                        <div className="sig-meta">
                          {s.source}
                          {s.author ? ` · ${s.author}` : ''} · {fmtDate(s.posted_at)}
                        </div>
                      </div>
                      <span className={`pill tone-${det.tone}`}>{det.label}</span>
                    </div>

                    {s.region === 'non_us' && (
                      <div className="notice tone-doubt mt12">
                        <Globe size={16} style={{ flex: 'none', marginTop: 2 }} />
                        <div>
                          <b>Different country.</b> {s.region_notes}
                        </div>
                      </div>
                    )}

                    {s.excerpt && <p className="sig-body">{s.excerpt}</p>}

                    <div className="sig-tags">
                      <span className="tag">{TIER_LABEL[s.tier] || 'Community'}</span>
                      <span className="tag">{freshnessLabel(s.posted_at)}</span>
                      {s.region === 'us' && <span className="tag">U.S. product</span>}
                      {s.ingredients.map((ing) => (
                        <span key={ing} className="tag">
                          {ing}
                        </span>
                      ))}
                      {s.url && (
                        <a className="tag" href={s.url} target="_blank" rel="noreferrer">
                          <ExternalLink size={12} />
                          Source
                        </a>
                      )}
                    </div>

                    <div className="mt8" style={{ textAlign: 'right' }}>
                      <button
                        className="btn btn-ghost btn-sm"
                        type="button"
                        onClick={() => onOpenDraft('quick', s.id)}
                      >
                        <Mail size={14} />
                        Ask brand to confirm
                      </button>
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="empty small">
                No saved forum posts for this item yet. Tap <b>Live scan</b> or <b>Reddit</b> above, or paste a post you found.
              </div>
            )}
          </section>
        </div>

        <aside className="side stack">
          <section className="card">
            <div className="card-head" style={{ paddingBottom: 4 }}>
              <div className="eyebrow">Next steps</div>
            </div>
            <div className="actions">
              <button
                className="action primary"
                type="button"
                onClick={() => onOpenDraft('full')}
              >
                <span className="action-ic">
                  <Mail size={18} />
                </span>
                <span>
                  <div className="action-t">Ask the brand</div>
                  <div className="action-d">
                    {ev.unresolvedFlags.length
                      ? `Draft a short email about the ${ev.unresolvedFlags.length} doubtful ingredient${ev.unresolvedFlags.length === 1 ? '' : 's'}. You send it.`
                      : 'Draft a quick confirmation email. You send it.'}
                  </div>
                </span>
                <ChevronRight size={17} className="chev" />
              </button>

              <button className="action" type="button" onClick={() => onOpenLog()}>
                <span className="action-ic">
                  <Reply size={18} />
                </span>
                <span>
                  <div className="action-t">Log the brand&apos;s reply</div>
                  <div className="action-d">Record what they said; the verdict updates instantly.</div>
                </span>
                <ChevronRight size={17} className="chev" />
              </button>

              <button className="action" type="button" onClick={onCompareLabel}>
                <span className="action-ic">
                  <FileText size={18} />
                </span>
                <span>
                  <div className="action-t">Compare a new label</div>
                  <div className="action-d">Catch silent recipe changes on the box in your hand.</div>
                </span>
                <ChevronRight size={17} className="chev" />
              </button>

              <button className="action" type="button" onClick={onSimulateChange}>
                <span className="action-ic">
                  <FlaskConical size={18} />
                </span>
                <span>
                  <div className="action-t">Demo: simulate a recipe change</div>
                  <div className="action-d">Adds two ingredients to see the warning in action.</div>
                </span>
                <ChevronRight size={17} className="chev" />
              </button>
            </div>
          </section>

          <section className="card">
            <div className="card-head" style={{ paddingBottom: 4 }}>
              <div>
                <div className="eyebrow">Record</div>
                <div className="title" style={{ fontSize: 18 }}>
                  Replies &amp; emails
                </div>
              </div>
            </div>
            {timeline.length ? (
              <div className="tl">
                {timeline.map((t, i) => (
                  <div key={i} className={`tl-item tone-${t.tone}`}>
                    <div className="tl-t">{t.title}</div>
                    <div className="tl-d">{t.meta}</div>
                    {t.text && <div className="tl-x">{t.text}</div>}
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty small">No replies logged yet.</div>
            )}
          </section>

          <section className="card card-pad">
            <div className="eyebrow">How we found it</div>
            <div className="small mt8" style={{ display: 'grid', gap: 6 }}>
              <div className="row between">
                <span>Your saved products</span>
                <b style={{ color: p.source.kind === 'seed' || p.source.kind === 'manual' ? 'var(--halal)' : 'var(--ink-3)' }}>
                  {p.source.kind === 'seed' || p.source.kind === 'manual' ? 'Found' : 'Saved'}
                </b>
              </div>
              <div className="row between">
                <span className="muted">Offline U.S. catalog · {CACHE_COUNT} products</span>
                {p.source.kind === 'off_cache' && <b style={{ color: 'var(--halal)' }}>Found</b>}
              </div>
              <div className="row between">
                <span className="muted">Open Food Facts · live search</span>
                {p.source.kind === 'off_live' && <b style={{ color: 'var(--halal)' }}>Found</b>}
              </div>
              <div className="row between">
                <span className="muted">USDA FoodData Central · live search</span>
                {p.source.kind === 'usda_live' && <b style={{ color: 'var(--halal)' }}>Found</b>}
              </div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
