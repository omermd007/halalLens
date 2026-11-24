import { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  Check,
  Copy,
  Download,
  ExternalLink,
  Image as ImageIcon,
  Lock,
  Plus,
  RotateCcw,
  Upload,
  X,
} from 'lucide-react';
import { startCameraBarcodeScan, type CameraController } from '../engine/barcodeScanner';
import { addMonths, buildOutreachDraft, parseForumPost, todayISO } from '../engine/evaluator';
import { FORUM_SAMPLES } from '../engine/seeds';
import type {
  AppMode,
  BrandPolicyRecord,
  Determination,
  ForumSignalItem,
  ProductEvaluation,
  ProductRecord,
  StrictnessSettings,
} from '../engine/types';

function SheetShell({
  title,
  sub,
  onClose,
  children,
  footer,
}: {
  title: string;
  sub?: string;
  onClose?: () => void;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <div
      className="sheet-bg"
      onClick={(e) => {
        if (e.target === e.currentTarget && onClose) onClose();
      }}
    >
      <div className="sheet" role="dialog" aria-modal="true" aria-label={title}>
        <div className="sheet-head">
          <div>
            <div className="title" style={{ fontSize: 20 }}>
              {title}
            </div>
            {sub && <div className="small muted mt8" style={{ marginTop: 2 }}>{sub}</div>}
          </div>
          {onClose && (
            <button className="icon-btn" type="button" aria-label="Close" onClick={onClose}>
              <X size={18} />
            </button>
          )}
        </div>
        <div className="sheet-body">{children}</div>
        <div className="sheet-foot">{footer}</div>
      </div>
    </div>
  );
}

