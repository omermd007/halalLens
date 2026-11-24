import { useMemo, useState } from 'react';
import {
  AlertTriangle,
  Camera,
  Check,
  FileText,
  Image as ImageIcon,
  Minus,
  Plus,
  ScanLine,
  Search,
  X,
} from 'lucide-react';
import { CACHE_COUNT, pickCacheExamples } from '../engine/store';
import type { HistoryItem, LookupTrace, ProductEvaluation, StatusKey } from '../engine/types';
import { ProductRow } from './StatusIcon';

const FILTER_OPTIONS: Array<{ id: 'all' | StatusKey; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'animal_or_haram', label: 'Not halal' },
  { id: 'mushbooh_needs_check', label: 'Doubtful' },
  { id: 'formulation_changed', label: 'Changed' },
  { id: 'verified_plant_or_microbial', label: 'Looks OK' },
  { id: 'certified_halal', label: 'Certified' },
];

const CURATED_CHIPS = [
  { name: 'Kraft Mac & Cheese', upc: '021000658831', tone: 'doubt' },
  { name: "Annie's Shells", upc: '013562300143', tone: 'ok' },
  { name: 'Goodles Cheddy Mac', upc: '850031990012', tone: 'changed' },
  { name: 'Saffron Road Tikka', upc: '815652010014', tone: 'halal' },
  { name: 'Haribo Goldbears', upc: '042238302124', tone: 'haram' },
  { name: 'Oreo', upc: '044000032029', tone: 'doubt' },
  { name: 'Cabot Cheddar', upc: '078354701025', tone: 'ok' },
] as const;

