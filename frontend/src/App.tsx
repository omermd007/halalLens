import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  BookOpen,
  ClipboardCheck,
  FileText,
  Leaf,
  ScanLine,
  SlidersHorizontal,
} from 'lucide-react';
import { GuideView } from './components/GuideView';
import { LabelCheckView } from './components/LabelCheckView';
import { ProductDetailView } from './components/ProductDetailView';
import { ScanView } from './components/ScanView';
import {
  AddPolicySheet,
  AddProductSheet,
  CameraScanSheet,
  DraftEmailSheet,
  LogReplySheet,
  PasscodeSheet,
  PasteForumSheet,
  SettingsSheet,
} from './components/Sheets';
import { TodoView } from './components/TodoView';
import { decodeBarcodeFromPhoto } from './engine/barcodeScanner';
import {
  addMonths,
  digitsOf,
  evaluateProduct,
  queueOf,
  uid,
} from './engine/evaluator';
import { createSeedProducts, DEFAULT_STRICT, SEED_POLICIES } from './engine/seeds';
import {
  DEFAULT_PROXY_URL,
  detectBackendMode,
  exportBackupJson,
  liveRedditForumScan,
  loadPersistedState,
  makeProductFromLookup,
  normalizeBrandKey,
  parseBackupFile,
  runUpcWaterfall,
  savePersistedState,
  upsertSavedBrandContact,
  verifyServerPasscode,
  type PersistedState,
} from './engine/store';
import type {
  AppMode,
  BrandPolicyRecord,
  Determination,
  ForumSignalItem,
  LookupTrace,
  ProductRecord,
  ViewName,
} from './engine/types';

type ActiveSheet =
  | { kind: 'camera' }
  | { kind: 'draft'; productId: string; mode: 'full' | 'quick'; sigId?: string }
  | { kind: 'log'; productId: string; ingredient?: string }
  | { kind: 'add-product'; upc: string }
  | { kind: 'paste-forum'; productId: string }
  | { kind: 'add-policy' }
  | { kind: 'settings' }
  | null;