export function CameraScanSheet({
  onCode,
  onPickPhoto,
  onClose,
}: {
  onCode: (code: string) => void;
  onPickPhoto: () => void;
  onClose: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [message, setMessage] = useState<string>('Starting camera…');

  useEffect(() => {
    let controller: CameraController | null = null;
    let active = true;
    const videoEl = videoRef.current;
    if (!videoEl) return;

    void startCameraBarcodeScan(
      videoEl,
      (code) => {
        if (!active) return;
        onCode(code);
      },
      (err) => {
        if (!active) return;
        setMessage(err);
      }
    ).then((ctrl) => {
      controller = ctrl;
      if (active) {
        setMessage((prev) => (prev === 'Starting camera…' ? '' : prev));
      } else {
        ctrl.stop();
      }
    });

    return () => {
      active = false;
      controller?.stop();
    };
  }, [onCode]);

  return (
    <SheetShell
      title="Scan a barcode"
      sub="Point your camera at the UPC barcode on the package"
      onClose={onClose}
      footer={
        <>
          <button
            className="btn btn-outline"
            type="button"
            onClick={() => {
              onClose();
              onPickPhoto();
            }}
          >
            <ImageIcon size={16} />
            Use a photo instead
          </button>
          <button className="btn btn-ghost" type="button" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="cam">
        <video ref={videoRef} playsInline muted autoPlay />
        <div className="cam-guide" />
        <div className="cam-laser" />
        {message && <div className="cam-msg">{message}</div>}
      </div>
      <div className="small muted mt12">
        Works on iPhone Safari, Android Chrome, and desktop over HTTPS. If lighting is dim, tap <b>Use a photo instead</b>.
      </div>
    </SheetShell>
  );
}

export function DraftEmailSheet({
  ev,
  allProducts,
  mode,
  sigId,
  onMarkSent,
  onClose,
  onToast,
}: {
  ev: ProductEvaluation;
  allProducts: ProductRecord[];
  mode: 'full' | 'quick';
  sigId?: string;
  onMarkSent: (to: string, subject: string, body: string, mode: 'full' | 'quick') => void;
  onClose: () => void;
  onToast: (msg: string) => void;
}) {
  const initial = buildOutreachDraft(ev, allProducts, mode, sigId);
  const [to, setTo] = useState(initial.to);
  const [subject, setSubject] = useState(initial.subject);
  const [body, setBody] = useState(initial.body);

  const mailtoHref = `mailto:${encodeURIComponent(to)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;

  return (
    <SheetShell
      title="Ask the brand"
      sub={`${ev.p.brand} · ${ev.p.name} — HalalLens drafts it, you send it`}
      onClose={onClose}
      footer={
        <>
          <button
            className="btn btn-outline"
            type="button"
            onClick={() => {
              void navigator.clipboard?.writeText(`Subject: ${subject}\n\n${body}`).then(
                () => onToast('Copied email to clipboard.'),
                () => onToast('Select and copy the message text.')
              );
            }}
          >
            <Copy size={15} />
            Copy
          </button>
          <a className="btn btn-outline" href={mailtoHref}>
            <ExternalLink size={15} />
            Open in email app
          </a>
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => {
              onMarkSent(to, subject, body, mode);
              onClose();
            }}
          >
            <Check size={15} />
            I sent it
          </button>
        </>
      }
    >
      {initial.warnings.map((w) => (
        <div key={w} className="notice tone-doubt" style={{ marginBottom: 14 }}>
          <AlertTriangle size={16} style={{ flex: 'none', marginTop: 2 }} />
          <div>{w}</div>
        </div>
      ))}

      <div className="field">
        <label className="field-l" htmlFor="d-to">
          Brand email
        </label>
        <input
          id="d-to"
          className="input"
          value={to}
          placeholder="Paste the brand's consumer care email"
          onChange={(e) => setTo(e.target.value)}
        />
        {ev.p.contact_url && (
          <div className="field-h">
            Or use their{' '}
            <a href={ev.p.contact_url} target="_blank" rel="noreferrer">
              contact form
            </a>
            .
          </div>
        )}
      </div>

      <div className="field">
        <label className="field-l" htmlFor="d-subj">
          Subject
        </label>
        <input
          id="d-subj"
          className="input"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
        />
      </div>

      <div className="field">
        <label className="field-l" htmlFor="d-body">
          Message
        </label>
        <textarea
          id="d-body"
          className="textarea"
          rows={9}
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
      </div>
    </SheetShell>
  );
}

export function LogReplySheet({
  ev,
  initialIngredient,
  onSave,
  onClose,
}: {
  ev: ProductEvaluation;
  initialIngredient?: string;
  onSave: (payload: {
    ingredient: string;
    determination: Determination;
    channel: string;
    date: string;
    excerpt: string;
    lot_code: string | null;
  }) => void;
  onClose: () => void;
}) {
  const options = ev.flags.length
    ? ev.flags
    : [];
  const defaultIng = initialIngredient || ev.unresolvedFlags[0]?.id || options[0]?.id || 'enzymes';
  const [ingredient, setIngredient] = useState(defaultIng);
  const selectedFlag = options.find((f) => f.id === ingredient);
  const isMeat = selectedFlag?.risk === 'meat';
  const [determination, setDetermination] = useState<Determination>(
    isMeat ? 'halal_slaughter' : 'plant_or_microbial'
  );
  const [channel, setChannel] = useState('email');
  const [date, setDate] = useState(todayISO());
  const [excerpt, setExcerpt] = useState('');
  const [lotCode, setLotCode] = useState(ev.cur?.lot_code || '');

  const choices: Array<{ value: Determination; tone: string; title: string; desc: string }> = isMeat
    ? [
        {
          value: 'halal_slaughter',
          tone: 'ok',
          title: 'Confirmed halal (zabiha) slaughter',
          desc: 'Brand confirmed halal slaughter / certification for this product.',
        },
        {
          value: 'animal_or_haram',
          tone: 'haram',
          title: 'Not halal / conventional slaughter',
          desc: 'Marks the product as not halal.',
        },
      ]
    : [
        {
          value: 'plant_or_microbial',
          tone: 'ok',
          title: 'Plant, microbial or synthetic',
          desc: 'No animal source. Turns the ingredient green.',
        },
        {
          value: 'varies_by_supplier',
          tone: 'doubt',
          title: 'It depends on the supplier or plant',
          desc: "Can't be guaranteed — stays doubtful.",
        },
        {
          value: 'animal_or_haram',
          tone: 'haram',
          title: 'Animal-derived',
          desc: 'Marks the product as not halal.',
        },
      ];

  return (
    <SheetShell
      title="Log the brand's reply"
      sub={`${ev.p.brand} · ${ev.p.name}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => {
              onSave({
                ingredient,
                determination,
                channel,
                date,
                excerpt: excerpt.trim(),
                lot_code: lotCode.trim() || null,
              });
              onClose();
            }}
          >
            <Check size={15} />
            Save reply
          </button>
        </>
      }
    >
      <div className="field">
        <label className="field-l" htmlFor="r-ing">
          Which ingredient?
        </label>
        <select
          id="r-ing"
          className="select"
          value={ingredient}
          onChange={(e) => {
            const next = e.target.value;
            setIngredient(next);
            const fl = options.find((f) => f.id === next);
            setDetermination(fl?.risk === 'meat' ? 'halal_slaughter' : 'plant_or_microbial');
          }}
        >
          {options.length ? (
            options.map((f) => (
              <option key={f.id} value={f.id}>
                {f.rule.name}
              </option>
            ))
          ) : (
            <option value="enzymes">enzymes</option>
          )}
        </select>
      </div>

      <div className="field">
        <div className="field-l">What did they say?</div>
        <div className="opts">
          {choices.map((c) => (
            <label
              key={c.value}
              className={`opt tone-${c.tone}${determination === c.value ? ' checked' : ''}`}
            >
              <input
                type="radio"
                name="r-det"
                value={c.value}
                checked={determination === c.value}
                onChange={() => setDetermination(c.value)}
              />
              <span>
                <div className="opt-t">{c.title}</div>
                <div className="opt-d">{c.desc}</div>
              </span>
            </label>
          ))}
        </div>
      </div>

      <div className="opts opts-2 mt12">
        <div className="field">
          <label className="field-l" htmlFor="r-ch">
            How
          </label>
          <select id="r-ch" className="select" value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="email">Email</option>
            <option value="phone">Phone call</option>
            <option value="chat">Web chat</option>
            <option value="faq">Brand FAQ</option>
          </select>
        </div>
        <div className="field" style={{ marginTop: 0 }}>
          <label className="field-l" htmlFor="r-date">
            Date of reply
          </label>
          <input
            id="r-date"
            type="date"
            className="input"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </div>
      </div>

      <div className="field">
        <label className="field-l" htmlFor="r-ex">
          Their words (paste the key sentence)
        </label>
        <textarea
          id="r-ex"
          className="textarea"
          rows={3}
          placeholder='e.g. "The enzymes used in this product are microbial."'
          value={excerpt}
          onChange={(e) => setExcerpt(e.target.value)}
        />
      </div>

      <div className="field">
        <label className="field-l" htmlFor="r-lot">
          Lot or plant code (optional)
        </label>
        <input
          id="r-lot"
          className="input"
          placeholder="Printed near the best-by date"
          value={lotCode}
          onChange={(e) => setLotCode(e.target.value)}
        />
      </div>
    </SheetShell>
  );
}