export function ScanView({
  evals,
  history,
  showExamples,
  upcDraft,
  onUpcChange,
  onLookup,
  onOpenCamera,
  onPickPhoto,
  onGoLabel,
  onOpenProduct,
  onAddProduct,
  trace,
  onDismissTrace,
  shake,
}: {
  evals: ProductEvaluation[];
  history: HistoryItem[];
  showExamples: boolean;
  upcDraft: string;
  onUpcChange: (val: string) => void;
  onLookup: (upc?: string) => void;
  onOpenCamera: () => void;
  onPickPhoto: () => void;
  onGoLabel: () => void;
  onOpenProduct: (id: string) => void;
  onAddProduct: (upc: string) => void;
  trace: LookupTrace | null;
  onDismissTrace: () => void;
  shake: boolean;
}) {
  const [filter, setFilter] = useState<'all' | StatusKey>('all');
  const [search, setSearch] = useState('');

  const cacheChips = useMemo(() => pickCacheExamples(6), []);

  const filteredEvals = useMemo(() => {
    const q = search.trim().toLowerCase();
    return evals.filter((e) => {
      if (filter !== 'all' && e.status !== filter) return false;
      if (!q) return true;
      return `${e.p.brand} ${e.p.name} ${e.p.upc} ${e.p.category}`.toLowerCase().includes(q);
    });
  }, [evals, filter, search]);

  const evalById = useMemo(() => new Map(evals.map((e) => [e.p.id, e])), [evals]);

  return (
    <div className="stack fadein">
      <section className="hero">
        <div className="hero-in">
          <div className="hero-eyebrow">Halal ingredient check · U.S. groceries</div>
          <h1>
            Is it halal?
            <span>Scan it and see what&apos;s inside.</span>
          </h1>
          <p>
            We check every ingredient for enzymes, gelatin, whey, emulsifiers, meat and alcohol — then help you confirm the doubtful ones with the brand.
          </p>

          <div className={`searchbox${shake ? ' shake' : ''}`}>
            <ScanLine size={20} color="#79837C" />
            <input
              id="upc-input"
              inputMode="numeric"
              autoComplete="off"
              enterKeyHint="search"
              placeholder="Barcode number"
              aria-label="Barcode number (UPC)"
              value={upcDraft}
              onChange={(e) => onUpcChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  onLookup();
                }
              }}
            />
            <button id="btn-lookup" className="btn btn-accent" type="button" onClick={() => onLookup()}>
              Check
            </button>
          </div>

          <div className="hero-actions">
            <button id="btn-camera" className="btn btn-glass" type="button" onClick={onOpenCamera}>
              <Camera size={17} />
              Scan with camera
            </button>
            <button id="btn-photo" className="btn btn-glass" type="button" onClick={onPickPhoto}>
              <ImageIcon size={17} />
              Use a barcode photo
            </button>
            <button id="btn-to-label" className="btn btn-glass" type="button" onClick={onGoLabel}>
              <FileText size={17} />
              Scan or paste a label
            </button>
          </div>

          <div className="hero-hint">
            Works with 12-digit UPC and 13-digit EAN codes · searches {CACHE_COUNT} saved U.S. products offline, plus Open Food Facts &amp; USDA live.
          </div>
        </div>
      </section>

      {trace && (
        <div className="stack">
          <section className="card lookup">
            <div className="lookup-head">
              <div>
                <div className="eyebrow">Looking up barcode</div>
                <div className="lookup-code">{trace.digits}</div>
              </div>
              <button className="btn btn-ghost btn-sm" type="button" onClick={onDismissTrace}>
                <X size={15} />
                Dismiss
              </button>
            </div>

            <ul className="steps">
              {trace.steps.map((s) => (
                <li className="step" key={s.label}>
                  <span className={`ind ${s.state}`}>
                    {s.state === 'hit' && <Check size={13} />}
                    {s.state === 'miss' && <Minus size={13} />}
                    {s.state === 'blocked' && <AlertTriangle size={12} />}
                  </span>
                  <div>
                    <div className="step-label">{s.label}</div>
                    <div className="step-detail">{s.detail}</div>
                  </div>
                  <span
                    className="step-st"
                    style={{
                      color:
                        s.state === 'hit'
                          ? 'var(--halal)'
                          : s.state === 'blocked'
                            ? 'var(--doubt)'
                            : 'var(--ink-3)',
                    }}
                  >
                    {s.state === 'hit'
                      ? 'Found'
                      : s.state === 'run'
                        ? 'Checking…'
                        : s.state === 'miss'
                          ? 'No match'
                          : s.state === 'blocked'
                            ? 'Offline'
                            : ''}
                  </span>
                </li>
              ))}
            </ul>
          </section>

          {trace.notFound && (
            <section className="card card-pad">
              <div className="row" style={{ alignItems: 'flex-start', gap: 14 }}>
                <span className="prow-ic tone-neutral" style={{ width: 42, height: 42 }}>
                  <Search size={19} />
                </span>
                <div style={{ flex: 1, minWidth: 200 }}>
                  <div style={{ fontWeight: 700, fontSize: 16 }}>
                    We couldn&apos;t find <span className="mono">{trace.digits}</span>
                  </div>
                  <div className="small muted mt8" style={{ marginTop: 4 }}>
                    It may be a store brand or a new item. Add it yourself by snapping or typing the ingredient list from the package.
                  </div>
                  <div className="row mt12">
                    <button
                      className="btn btn-primary btn-sm"
                      type="button"
                      onClick={() => onAddProduct(trace.digits)}
                    >
                      <Plus size={15} />
                      Add this product
                    </button>
                    <button className="btn btn-outline btn-sm" type="button" onClick={onGoLabel}>
                      <FileText size={15} />
                      Check a label instead
                    </button>
                  </div>
                </div>
              </div>
            </section>
          )}
        </div>
      )}

      {showExamples && (
        <section className="card card-pad">
          <div className="eyebrow">Try it</div>
          <div className="title">Tap a product to test the lookup</div>
          <div className="small muted mt8">Examples with brand replies, forum posts &amp; recipe changes</div>
          <div className="chips mt8">
            {CURATED_CHIPS.map((c) => (
              <button
                key={c.upc}
                className={`chip tone-${c.tone}`}
                type="button"
                onClick={() => onLookup(c.upc)}
              >
                <span className="chip-dot" />
                {c.name}
                <span className="mono">{c.upc}</span>
              </button>
            ))}
          </div>
          <div className="small muted mt16">Real U.S. products from Open Food Facts</div>
          <div className="chips mt8">
            {cacheChips.map((item) => (
              <button
                key={item.upc}
                className="chip"
                type="button"
                onClick={() => onLookup(item.upc)}
              >
                {item.name}
                <span className="mono">{item.upc}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      <div className="grid-2">
        <section className="card">
          <div className="card-head">
            <div>
              <div className="eyebrow">Your list</div>
              <div className="title">Saved products</div>
            </div>
            <label className="field-search" style={{ width: '100%', maxWidth: 230 }}>
              <Search size={15} color="#79837C" />
              <input
                id="plist-search"
                placeholder="Search brand or name"
                aria-label="Search saved products"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
          </div>
          <div className="chips" style={{ padding: '0 20px 14px' }}>
            {FILTER_OPTIONS.map((f) => (
              <button
                key={f.id}
                className={`chip${filter === f.id ? ' on' : ''}`}
                type="button"
                onClick={() => setFilter(f.id)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <div id="plist" className="plist">
            {filteredEvals.length ? (
              filteredEvals.map((ev) => <ProductRow key={ev.p.id} ev={ev} onOpen={onOpenProduct} />)
            ) : (
              <div className="empty">
                {evals.length === 0
                  ? 'No saved products yet. Scan a barcode or add one above.'
                  : 'No products match that filter.'}
              </div>
            )}
          </div>
        </section>

        <div className="stack">
          <section className="card">
            <div className="card-head">
              <div>
                <div className="eyebrow">History</div>
                <div className="title">Recently checked</div>
              </div>
            </div>
            <div className="plist">
              {history.length ? (
                history.slice(0, 6).map((h) => {
                  const ev = evalById.get(h.id);
                  if (!ev) return null;
                  return <ProductRow key={h.id} ev={ev} onOpen={onOpenProduct} />;
                })
              ) : (
                <div className="empty small">Products you look up will show here.</div>
              )}
            </div>
          </section>

          <section className="card card-pad">
            <div className="eyebrow">How it works</div>
            <div className="steps3 mt12" style={{ gridTemplateColumns: '1fr' }}>
              <div className="how">
                <span className="how-n">1</span>
                <h3>Scan or type a barcode</h3>
                <p>We find the product and its current ingredient list.</p>
              </div>
              <div className="how">
                <span className="how-n">2</span>
                <h3>See what&apos;s doubtful</h3>
                <p>Each ingredient is checked against 19 U.S. rule families and your strictness settings.</p>
              </div>
              <div className="how">
                <span className="how-n">3</span>
                <h3>Confirm with the brand</h3>
                <p>Draft a short email, log the reply, and we&apos;ll warn you if the recipe changes later.</p>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