export default function App() {
  const [persisted, setPersisted] = useState<PersistedState>(() => loadPersistedState());
  const [view, setView] = useState<ViewName>('scan');
  const [productId, setProductId] = useState<string | null>(null);
  const [labelTargetId, setLabelTargetId] = useState<string | null>(null);
  const [upcDraft, setUpcDraft] = useState('');
  const [shake, setShake] = useState(false);
  const [trace, setTrace] = useState<LookupTrace | null>(null);
  const [sheet, setSheet] = useState<ActiveSheet>(null);
  const [toastMsg, setToastMsg] = useState('');
  const [toastOpen, setToastOpen] = useState(false);
  const [scanningForum, setScanningForum] = useState(false);
  const [appMode, setAppMode] = useState<AppMode>('standalone');
  const [needsPasscode, setNeedsPasscode] = useState(false);
  const [passcodeError, setPasscodeError] = useState<string | null>(null);
  const [checkingPasscode, setCheckingPasscode] = useState(false);

  const photoInputRef = useRef<HTMLInputElement>(null);
  const toastTimerRef = useRef<number | null>(null);

  const showToast = useCallback((msg: string) => {
    setToastMsg(msg);
    setToastOpen(true);
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToastOpen(false), 3200);
  }, []);

  // Persist to localStorage on changes
  useEffect(() => {
    savePersistedState(persisted);
  }, [persisted]);

  // Detect optional FastAPI server + passcode state
  useEffect(() => {
    let active = true;
    void detectBackendMode().then((res) => {
      if (!active) return;
      setAppMode(res.mode);
      setNeedsPasscode(res.mode === 'api' && res.passcodeRequired && !res.authenticated);
    });
    return () => {
      active = false;
    };
  }, []);

  const evals = useMemo(
    () => persisted.products.map((p) => evaluateProduct(p, persisted.policies, persisted.strict)),
    [persisted.products, persisted.policies, persisted.strict]
  );

  const queue = useMemo(() => queueOf(evals), [evals]);
  const activeEval = useMemo(
    () => (productId ? evals.find((e) => e.p.id === productId) || null : null),
    [evals, productId]
  );

  const openProduct = useCallback((id: string) => {
    setProductId(id);
    setView('product');
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
  }, []);

  const recordHistory = useCallback((p: ProductRecord) => {
    setPersisted((prev) => ({
      ...prev,
      history: [
        { id: p.id, upc: p.upc, name: p.name, brand: p.brand, at: new Date().toISOString() },
        ...prev.history.filter((h) => h.id !== p.id),
      ].slice(0, 12),
    }));
  }, []);

  const handleLookup = useCallback(
    async (explicitCode?: string) => {
      const raw = explicitCode ?? upcDraft;
      const digits = digitsOf(raw);
      if (explicitCode !== undefined) setUpcDraft(digits);
      if (digits.length < 6) {
        setShake(true);
        window.setTimeout(() => setShake(false), 400);
        showToast('Enter at least 6 digits of a barcode number.');
        return;
      }

      setView('scan');
      const res = await runUpcWaterfall({
        rawInput: digits,
        products: persisted.products,
        brandContacts: persisted.brandContacts,
        usdaApiKey: persisted.usdaApiKey,
        onSteps: (steps) => setTrace({ digits, steps }),
      });

      if (res.product) {
        const found = res.product;
        if (res.imported) {
          setPersisted((prev) => ({
            ...prev,
            products: [found, ...prev.products],
          }));
        }
        recordHistory(found);
        setTrace(null);
        openProduct(found.id);
        if (res.imported) {
          showToast(`Imported ${found.brand} ${found.name} (${found.source.label}).`);
        }
      } else {
        setTrace({ digits, steps: res.steps, notFound: true });
      }
    },
    [
      upcDraft,
      persisted.products,
      persisted.brandContacts,
      persisted.usdaApiKey,
      recordHistory,
      openProduct,
      showToast,
    ]
  );

  const handlePhotoFile = useCallback(
    async (file: File) => {
      showToast('Reading barcode from photo…');
      try {
        const code = await decodeBarcodeFromPhoto(file);
        if (!code) {
          showToast("Couldn't read a barcode from that photo. Try a closer, sharper shot.");
          return;
        }
        showToast(`Scanned ${code}`);
        void handleLookup(code);
      } catch {
        showToast("Couldn't open that image.");
      }
    },
    [handleLookup, showToast]
  );

  const handleSaveReply = useCallback(
    (
      pid: string,
      payload: {
        ingredient: string;
        determination: Determination;
        channel: string;
        date: string;
        excerpt: string;
        lot_code: string | null;
      }
    ) => {
      setPersisted((prev) => ({
        ...prev,
        products: prev.products.map((p) => {
          if (p.id !== pid) return p;
          const cur = p.snapshots.find((s) => s.is_current) || p.snapshots[p.snapshots.length - 1];
          if (!cur) return p;
          const nextSnap = payload.lot_code ? { ...cur, lot_code: payload.lot_code } : cur;
          const v = {
            id: uid('v'),
            snap: cur.id,
            ingredient: payload.ingredient,
            determination: payload.determination,
            varies: payload.determination === 'varies_by_supplier',
            channel: payload.channel,
            contact: p.brand,
            excerpt: payload.excerpt,
            lot_code: payload.lot_code,
            date: payload.date,
            expires: payload.determination === 'animal_or_haram' ? null : addMonths(payload.date, 12),
          };
          const filtered = p.verifications.filter(
            (x) => !(x.snap === cur.id && x.ingredient === payload.ingredient)
          );
          return {
            ...p,
            snapshots: p.snapshots.map((s) => (s.id === cur.id ? nextSnap : s)),
            verifications: [v, ...filtered],
          };
        }),
      }));
      showToast('Reply saved — verdict updated.');
    },
    [showToast]
  );

  const handleSaveBrandContact = useCallback(
    (
      brand: string,
      contact: { email: string; contact_url: string; phone?: string | null }
    ) => {
      const targetKey = normalizeBrandKey(brand);
      setPersisted((prev) => ({
        ...prev,
        brandContacts: upsertSavedBrandContact(prev.brandContacts, brand, contact),
        products: targetKey
          ? prev.products.map((p) =>
              normalizeBrandKey(p.brand) === targetKey
                ? {
                    ...p,
                    email: contact.email.trim(),
                    contact_url: contact.contact_url.trim(),
                  }
                : p
            )
          : prev.products,
      }));
    },
    []
  );

  const handleMarkOutreachSent = useCallback(
    (
      pid: string,
      to: string,
      contactUrl: string,
      subject: string,
      body: string,
      mode: 'full' | 'quick'
    ) => {
      setPersisted((prev) => {
        const target = prev.products.find((p) => p.id === pid);
        const nextBook =
          target && (to.trim() || contactUrl.trim())
            ? upsertSavedBrandContact(prev.brandContacts, target.brand, {
                email: to,
                contact_url: contactUrl,
              })
            : prev.brandContacts;
        return {
          ...prev,
          brandContacts: nextBook,
          products: prev.products.map((p) => {
            if (p.id !== pid) return p;
            const cur = p.snapshots.find((s) => s.is_current) || p.snapshots[p.snapshots.length - 1];
            return {
              ...p,
              email: to || p.email,
              contact_url: contactUrl || p.contact_url,
              outreach: [
                {
                  id: uid('o'),
                  snap: cur?.id || '',
                  to: to || contactUrl,
                  subject,
                  body,
                  mode,
                  state: 'sent',
                  created_at: new Date().toISOString(),
                },
                ...p.outreach,
              ],
            };
          }),
        };
      });
      showToast('Marked as sent.');
    },
    [showToast]
  );

  const handleSaveNewLabel = useCallback(
    (pid: string, rawText: string) => {
      setPersisted((prev) => ({
        ...prev,
        products: prev.products.map((p) => {
          if (p.id !== pid) return p;
          const nextSnap = {
            id: uid('s'),
            raw_ingredients: rawText,
            source_type: 'label',
            lot_code: null,
            plant_code: null,
            captured_at: new Date().toISOString(),
            is_current: true,
          };
          return {
            ...p,
            snapshots: [...p.snapshots.map((s) => ({ ...s, is_current: false })), nextSnap],
          };
        }),
      }));
      openProduct(pid);
      showToast('New label saved — verdict updated.');
    },
    [openProduct, showToast]
  );

  const handleSimulateChange = useCallback(
    (pid: string) => {
      setPersisted((prev) => ({
        ...prev,
        products: prev.products.map((p) => {
          if (p.id !== pid) return p;
          const cur = p.snapshots.find((s) => s.is_current) || p.snapshots[p.snapshots.length - 1];
          if (!cur) return p;
          const oldSnapId = cur.id;
          // Ensure a prior verification exists on oldSnapId so the drift detector fires clearly
          const ensuredVerifs = p.verifications.some((v) => v.snap === oldSnapId)
            ? p.verifications
            : [
                {
                  id: uid('v'),
                  snap: oldSnapId,
                  ingredient: 'enzymes',
                  determination: 'plant_or_microbial' as const,
                  varies: false,
                  channel: 'email',
                  contact: p.brand,
                  excerpt: 'Prior confirmation before simulated label change.',
                  date: '2026-06-01',
                  expires: '2027-06-01',
                },
                ...p.verifications,
              ];
          const nextSnap = {
            id: uid('s'),
            raw_ingredients: `${cur.raw_ingredients.replace(/\.$/, '')}, MONO- AND DIGLYCERIDES, NATURAL FLAVORS.`,
            source_type: 'demo_drift',
            lot_code: 'SIM-2026',
            plant_code: null,
            captured_at: new Date().toISOString(),
            is_current: true,
          };
          return {
            ...p,
            verifications: ensuredVerifs,
            snapshots: [...p.snapshots.map((s) => ({ ...s, is_current: false })), nextSnap],
          };
        }),
      }));
      showToast('Simulated a silent recipe change — check the verdict banner.');
    },
    [showToast]
  );

  const handleLiveForumScan = useCallback(
    async (product: ProductRecord, flaggedIngredients: string[]) => {
      setScanningForum(true);
      const res = await liveRedditForumScan(product, {
        flaggedIngredients,
        proxyUrl: persisted.proxyUrl,
        appMode,
      });
      setScanningForum(false);
      if (res.added.length) {
        setPersisted((prev) => ({
          ...prev,
          products: prev.products.map((p) =>
            p.id === product.id ? { ...p, signals: [...res.added, ...p.signals] } : p
          ),
        }));
      }
      showToast(res.message);
    },
    [persisted.proxyUrl, appMode, showToast]
  );

  const handleSaveForumPost = useCallback(
    (pid: string, signal: ForumSignalItem) => {
      setPersisted((prev) => ({
        ...prev,
        products: prev.products.map((p) =>
          p.id === pid ? { ...p, signals: [signal, ...p.signals] } : p
        ),
      }));
      showToast(
        signal.region === 'non_us'
          ? 'Saved post (flagged as non-U.S. recipe).'
          : 'Community post analyzed and saved.'
      );
    },
    [showToast]
  );

  const handleAddProduct = useCallback(
    (payload: {
      upc: string;
      brand: string;
      name: string;
      ingredients: string;
      cert: string | null;
      kosher: string | null;
      vegan: boolean;
    }) => {
      const created = makeProductFromLookup({
        upc: payload.upc || uid('upc'),
        brand: payload.brand,
        name: payload.name,
        ingredients: payload.ingredients,
        cert: payload.cert,
        kosher: payload.kosher,
        vegan: payload.vegan,
        sourceKind: 'manual',
        sourceLabel: 'Added by you',
        brandContacts: persisted.brandContacts,
      });
      setPersisted((prev) => ({ ...prev, products: [created, ...prev.products] }));
      recordHistory(created);
      setTrace(null);
      openProduct(created.id);
      showToast(`Saved ${created.brand} ${created.name}.`);
    },
    [persisted.brandContacts, recordHistory, openProduct, showToast]
  );

  const handleAddPolicy = useCallback(
    (policy: BrandPolicyRecord) => {
      setPersisted((prev) => ({ ...prev, policies: [policy, ...prev.policies] }));
      showToast(`Saved ${policy.brand} brand policy.`);
    },
    [showToast]
  );

  const handlePasscodeUnlock = useCallback(async (code: string) => {
    setCheckingPasscode(true);
    setPasscodeError(null);
    const ok = await verifyServerPasscode(code);
    setCheckingPasscode(false);
    if (ok) {
      setNeedsPasscode(false);
      showToast('Unlocked.');
    } else {
      setPasscodeError('Incorrect passcode. Try again.');
    }
  }, [showToast]);

  const activeNavTab: ViewName = view === 'product' ? 'scan' : view;

  return (
    <div className="app" id="app">
      <header className="topbar">
        <div className="topbar-in">
          <button
            id="btn-home"
            className="logo"
            type="button"
            onClick={() => {
              setView('scan');
              setProductId(null);
            }}
          >
            <span className="logo-mark">
              <Leaf size={20} />
            </span>
            <span>
              <div className="logo-name">HalalLens</div>
              <div className="logo-sub">U.S. grocery ingredient check</div>
            </span>
          </button>

          <nav className="tabs" aria-label="Main navigation">
            <button
              id="tab-scan"
              className={`tab${activeNavTab === 'scan' ? ' active' : ''}`}
              type="button"
              onClick={() => setView('scan')}
            >
              <ScanLine size={16} />
              Scan
            </button>
            <button
              id="tab-label"
              className={`tab${activeNavTab === 'label' ? ' active' : ''}`}
              type="button"
              onClick={() => setView('label')}
            >
              <FileText size={16} />
              Check a label
            </button>
            <button
              id="tab-todo"
              className={`tab${activeNavTab === 'todo' ? ' active' : ''}`}
              type="button"
              onClick={() => setView('todo')}
            >
              <ClipboardCheck size={16} />
              To-do
              <span id="badge-desk" className={`badge${queue.count === 0 ? ' zero' : ''}`}>
                {queue.count}
              </span>
            </button>
            <button
              id="tab-learn"
              className={`tab${activeNavTab === 'learn' ? ' active' : ''}`}
              type="button"
              onClick={() => setView('learn')}
            >
              <BookOpen size={16} />
              Ingredient guide
            </button>
          </nav>

          <button
            id="btn-profile"
            className="profile-btn"
            type="button"
            onClick={() => setSheet({ kind: 'settings' })}
          >
            <span className="profile-dot" />
            <span id="profile-label">
              {persisted.strict.preset === 'strict' ? 'Strict' : 'Balanced'}
            </span>
            <SlidersHorizontal size={15} />
          </button>
        </div>
      </header>

      <main className="container" id="view">
        {view === 'scan' && (
          <ScanView
            evals={evals}
            history={persisted.history}
            showExamples={persisted.showExamples}
            upcDraft={upcDraft}
            onUpcChange={setUpcDraft}
            onLookup={(code) => void handleLookup(code)}
            onOpenCamera={() => setSheet({ kind: 'camera' })}
            onPickPhoto={() => photoInputRef.current?.click()}
            onGoLabel={() => {
              setLabelTargetId(null);
              setView('label');
            }}
            onOpenProduct={openProduct}
            onAddProduct={(upc) => setSheet({ kind: 'add-product', upc })}
            trace={trace}
            onDismissTrace={() => setTrace(null)}
            shake={shake}
          />
        )}

        {view === 'product' && activeEval && (
          <ProductDetailView
            ev={activeEval}
            onBack={() => setView('scan')}
            onOpenDraft={(mode, sigId) =>
              setSheet({ kind: 'draft', productId: activeEval.p.id, mode, sigId })
            }
            onOpenLog={(ingredient) =>
              setSheet({ kind: 'log', productId: activeEval.p.id, ingredient })
            }
            onCompareLabel={() => {
              setLabelTargetId(activeEval.p.id);
              setView('label');
            }}
            onSimulateChange={() => handleSimulateChange(activeEval.p.id)}
            onLiveForumScan={() =>
              void handleLiveForumScan(
                activeEval.p,
                (activeEval.unresolvedFlags.length ? activeEval.unresolvedFlags : activeEval.flags).map(
                  (f) => f.rule.name
                )
              )
            }
            onOpenPasteForum={() => setSheet({ kind: 'paste-forum', productId: activeEval.p.id })}
            scanningForum={scanningForum}
          />
        )}

        {view === 'label' && (
          <LabelCheckView
            key={labelTargetId || 'standalone'}
            evals={evals}
            initialProductId={labelTargetId}
            onSaveLabel={handleSaveNewLabel}
            onToast={showToast}
          />
        )}

        {view === 'todo' && <TodoView evals={evals} onOpenProduct={openProduct} />}

        {view === 'learn' && (
          <GuideView
            policies={persisted.policies}
            onOpenAddPolicy={() => setSheet({ kind: 'add-policy' })}
          />
        )}
      </main>

      <nav className="bottomnav" aria-label="Mobile navigation">
        <button
          id="bn-scan"
          className={`bn${activeNavTab === 'scan' ? ' active' : ''}`}
          type="button"
          onClick={() => setView('scan')}
        >
          <span className="bn-ic">
            <ScanLine size={20} />
          </span>
          Scan
        </button>
        <button
          id="bn-label"
          className={`bn${activeNavTab === 'label' ? ' active' : ''}`}
          type="button"
          onClick={() => setView('label')}
        >
          <span className="bn-ic">
            <FileText size={20} />
          </span>
          Label
        </button>
        <button
          id="bn-todo"
          className={`bn${activeNavTab === 'todo' ? ' active' : ''}`}
          type="button"
          onClick={() => setView('todo')}
        >
          <span className="bn-ic">
            <ClipboardCheck size={20} />
          </span>
          To-do
          <span id="badge-mob" className={`badge${queue.count === 0 ? ' zero' : ''}`}>
            {queue.count}
          </span>
        </button>
        <button
          id="bn-learn"
          className={`bn${activeNavTab === 'learn' ? ' active' : ''}`}
          type="button"
          onClick={() => setView('learn')}
        >
          <span className="bn-ic">
            <BookOpen size={20} />
          </span>
          Guide
        </button>
      </nav>

      <input
        ref={photoInputRef}
        id="photo-input"
        type="file"
        accept="image/*"
        capture="environment"
        className="sr"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = '';
          if (file) void handlePhotoFile(file);
        }}
      />

      <div id="sheet-root">
        {needsPasscode && (
          <PasscodeSheet
            onSubmit={(code) => void handlePasscodeUnlock(code)}
            error={passcodeError}
            loading={checkingPasscode}
          />
        )}

        {!needsPasscode && sheet?.kind === 'camera' && (
          <CameraScanSheet
            onCode={(code) => {
              setSheet(null);
              showToast(`Scanned ${code}`);
              void handleLookup(code);
            }}
            onPickPhoto={() => photoInputRef.current?.click()}
            onClose={() => setSheet(null)}
          />
        )}

        {!needsPasscode &&
          sheet?.kind === 'draft' &&
          (() => {
            const ev = evals.find((e) => e.p.id === sheet.productId);
            if (!ev) return null;
            return (
              <DraftEmailSheet
                ev={ev}
                allProducts={persisted.products}
                brandContacts={persisted.brandContacts}
                appMode={appMode}
                proxyUrl={persisted.proxyUrl}
                mode={sheet.mode}
                sigId={sheet.sigId}
                onSaveBrandContact={handleSaveBrandContact}
                onMarkSent={(to, contactUrl, subj, body, mode) =>
                  handleMarkOutreachSent(ev.p.id, to, contactUrl, subj, body, mode)
                }
                onClose={() => setSheet(null)}
                onToast={showToast}
              />
            );
          })()}

        {!needsPasscode &&
          sheet?.kind === 'log' &&
          (() => {
            const ev = evals.find((e) => e.p.id === sheet.productId);
            if (!ev) return null;
            return (
              <LogReplySheet
                ev={ev}
                initialIngredient={sheet.ingredient}
                onSave={(payload) => handleSaveReply(ev.p.id, payload)}
                onClose={() => setSheet(null)}
              />
            );
          })()}

        {!needsPasscode && sheet?.kind === 'add-product' && (
          <AddProductSheet
            initialUpc={sheet.upc}
            onSave={handleAddProduct}
            onClose={() => setSheet(null)}
          />
        )}

        {!needsPasscode &&
          sheet?.kind === 'paste-forum' &&
          (() => {
            const prod = persisted.products.find((p) => p.id === sheet.productId);
            if (!prod) return null;
            return (
              <PasteForumSheet
                product={prod}
                onSave={(sig) => handleSaveForumPost(prod.id, sig)}
                onClose={() => setSheet(null)}
              />
            );
          })()}

        {!needsPasscode && sheet?.kind === 'add-policy' && (
          <AddPolicySheet onSave={handleAddPolicy} onClose={() => setSheet(null)} />
        )}

        {!needsPasscode && sheet?.kind === 'settings' && (
          <SettingsSheet
            strict={persisted.strict}
            usdaApiKey={persisted.usdaApiKey}
            proxyUrl={persisted.proxyUrl}
            showExamples={persisted.showExamples}
            appMode={appMode}
            onSave={(next) => {
              setPersisted((prev) => ({
                ...prev,
                strict: next.strict,
                usdaApiKey: next.usdaApiKey,
                proxyUrl: next.proxyUrl,
                showExamples: next.showExamples,
              }));
              showToast('Settings saved.');
            }}
            onExportBackup={() => {
              exportBackupJson(persisted);
              showToast('Backup JSON downloaded.');
            }}
            onImportBackup={(file) => {
              void parseBackupFile(file).then(
                (restored) => {
                  setPersisted(restored);
                  setSheet(null);
                  showToast(`Restored ${restored.products.length} products from backup.`);
                },
                (err) => showToast(err instanceof Error ? err.message : 'Could not import backup.')
              );
            }}
            onClearExamples={() => {
              setPersisted((prev) => ({
                ...prev,
                showExamples: false,
                products: prev.products.filter((p) => !p.is_example),
                history: prev.history.filter(
                  (h) => !prev.products.find((p) => p.id === h.id && p.is_example)
                ),
              }));
              setSheet(null);
              setView('scan');
              showToast('Removed illustrative sample items. Ready for your own groceries!');
            }}
            onResetAll={() => {
              setPersisted({
                products: createSeedProducts(),
                policies: JSON.parse(JSON.stringify(SEED_POLICIES)),
                brandContacts: {},
                strict: { ...DEFAULT_STRICT },
                history: [],
                usdaApiKey: '',
                proxyUrl: DEFAULT_PROXY_URL,
                showExamples: true,
              });
              setSheet(null);
              setView('scan');
              showToast('Reset to default sample data.');
            }}
            onClose={() => setSheet(null)}
          />
        )}
      </div>

      <div id="toast" className={`toast${toastOpen ? ' show' : ''}`} role="status" aria-live="polite">
        {toastMsg}
      </div>
    </div>
  );
}