export function AddProductSheet({
  initialUpc,
  onSave,
  onClose,
}: {
  initialUpc: string;
  onSave: (payload: {
    upc: string;
    brand: string;
    name: string;
    ingredients: string;
    cert: string | null;
    kosher: string | null;
    vegan: boolean;
  }) => void;
  onClose: () => void;
}) {
  const [upc, setUpc] = useState(initialUpc);
  const [brand, setBrand] = useState('');
  const [name, setName] = useState('');
  const [ingredients, setIngredients] = useState('');
  const [cert, setCert] = useState('');
  const [kosher, setKosher] = useState('');
  const [vegan, setVegan] = useState(false);

  return (
    <SheetShell
      title="Add a product"
      sub="Save a barcode that wasn't in the online databases"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            type="button"
            disabled={!name.trim() || !brand.trim()}
            onClick={() => {
              onSave({
                upc: upc.trim(),
                brand: brand.trim(),
                name: name.trim(),
                ingredients: ingredients.trim(),
                cert: cert.trim() || null,
                kosher: kosher.trim() || null,
                vegan,
              });
              onClose();
            }}
          >
            <Plus size={15} />
            Save &amp; check
          </button>
        </>
      }
    >
      <div className="field">
        <label className="field-l" htmlFor="a-upc">
          Barcode (UPC / EAN)
        </label>
        <input id="a-upc" className="input mono" value={upc} onChange={(e) => setUpc(e.target.value)} />
      </div>
      <div className="opts opts-2 mt12">
        <div className="field">
          <label className="field-l" htmlFor="a-brand">
            Brand
          </label>
          <input
            id="a-brand"
            className="input"
            placeholder="e.g. Kirkland Signature"
            value={brand}
            onChange={(e) => setBrand(e.target.value)}
          />
        </div>
        <div className="field" style={{ marginTop: 0 }}>
          <label className="field-l" htmlFor="a-name">
            Product name
          </label>
          <input
            id="a-name"
            className="input"
            placeholder="e.g. Mild Cheddar"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
      </div>
      <div className="field">
        <label className="field-l" htmlFor="a-ing">
          Ingredient list (from package)
        </label>
        <textarea
          id="a-ing"
          className="textarea"
          rows={4}
          placeholder="Paste or type the ingredients printed on the box…"
          value={ingredients}
          onChange={(e) => setIngredients(e.target.value)}
        />
      </div>
      <div className="opts opts-2 mt12">
        <div className="field">
          <label className="field-l" htmlFor="a-cert">
            Halal certifier (if printed)
          </label>
          <input
            id="a-cert"
            className="input"
            placeholder="e.g. IFANCA, HFSAA"
            value={cert}
            onChange={(e) => setCert(e.target.value)}
          />
        </div>
        <div className="field" style={{ marginTop: 0 }}>
          <label className="field-l" htmlFor="a-kosher">
            Kosher symbol (if any)
          </label>
          <input
            id="a-kosher"
            className="input"
            placeholder="e.g. OU-D, OU-Pareve"
            value={kosher}
            onChange={(e) => setKosher(e.target.value)}
          />
        </div>
      </div>
      <label className="switch mt12">
        <input type="checkbox" checked={vegan} onChange={(e) => setVegan(e.target.checked)} />
        <span className="track" />
        <span>
          <div className="opt-t">Certified vegan</div>
          <div className="opt-d">Treats animal-origin risks as plant-based (still checks alcohol).</div>
        </span>
      </label>
    </SheetShell>
  );
}

