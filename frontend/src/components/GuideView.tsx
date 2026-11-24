import { useMemo, useState } from 'react';
import { ExternalLink, Plus, Search } from 'lucide-react';
import { fmtDate } from '../engine/evaluator';
import { RULES } from '../engine/rules';
import type { BrandPolicyRecord } from '../engine/types';

export function GuideView({
  policies,
  onOpenAddPolicy,
}: {
  policies: BrandPolicyRecord[];
  onOpenAddPolicy: () => void;
}) {
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return RULES;
    return RULES.filter((r) =>
      `${r.name} ${r.aliases.join(' ')} ${r.plain} ${r.context}`.toLowerCase().includes(q)
    );
  }, [query]);

  return (
    <div className="stack fadein">
      <div>
        <h1 className="page-title">Ingredient guide</h1>
        <p className="page-sub">
          The {RULES.length} ingredient families HalalLens checks on U.S. labels, in plain language — plus brand-wide policies you&apos;ve saved.
        </p>
      </div>

      <label className="field-search" style={{ maxWidth: 420, background: 'var(--surface)' }}>
        <Search size={16} color="#79837C" />
        <input
          id="guide-search"
          placeholder="Search e.g. rennet, glycerin, carmine"
          aria-label="Search ingredients"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>

      <div id="guide-list" className="guide-grid">
        {filtered.length ? (
          filtered.map((r) => {
            const tone = r.risk === 'haram' || r.risk === 'meat' ? 'haram' : 'doubt';
            const badge =
              r.risk === 'haram' ? 'Not halal' : r.risk === 'meat' ? 'Needs halal cert' : 'Doubtful';
            return (
              <div key={r.id} className={`card card-pad tone-${tone}`}>
                <div className="row between" style={{ alignItems: 'flex-start' }}>
                  <div className="ing-name">{r.name}</div>
                  <span className="pill">{badge}</span>
                </div>
                <p className="ing-plain mt8">{r.plain}</p>
                <div className="small muted mt8">{r.context}</div>
                <div className="small mt8">
                  <b>Kosher / vegan:</b> {r.kosher}
                </div>
              </div>
            );
          })
        ) : (
          <div className="card empty">No matching ingredient rules.</div>
        )}
      </div>

      <section className="card">
        <div className="card-head">
          <div>
            <div className="eyebrow">Brand-wide statements</div>
            <div className="title">Brand policies</div>
            <div className="small muted">A cited brand FAQ can cover every product from that brand.</div>
          </div>
          <button className="btn btn-outline btn-sm" type="button" onClick={onOpenAddPolicy}>
            <Plus size={15} />
            Add policy
          </button>
        </div>

        <div className="plist">
          {policies.length ? (
            policies.map((bp) => (
              <div key={bp.id} className="sig">
                <div className="row between">
                  <div className="sig-title">{bp.brand}</div>
                  <span className="pill tone-ok">Active until {fmtDate(bp.expires_at)}</span>
                </div>
                <p className="sig-body">{bp.scope}</p>
                <div className="sig-tags">
                  {bp.ingredients.map((i) => (
                    <span key={i} className="tag">
                      {i}
                    </span>
                  ))}
                  {bp.source_url && (
                    <a className="tag" href={bp.source_url} target="_blank" rel="noreferrer">
                      <ExternalLink size={12} />
                      Brand FAQ
                    </a>
                  )}
                </div>
              </div>
            ))
          ) : (
            <div className="empty small">No brand policies saved yet.</div>
          )}
        </div>
      </section>
    </div>
  );
}
