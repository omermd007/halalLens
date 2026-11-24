# HalalLens — U.S. Grocery Barcode & Ingredient Verification

HalalLens helps U.S. grocery shoppers check whether questionable ingredients—such as **enzymes, whey, cheese cultures, gelatin, mono- and diglycerides, L-cysteine, glycerin, natural flavors, carmine, or vanilla extract**—are plant/microbial or animal-derived, with a **human-in-the-loop brand outreach workflow** (never unthrottled mass emailing).

## What’s inside

- **Installable PWA (`frontend/`)**:
  - Works over HTTPS on iPhone Safari and Android Chrome (**Add to Home Screen**).
  - **Cross-browser barcode scanning** via `@zxing/browser` + native `BarcodeDetector` + barcode-photo fallback.
  - **4-step UPC lookup waterfall**: your saved list → built-in offline catalog of **369 real U.S. products** → live Open Food Facts → live USDA FoodData Central (add your own free USDA API key in Settings for 1,000 req/hr).
  - **On-device label OCR** (`tesseract.js`) to read ingredient lists from package photos and detect silent recipe changes.
  - **19 U.S. ingredient rule families**, strictness presets (`Strict` / `Balanced`), brand policies, and community forum signal parsing (advisory only, with non-U.S. region warnings).
  - **Human-in-the-loop outreach**: tailored email drafts with cooldown warnings, `mailto:` launch, copy-to-clipboard, and verification logging.
  - **JSON export/import backup** and one-tap removal of illustrative sample items for clean personal testing.
- **Full-stack backend (`backend/`)** (ready for local hosting or Phase 2 production):
  - FastAPI + SQLite (44 pytest tests), live external lookup & Reddit/forum adapters, optional personal-mode passcode lock (`HALAL_SCAN_PASSCODE`), clean-seed toggle (`HALAL_SCAN_SEED_EXAMPLES=false`), and multi-stage `Dockerfile`.

---

## Option 1: Personal testing on your phone via GitHub Pages (free HTTPS)

A GitHub Actions workflow (`.github/workflows/deploy-pages.yml`) builds `frontend/` as a standalone PWA (`VITE_STANDALONE=true`) on every push to `main`.

1. Enable **GitHub Pages** in your repository: **Settings → Pages → Source: GitHub Actions**.
   *(Note: on GitHub Free personal accounts, GitHub Pages requires a public repository; private repo Pages requires GitHub Pro/Team.)*
2. Open the published `https://<username>.github.io/<repo>/` URL on your phone.
3. Install to your home screen:
   - **iPhone (Safari):** Share → **Add to Home Screen**
   - **Android (Chrome):** Menu (⋮) → **Install app**
4. Open **Settings (top right)** to:
   - Tap **Remove sample items** when you’re ready to track only your own groceries.
   - Optionally paste a free [USDA FoodData Central API key](https://fdc.nal.usda.gov/api-key-signup.html).
   - Periodically tap **Export JSON backup** to save your logged brand replies.

---

## Option 2: Run full-stack locally (FastAPI + React)

```bash
./scripts/run_local.sh
```

Then open `http://localhost:8000` (or `HALAL_SCAN_PASSCODE=mysecret ./scripts/run_local.sh` to enable the passcode lock).

### Environment variables (backend)

| Variable | Default | Purpose |
|---|---|---|
| `HALAL_SCAN_DB_PATH` | `backend/data/halal_scan.db` | SQLite database file path |
| `HALAL_SCAN_PASSCODE` | *(unset)* | Optional passcode protecting `/api/*` |
| `HALAL_SCAN_SEED_EXAMPLES` | `true` | Set `false` to seed rules only (no sample products) |
| `USDA_API_KEY` | `DEMO_KEY` | Free USDA FoodData Central key (1,000 req/hr) |
| `CORS_ALLOW_ORIGINS` | `localhost` | Comma-separated extra origins (e.g. GitHub Pages URL) |

---

## Option 3: Docker deployment (Render / Railway / Fly.io)

```bash
docker build -t halallens .
docker run -p 8000:8000 \
  -v halallens_data:/data \
  -e HALAL_SCAN_PASSCODE=choose-a-strong-passcode \
  -e HALAL_SCAN_SEED_EXAMPLES=false \
  -e USDA_API_KEY=your-free-usda-key \
  halallens
```

## Tests

```bash
cd backend && pytest -v -W error
cd frontend && npm run build
```

> **Disclaimer:** Seed examples are illustrative. HalalLens is an informational tool—always verify certification symbols and ingredient lists directly on the package in your hand.