export function PasteForumSheet({
  product,
  onSave,
  onClose,
}: {
  product: ProductRecord;
  onSave: (signal: ForumSignalItem) => void;
  onClose: () => void;
}) {
  const [title, setTitle] = useState('');
  const [source, setSource] = useState('r/halal');
  const [url, setUrl] = useState('');
  const [body, setBody] = useState('');

  return (
    <SheetShell
      title="Paste a forum or Reddit post"
      sub={`${product.brand} · ${product.name} — we extract the claim & check for non-U.S. recipes`}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            type="button"
            disabled={!body.trim() && !title.trim()}
            onClick={() => {
              const sig = parseForumPost(title.trim(), body.trim(), source.trim(), url.trim());
              onSave(sig);
              onClose();
            }}
          >
            <Plus size={15} />
            Analyze &amp; save post
          </button>
        </>
      }
    >
      <div className="chips" style={{ marginBottom: 12 }}>
        <span className="small muted" style={{ alignSelf: 'center' }}>
          Try sample:
        </span>
        {FORUM_SAMPLES.map((s) => (
          <button
            key={s.label}
            className="chip"
            type="button"
            onClick={() => {
              setTitle(s.title);
              setSource(s.source);
              setUrl(s.url);
              setBody(s.body);
            }}
          >
            {s.label}
          </button>
        ))}
      </div>

      <div className="field">
        <label className="field-l" htmlFor="f-title">
          Post title
        </label>
        <input id="f-title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div className="opts opts-2 mt12">
        <div className="field">
          <label className="field-l" htmlFor="f-src">
            Forum / subreddit
          </label>
          <input id="f-src" className="input" value={source} onChange={(e) => setSource(e.target.value)} />
        </div>
        <div className="field" style={{ marginTop: 0 }}>
          <label className="field-l" htmlFor="f-url">
            Link (optional)
          </label>
          <input id="f-url" className="input" value={url} onChange={(e) => setUrl(e.target.value)} />
        </div>
      </div>
      <div className="field">
        <label className="field-l" htmlFor="f-body">
          Post text
        </label>
        <textarea
          id="f-body"
          className="textarea"
          rows={5}
          placeholder="Paste the Reddit comment or forum post here…"
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
      </div>
    </SheetShell>
  );
}

