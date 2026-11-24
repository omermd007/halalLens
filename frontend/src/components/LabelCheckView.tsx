import { useRef, useState } from 'react';
import { Camera, Check, RefreshCw, Search } from 'lucide-react';
import { computeDiff, fingerprint, matchRules } from '../engine/evaluator';
import { LABEL_PRESETS } from '../engine/seeds';
import type { ProductEvaluation, RuleMatch } from '../engine/types';

export function LabelCheckView({
  evals,
  initialProductId,
  onSaveLabel,
  onToast,
}: {
  evals: ProductEvaluation[];
  initialProductId?: string | null;
  onSaveLabel: (productId: string, rawText: string) => void;
  onToast: (msg: string) => void;
}) {
  const [selectedProductId, setSelectedProductId] = useState<string>(initialProductId || '');
  const [text, setText] = useState<string>(() => {
    if (!initialProductId) return '';
    return evals.find((e) => e.p.id === initialProductId)?.raw || '';
  });
  const [result, setResult] = useState<{
    raw: string;
    matches: RuleMatch[];
    diff: { added: string[]; removed: string[] } | null;
    sameLabel: boolean;
  } | null>(null);
  const [ocrStatus, setOcrStatus] = useState<{ running: boolean; progress: number; label: string }>({
    running: false,
    progress: 0,
    label: '',
  });
  const ocrFileRef = useRef<HTMLInputElement>(null);

  const selectedEval = evals.find((e) => e.p.id === selectedProductId);

  function analyze(rawOverride?: string) {
    const raw = (rawOverride ?? text).trim();
    if (!raw) {
      onToast('Paste or snap an ingredient list first.');
      return;
    }
    const matches = matchRules(raw);
    let diff: { added: string[]; removed: string[] } | null = null;
    let sameLabel = false;
    if (selectedEval && selectedEval.raw) {
      if (fingerprint(selectedEval.raw) === fingerprint(raw)) {
        sameLabel = true;
      } else {
        diff = computeDiff(selectedEval.raw, raw);
      }
    }
    setResult({ raw, matches, diff, sameLabel });
  }

  async function handleOcrPhoto(file: File) {
    setOcrStatus({ running: true, progress: 10, label: 'Loading OCR engine…' });
    try {
      const { createWorker } = await import('tesseract.js');
      const worker = await createWorker('eng', 1, {
        logger: (m: { status?: string; progress?: number }) => {
          if (typeof m.progress === 'number') {
            setOcrStatus({
              running: true,
              progress: Math.max(12, Math.round(m.progress * 100)),
              label: m.status === 'recognizing text' ? 'Reading ingredients from photo…' : 'Preparing OCR…',
            });
          }
        },
      });
      const res = await worker.recognize(file);
      await worker.terminate();
      const extracted = (res.data.text || '').replace(/\s+/g, ' ').trim();
      setOcrStatus({ running: false, progress: 0, label: '' });
      if (!extracted) {
        onToast("Couldn't read text from that photo. Try a closer, flatter shot.");
        return;
      }
      setText(extracted);
      analyze(extracted);
      onToast('Ingredient text extracted from photo.');
    } catch {
      setOcrStatus({ running: false, progress: 0, label: '' });
      onToast('OCR failed — try a clearer photo or paste the text directly.');
    }
  }

  return (
    <div className="stack fadein">
      <div>
        <h1 className="page-title">Check a label</h1>
        <p className="page-sub">
          Snap a photo of the package&apos;s ingredient list or paste the text. We&apos;ll flag doubtful ingredients and spot silent recipe changes.
        </p>
      </div>

      <section className="card card-pad">
        <div className="ocr-box">
          <div>
            <div style={{ fontWeight: 700, fontSize: 15 }}>Read ingredients from a photo (OCR)</div>
            <div className="small muted">
              Runs privately on your device — hold the phone close and flat over the &ldquo;Ingredients:&rdquo; block.
            </div>
          </div>
          <div>
            <input
              ref={ocrFileRef}
              type="file"
              accept="image/*"
              capture="environment"
              className="sr"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = '';
                if (file) void handleOcrPhoto(file);
              }}
            />
            <button
              className="btn btn-primary btn-sm"
              type="button"
              disabled={ocrStatus.running}
              onClick={() => ocrFileRef.current?.click()}
            >
              <Camera size={15} />
              {ocrStatus.running ? `Reading (${ocrStatus.progress}%)…` : 'Snap or upload label photo'}
            </button>
          </div>
        </div>

        {ocrStatus.running && (
          <div className="mt12">
            <div className="small muted">{ocrStatus.label}</div>
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${ocrStatus.progress}%` }} />
            </div>
          </div>
        )}

        <div className="field mt16">
          <label className="field-l" htmlFor="label-product">
            Compare against a saved product (optional)
          </label>
          <select
            id="label-product"
            className="select"
            value={selectedProductId}
            onChange={(e) => {
              const id = e.target.value;
              setSelectedProductId(id);
              const hit = evals.find((x) => x.p.id === id);
              if (hit && !text.trim()) setText(hit.raw);
            }}
          >
            <option value="">Standalone check — don&apos;t link to a product</option>
            {evals.map((e) => (
              <option key={e.p.id} value={e.p.id}>
                {e.p.brand} — {e.p.name} ({e.p.upc})
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label className="field-l" htmlFor="label-text">
            Ingredient list
          </label>
          <textarea
            id="label-text"
            className="textarea"
            rows={5}
            placeholder="e.g. ENRICHED WHEAT FLOUR, CHEDDAR CHEESE (MILK, CHEESE CULTURE, SALT, ENZYMES), WHEY, MONO- AND DIGLYCERIDES..."
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="chips mt8">
            <span className="small muted" style={{ alignSelf: 'center' }}>
              Try a sample:
            </span>
            {LABEL_PRESETS.map((preset) => (
              <button
                key={preset.name}
                className="chip"
                type="button"
                onClick={() => {
                  setText(preset.text);
                  analyze(preset.text);
                }}
              >
                {preset.name}
              </button>
            ))}
          </div>
        </div>

        <div className="row mt16">
          <button id="btn-analyze" className="btn btn-primary" type="button" onClick={() => analyze()}>
            <Search size={16} />
            Check ingredients
          </button>
          {selectedEval && text.trim() && (
            <button
              id="btn-save-label"
              className="btn btn-outline"
              type="button"
              onClick={() => onSaveLabel(selectedEval.p.id, text.trim())}
            >
              <Check size={16} />
              Save as new label for {selectedEval.p.brand}
            </button>
          )}
        </div>
      </section>

      {result && (
        <section id="label-result" className="card fadein">
          <div className="card-head">
            <div>
              <div className="eyebrow">Result</div>
              <div className="title">
                {result.matches.length
                  ? `${result.matches.length} ingredient${result.matches.length === 1 ? '' : 's'} flagged`
                  : 'No doubtful ingredients found'}
              </div>
            </div>
            <span className="tag mono">Label ID {fingerprint(result.raw)}</span>
          </div>

          {result.sameLabel && selectedEval && (
            <div className="notice tone-ok" style={{ margin: '0 20px 16px' }}>
              <Check size={16} style={{ flex: 'none', marginTop: 2 }} />
              <div>
                Matches the saved label for <b>{selectedEval.p.brand} {selectedEval.p.name}</b> — no recipe change.
              </div>
            </div>
          )}

          {result.diff && selectedEval && (
            <div className="drift" style={{ margin: '0 20px 16px' }}>
              <div className="drift-title">
                <RefreshCw size={15} />
                Different from the saved label for {selectedEval.p.brand} {selectedEval.p.name}
              </div>
              <div className="chips mt8">
                {result.diff.added.map((x) => (
                  <span key={`a-${x}`} className="diffchip diff-add">
                    + {x}
                  </span>
                ))}
                {result.diff.removed.map((x) => (
                  <span key={`r-${x}`} className="diffchip diff-rem">
                    − {x}
                  </span>
                ))}
              </div>
            </div>
          )}

          {result.matches.length ? (
            result.matches.map((m) => {
              const tone =
                m.risk === 'haram' || m.risk === 'meat'
                  ? 'haram'
                  : m.safe
                    ? 'ok'
                    : 'doubt';
              const badge =
                m.risk === 'haram'
                  ? 'Not halal'
                  : m.risk === 'meat'
                    ? 'Needs halal cert'
                    : m.safe
                      ? 'Label says OK'
                      : 'Doubtful';
              return (
                <div key={m.rule.id} className={`ing tone-${tone}`}>
                  <span className="ing-dot" />
                  <div>
                    <div className="ing-top">
                      <div className="ing-name">
                        {m.rule.name}
                        {m.parent && <span>in {m.parent}</span>}
                      </div>
                      <span className="pill">{badge}</span>
                    </div>
                    <p className="ing-plain">{m.rule.plain}</p>
                    <div className="small muted mt8">Matched: “{m.token}”</div>
                  </div>
                </div>
              );
            })
          ) : (
            <div className="empty">Everything in this list looks clear of the 19 watched ingredient families.</div>
          )}
        </section>
      )}
    </div>
  );
}
