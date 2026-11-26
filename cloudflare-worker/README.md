# HalalLens Multi-Source Research Worker (Cloudflare Free Tier)

This zero-dependency Cloudflare Worker runs on Cloudflare's **\$0/month free tier** (100,000 requests/day, no cold starts) and unlocks live multi-source scanning for the HalalLens GitHub Pages PWA (`https://omermd007.github.io/halalLens/`):

- **Reddit communities** (`r/halal`, `r/MuslimLounge`, `r/Costco`, `r/traderjoes`, `r/vegetarian`) without browser CORS blocks
- **Official brand FAQs & dietary pages** (with lightweight excerpt extraction)
- **U.S. Halal & vegetarian guides** (Muslim Consumer Group, IFANCA, HFSAA, ISA Halal, Vegetarian Resource Group, IsItHalal)
- **Unknown brand support contact discovery** (`GET /brand-contact`)
- **24-hour edge caching** so repeat scans are instant

---

## 3-Step Free Setup (No CLI Required)

1. **Create a free Cloudflare Worker**
   - Sign in at [dash.cloudflare.com](https://dash.cloudflare.com/) (free account, no credit card needed).
   - Go to **Workers & Pages → Create → Create Worker**.
   - Name it `halallens-scanner` and click **Deploy**.
   - Click **Edit code**, replace the default code with the contents of [`worker.js`](./worker.js), and click **Deploy**.
   - Copy your live Worker URL (e.g., `https://halallens-scanner.<your-subdomain>.workers.dev`).

2. **Connect it to HalalLens**
   - **Option A (on your phone):** Open HalalLens → tap **Settings** (top right) → paste your Worker URL into **Multi-site live scan proxy URL** → tap **Test connection** → **Save settings**.
   - **Option B (automatic for every device via GitHub Pages):** In your GitHub repo (`omermd007/halalLens`), go to **Settings → Secrets and variables → Actions → Variables** → add a repository variable named `VITE_PROXY_URL` with your Worker URL, then re-run the **Deploy HalalLens PWA to GitHub Pages** workflow.

3. **Optional Free Upgrades (Recommended for Best Web Coverage)**
   In Cloudflare Dashboard → your Worker → **Settings → Variables and Secrets → Add secret**:
   - `GEMINI_API_KEY` *(Recommended — Google Search Grounding)*: Free API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). Uses Google's live web index to search official brand FAQs, U.S. halal directories, Reddit, and brand support pages in one call. (Optional `GEMINI_MODEL` variable defaults to `gemini-2.5-flash`.)
   - `BRAVE_API_KEY`: Alternative free tier (2,000 web searches/month) at [brave.com/search/api](https://brave.com/search/api/).
   - `REDDIT_CLIENT_ID` & `REDDIT_CLIENT_SECRET`: Optional free Reddit "script" app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) (without these, the Worker automatically uses public Reddit archives).

---

## CLI Deploy (Alternative)

```bash
cd cloudflare-worker
npx wrangler deploy
# Optional secrets:
npx wrangler secret put BRAVE_API_KEY
```

## Local Unit Tests

```bash
node --test cloudflare-worker/worker.test.mjs
```