export function AddPolicySheet({
  onSave,
  onClose,
}: {
  onSave: (policy: BrandPolicyRecord) => void;
  onClose: () => void;
}) {
  const [brand, setBrand] = useState('');
  const [scope, setScope] = useState('');
  const [url, setUrl] = useState('');
  const [ingredients, setIngredients] = useState('enzymes, cheese_culture, whey, cheese');

  return (
    <SheetShell
      title="Add a brand policy"
      sub="Apply a verified brand-wide FAQ to all products from that brand"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            type="button"
            disabled={!brand.trim() || !scope.trim()}
            onClick={() => {
              const today = todayISO();
              onSave({
                id: `bp_${Date.now().toString(36)}`,
                brand: brand.trim(),
                scope: scope.trim(),
                ingredients: ingredients
                  .split(',')
                  .map((x) => x.trim())
                  .filter(Boolean),
                determination: 'plant_or_microbial',
                source_url: url.trim(),
                excerpt: scope.trim(),
                checked_date: today,
                expires_at: addMonths(today, 12),
              });
              onClose();
            }}
          >
            <Plus size={15} />
            Save policy
          </button>
        </>
      }
    >
      <div className="field">
        <label className="field-l" htmlFor="bp-brand">
          Brand name
        </label>
        <input id="bp-brand" className="input" placeholder="e.g. Tillamook" value={brand} onChange={(e) => setBrand(e.target.value)} />
      </div>
      <div className="field">
        <label className="field-l" htmlFor="bp-scope">
          What does their policy say?
        </label>
        <textarea
          id="bp-scope"
          className="textarea"
          rows={3}
          placeholder="e.g. All retail cheddar blocks use non-animal microbial rennet."
          value={scope}
          onChange={(e) => setScope(e.target.value)}
        />
      </div>
      <div className="field">
        <label className="field-l" htmlFor="bp-ing">
          Covered rule IDs (comma-separated)
        </label>
        <input id="bp-ing" className="input mono" value={ingredients} onChange={(e) => setIngredients(e.target.value)} />
      </div>
      <div className="field">
        <label className="field-l" htmlFor="bp-url">
          Source FAQ link (optional)
        </label>
        <input id="bp-url" className="input" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />
      </div>
    </SheetShell>
  );
}

export function SettingsSheet({
  strict,
  usdaApiKey,
  showExamples,
  appMode,
  onSave,
  onExportBackup,
  onImportBackup,
  onClearExamples,
  onResetAll,
  onClose,
}: {
  strict: StrictnessSettings;
  usdaApiKey: string;
  showExamples: boolean;
  appMode: AppMode;
  onSave: (next: { strict: StrictnessSettings; usdaApiKey: string; showExamples: boolean }) => void;
  onExportBackup: () => void;
  onImportBackup: (file: File) => void;
  onClearExamples: () => void;
  onResetAll: () => void;
  onClose: () => void;
}) {
  const [localStrict, setLocalStrict] = useState<StrictnessSettings>(strict);
  const [localUsdaKey, setLocalUsdaKey] = useState(usdaApiKey);
  const [localShowExamples, setLocalShowExamples] = useState(showExamples);
  const importRef = useRef<HTMLInputElement>(null);

  function setPreset(preset: 'strict' | 'balanced') {
    if (preset === 'strict') {
      setLocalStrict({ preset: 'strict', oud: false, whey: true, nf: true, ethanol: true });
    } else {
      setLocalStrict({ preset: 'balanced', oud: true, whey: false, nf: false, ethanol: false });
    }
  }

  return (
    <SheetShell
      title="Settings & strictness"
      sub={
        appMode === 'api'
          ? 'Connected to HalalLens API server'
          : 'Standalone PWA mode · data saved privately on this device'
      }
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => {
              onSave({
                strict: localStrict,
                usdaApiKey: localUsdaKey.trim(),
                showExamples: localShowExamples,
              });
              onClose();
            }}
          >
            <Check size={15} />
            Save settings
          </button>
        </>
      }
    >
      <div className="field">
        <div className="field-l">Strictness preset</div>
        <div className="opts opts-2">
          <label className={`opt tone-halal${localStrict.preset === 'strict' ? ' checked' : ''}`}>
            <input
              type="radio"
              name="preset"
              checked={localStrict.preset === 'strict'}
              onChange={() => setPreset('strict')}
            />
            <span>
              <div className="opt-t">Strict</div>
              <div className="opt-d">Flags whey, natural flavors, vanilla &amp; OU-D enzymes</div>
            </span>
          </label>
          <label className={`opt tone-ok${localStrict.preset === 'balanced' ? ' checked' : ''}`}>
            <input
              type="radio"
              name="preset"
              checked={localStrict.preset === 'balanced'}
              onChange={() => setPreset('balanced')}
            />
            <span>
              <div className="opt-t">Balanced</div>
              <div className="opt-d">Accepts OU-D enzymes; marks whey &amp; flavors info-only</div>
            </span>
          </label>
        </div>
      </div>

      <div className="mt12">
        <label className="switch">
          <input
            type="checkbox"
            checked={localStrict.oud}
            onChange={(e) => setLocalStrict({ ...localStrict, oud: e.target.checked })}
          />
          <span className="track" />
          <span>
            <div className="opt-t">Accept trusted kosher symbols (OU-D, OK, Star-K)</div>
            <div className="opt-d">Treats enzymes &amp; emulsifiers on OU-D/Pareve labels as OK.</div>
          </span>
        </label>
        <label className="switch">
          <input
            type="checkbox"
            checked={localStrict.whey}
            onChange={(e) => setLocalStrict({ ...localStrict, whey: e.target.checked })}
          />
          <span className="track" />
          <span>
            <div className="opt-t">Flag whey</div>
            <div className="opt-d">Require confirmation that whey comes from microbial-rennet cheese.</div>
          </span>
        </label>
        <label className="switch">
          <input
            type="checkbox"
            checked={localStrict.nf}
            onChange={(e) => setLocalStrict({ ...localStrict, nf: e.target.checked })}
          />
          <span className="track" />
          <span>
            <div className="opt-t">Flag natural flavors</div>
            <div className="opt-d">Mark &ldquo;natural flavors&rdquo; as doubtful until confirmed.</div>
          </span>
        </label>
        <label className="switch">
          <input
            type="checkbox"
            checked={localStrict.ethanol}
            onChange={(e) => setLocalStrict({ ...localStrict, ethanol: e.target.checked })}
          />
          <span className="track" />
          <span>
            <div className="opt-t">Flag vanilla extract &amp; trace alcohol</div>
            <div className="opt-d">Flag pure vanilla extract and solvent ethanol on labels.</div>
          </span>
        </label>
      </div>

      <div className="divider" />

      <div className="field">
        <label className="field-l" htmlFor="s-usda">
          Personal USDA FoodData Central API key (optional)
        </label>
        <input
          id="s-usda"
          className="input mono"
          placeholder="Leave blank to use DEMO_KEY (30 req/hr)"
          value={localUsdaKey}
          onChange={(e) => setLocalUsdaKey(e.target.value)}
        />
        <div className="field-h">
          Get a free key (1,000 req/hr) at{' '}
          <a href="https://fdc.nal.usda.gov/api-key-signup.html" target="_blank" rel="noreferrer">
            fdc.nal.usda.gov
          </a>
          . Stored only in this browser.
        </div>
      </div>

      <label className="switch mt12">
        <input
          type="checkbox"
          checked={localShowExamples}
          onChange={(e) => setLocalShowExamples(e.target.checked)}
        />
        <span className="track" />
        <span>
          <div className="opt-t">Show &ldquo;Try it&rdquo; example chips on Home</div>
          <div className="opt-d">Turn off once you start testing your own groceries.</div>
        </span>
      </label>

      <div className="divider" />

      <div className="field-l">Your data &amp; backups</div>
      <div className="row mt8">
        <button className="btn btn-outline btn-sm" type="button" onClick={onExportBackup}>
          <Download size={14} />
          Export JSON backup
        </button>
        <input
          ref={importRef}
          type="file"
          accept="application/json"
          className="sr"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = '';
            if (file) onImportBackup(file);
          }}
        />
        <button className="btn btn-outline btn-sm" type="button" onClick={() => importRef.current?.click()}>
          <Upload size={14} />
          Import backup
        </button>
        <button className="btn btn-outline btn-sm" type="button" onClick={onClearExamples}>
          Remove sample items
        </button>
        <button className="btn btn-danger btn-sm" type="button" onClick={onResetAll}>
          <RotateCcw size={14} />
          Reset all
        </button>
      </div>
    </SheetShell>
  );
}

export function PasscodeSheet({
  onSubmit,
  error,
  loading,
}: {
  onSubmit: (code: string) => void;
  error: string | null;
  loading: boolean;
}) {
  const [code, setCode] = useState('');

  return (
    <SheetShell
      title="Personal instance locked"
      sub="Enter your HalalLens passcode to connect to this server"
      footer={
        <button
          className="btn btn-primary"
          type="button"
          disabled={!code.trim() || loading}
          onClick={() => onSubmit(code.trim())}
        >
          <Lock size={15} />
          {loading ? 'Checking…' : 'Unlock'}
        </button>
      }
    >
      {error && (
        <div className="notice tone-haram" style={{ marginBottom: 14 }}>
          <AlertTriangle size={16} style={{ flex: 'none', marginTop: 2 }} />
          <div>{error}</div>
        </div>
      )}
      <div className="field">
        <label className="field-l" htmlFor="passcode-input">
          Passcode
        </label>
        <input
          id="passcode-input"
          type="password"
          className="input"
          placeholder="Enter passcode"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && code.trim()) onSubmit(code.trim());
          }}
        />
      </div>
    </SheetShell>
  );
}
