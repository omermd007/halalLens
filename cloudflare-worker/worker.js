/**
 * HalalLens Multi-Source Research & Brand Contact Worker (Cloudflare Workers — Free Tier)
 *
 * Endpoints:
 *   GET /health
 *   GET /scan?brand=...&product=...&ingredients=...
 *   GET /brand-contact?brand=...
 *
 * Optional Worker Secrets (all optional — works zero-key out of the box):
 *   BRAVE_API_KEY         - Free tier (2,000 queries/mo) at https://brave.com/search/api/
 *   REDDIT_CLIENT_ID      - Free Reddit "script" app at https://www.reddit.com/prefs/apps
 *   REDDIT_CLIENT_SECRET  - Paired with REDDIT_CLIENT_ID
 *   ALLOWED_ORIGINS       - Comma-separated extra allowed origins (default includes https://omermd007.github.io)
 */

const DEFAULT_ALLOWED_ORIGINS = [
  'https://omermd007.github.io',
];

const REDDIT_SUBREDDITS = ['halal', 'MuslimLounge', 'Costco', 'traderjoes', 'vegetarian'];

const HALAL_DIRECTORY_HOSTS = {
  'muslimconsumergroup.com': 'Muslim Consumer Group',
  'ifanca.org': 'IFANCA',
  'hfsaa.org': 'HFSAA',
  'isahalal.com': 'ISA Halal',
  'vrg.org': 'Vegetarian Resource Group',
  'isithalal.org': 'IsItHalal',
  'halalguide.org': 'Halal Guide',
  'scanhalal.org': 'ScanHalal',
};

const AGGREGATOR_HOSTS = new Set([
  'pissedconsumer.com',
  'gethuman.com',
  'bbb.org',
  'wikipedia.org',
  'reddit.com',
  'facebook.com',
  'instagram.com',
  'twitter.com',
  'x.com',
  'linkedin.com',
  'yelp.com',
  'zoominfo.com',
  'amazon.com',
  'walmart.com',
  'target.com',
  'instacart.com',
  'youtube.com',
  'tiktok.com',
  'pinterest.com',
  'dnb.com',
  'bloomberg.com',
  'crunchbase.com',
  'glassdoor.com',
  'indeed.com',
  'corporateoffice.com',
  'donotpay.com',
  'duckduckgo.com',
  'google.com',
  'example.com',
  'example.org',
  'example.net',
]);

const BLOCKED_EMAIL_DOMAINS = new Set([
  'example.com',
  'example.org',
  'example.net',
  'test.com',
  'invalid',
  'localhost',
  'wixpress.com',
  'sentry.io',
  'squarespace.com',
  'shopify.com',
  'cloudflare.com',
  'w3.org',
  'schema.org',
  'googleapis.com',
  'gravatar.com',
  'facebook.com',
  'twitter.com',
  'instagram.com',
  'youtube.com',
  'pissedconsumer.com',
  'gethuman.com',
  'bbb.org',
]);

const BLOCKED_LOCAL_PARTS = new Set([
  'noreply',
  'no-reply',
  'no_reply',
  'donotreply',
  'do-not-reply',
  'do_not_reply',
  'mailer-daemon',
  'postmaster',
  'webmaster',
  'hostmaster',
  'abuse',
  'security',
  'privacy',
  'usprivacy',
  'gdpr',
  'dpo',
  'legal',
  'dmca',
  'copyright',
  'copyrights',
  'trademark',
  'press',
  'media',
  'pr',
  'news',
  'newsroom',
  'ir',
  'investor',
  'investors',
  'investorrelations',
  'careers',
  'jobs',
  'hr',
  'askhr',
  'recruiting',
  'talent',
  'unsubscribe',
  'bounce',
  'notifications',
  'alerts',
  'billing',
  'sales',
  'wholesale',
  'affiliate',
  'affiliates',
  'donations',
  'sponsorship',
  'boardofdirectors',
]);

const PREFERRED_LOCAL_HINTS = [
  'customerservice',
  'customercare',
  'consumercare',
  'consumerrelations',
  'crelations',
  'support',
  'care',
  'help',
  'ask',
  'contact',
  'contactus',
  'info',
  'hello',
];

const BRAND_STOPWORDS = new Set([
  'inc',
  'llc',
  'co',
  'corp',
  'corporation',
  'company',
  'foods',
  'food',
  'brands',
  'brand',
  'usa',
  'us',
  'the',
  'and',
  'of',
  'international',
  'north',
  'america',
]);

const INGREDIENT_KEYWORDS = [
  'halal',
  'haram',
  'enzyme',
  'rennet',
  'microbial',
  'vegetarian',
  'vegan',
  'gelatin',
  'porcine',
  'pork',
  'beef',
  'animal',
  'whey',
  'culture',
  'diglyceride',
  'monoglyceride',
  'cysteine',
  'glycerin',
  'natural flavor',
  'carmine',
  'shellac',
  'vanilla',
  'alcohol',
  'ethanol',
  'kosher',
];

const USER_AGENT =
  'HalalLens-Worker/1.0 (+https://github.com/omermd007/halalLens; read-only ingredient research)';

// ---------------------------------------------------------------------------
// CORS & URL / Email Safety Helpers
// ---------------------------------------------------------------------------

export function resolveCorsOrigin(requestOrigin, env = {}) {
  if (!requestOrigin) return DEFAULT_ALLOWED_ORIGINS[0];
  try {
    const u = new URL(requestOrigin);
    if (u.hostname === 'localhost' || u.hostname === '127.0.0.1') {
      return requestOrigin;
    }
  } catch {
    return null;
  }
  const extra = String(env.ALLOWED_ORIGINS || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  const allowed = new Set([...DEFAULT_ALLOWED_ORIGINS, ...extra]);
  if (allowed.has('*')) return '*';
  return allowed.has(requestOrigin) ? requestOrigin : null;
}

function corsHeaders(origin) {
  const headers = {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Accept',
    Vary: 'Origin',
  };
  if (origin) {
    headers['Access-Control-Allow-Origin'] = origin;
  }
  return headers;
}

function jsonResponse(payload, status = 200, origin = null, extraHeaders = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { ...corsHeaders(origin), ...extraHeaders },
  });
}

export function normalizeBrand(str) {
  return String(str || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/['’`]/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

export function registrableDomain(host) {
  const h = String(host || '')
    .toLowerCase()
    .trim()
    .replace(/\.$/, '')
    .replace(/^www\./, '');
  const parts = h.split('.').filter(Boolean);
  if (parts.length <= 2) return parts.join('.');
  const last = parts[parts.length - 1];
  const prev = parts[parts.length - 2];
  if (['uk', 'au', 'nz', 'ca'].includes(last) && ['co', 'com', 'org', 'net'].includes(prev)) {
    return parts.slice(-3).join('.');
  }
  return parts.slice(-2).join('.');
}

export function isSafePublicUrl(rawUrl) {
  let u;
  try {
    u = new URL(rawUrl);
  } catch {
    return false;
  }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return false;
  if (u.username || u.password) return false;
  const host = u.hostname.toLowerCase();
  if (!host || host === 'localhost' || host === '::1' || host === '[::1]') return false;
  if (host.endsWith('.local') || host.endsWith('.internal') || host.endsWith('.localhost')) {
    return false;
  }
  // Reject IPv4 private/loopback/link-local ranges and bare IPv6 literals
  if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) {
    const octets = host.split('.').map(Number);
    const [a, b] = octets;
    if (
      a === 10 ||
      a === 127 ||
      a === 0 ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) ||
      (a === 100 && b >= 64 && b <= 127)
    ) {
      return false;
    }
  }
  if (host.includes(':')) return false;
  return true;
}

export function isValidSupportEmail(email, expectedDomain = null) {
  if (!email) return false;
  const cleaned = String(email).trim().toLowerCase();
  if (!/^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$/.test(cleaned)) return false;
  const [local, domain] = cleaned.split('@');
  if (BLOCKED_EMAIL_DOMAINS.has(domain)) return false;
  for (const blocked of BLOCKED_EMAIL_DOMAINS) {
    if (domain.endsWith(`.${blocked}`)) return false;
  }
  const localFlat = local.replace(/[^a-z0-9]/g, '');
  if (BLOCKED_LOCAL_PARTS.has(local) || BLOCKED_LOCAL_PARTS.has(localFlat)) return false;
  if (
    local.startsWith('noreply') ||
    local.startsWith('no-reply') ||
    local.startsWith('no_reply') ||
    local.startsWith('donotreply') ||
    local.startsWith('do-not-reply')
  ) {
    return false;
  }
  if (expectedDomain) {
    const expRoot = registrableDomain(expectedDomain);
    const emailRoot = registrableDomain(domain);
    if (expRoot && emailRoot !== expRoot) return false;
  }
  return true;
}

function decodeHtmlEntities(text) {
  return String(text || '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&#x27;|&apos;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n)));
}

function stripTags(html) {
  return decodeHtmlEntities(
    String(html || '')
      .replace(/<script[\s\S]*?<\/script>/gi, ' ')
      .replace(/<style[\s\S]*?<\/style>/gi, ' ')
      .replace(/<noscript[\s\S]*?<\/noscript>/gi, ' ')
      .replace(/<[^>]+>/g, ' ')
  )
    .replace(/\s+/g, ' ')
    .trim();
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 5000, fetchImpl = fetch) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetchImpl(url, {
      ...options,
      signal: ctrl.signal,
      headers: {
        'User-Agent': USER_AGENT,
        'Accept-Language': 'en-US,en;q=0.9',
        ...(options.headers || {}),
      },
    });
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// Source 1: Reddit (OAuth if configured, Arctic Shift public API, Reddit JSON)
// ---------------------------------------------------------------------------

async function getRedditOAuthToken(env, fetchImpl = fetch) {
  if (!env.REDDIT_CLIENT_ID || !env.REDDIT_CLIENT_SECRET) return null;
  try {
    const auth = btoa(`${env.REDDIT_CLIENT_ID}:${env.REDDIT_CLIENT_SECRET}`);
    const res = await fetchWithTimeout(
      'https://www.reddit.com/api/v1/access_token',
      {
        method: 'POST',
        headers: {
          Authorization: `Basic ${auth}`,
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: 'grant_type=client_credentials',
      },
      4500,
      fetchImpl
    );
    if (!res.ok) return null;
    const data = await res.json();
    return data?.access_token || null;
  } catch {
    return null;
  }
}

async function searchReddit(brand, shortProduct, env, fetchImpl = fetch) {
  const query = `${brand} ${shortProduct} halal`.trim();
  const items = [];

  // 1a. Official Reddit OAuth API (if user added free script-app credentials)
  const token = await getRedditOAuthToken(env, fetchImpl);
  if (token) {
    try {
      const url = `https://oauth.reddit.com/search?q=${encodeURIComponent(query)}&sort=relevance&limit=8&type=link`;
      const res = await fetchWithTimeout(
        url,
        { headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' } },
        5000,
        fetchImpl
      );
      if (res.ok) {
        const data = await res.json();
        const children = data?.data?.children || [];
        for (const ch of children) {
          const post = ch?.data;
          if (!post) continue;
          items.push({
            platform: 'reddit',
            source: `r/${post.subreddit || 'reddit'}`,
            url: `https://www.reddit.com${post.permalink || ''}`,
            title: String(post.title || '').trim(),
            author: post.author ? `u/${post.author}` : null,
            posted_at:
              typeof post.created_utc === 'number'
                ? new Date(post.created_utc * 1000).toISOString().slice(0, 10)
                : null,
            excerpt: String(post.selftext || post.title || '').trim().slice(0, 520),
          });
        }
        return { source: 'reddit_oauth', status: 'ok', items };
      }
    } catch {
      // fall through to Arctic Shift
    }
  }

  // 1b. Arctic Shift public Reddit search API (zero-key, cloud-friendly)
  try {
    const subResults = await Promise.allSettled(
      REDDIT_SUBREDDITS.slice(0, 4).map(async (sub) => {
        const subQuery = `${brand} ${shortProduct}`.trim();
        const url = `https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=${encodeURIComponent(
          sub
        )}&query=${encodeURIComponent(subQuery)}&limit=4&sort=desc`;
        const res = await fetchWithTimeout(url, { headers: { Accept: 'application/json' } }, 4500, fetchImpl);
        if (!res.ok) return [];
        const data = await res.json();
        const rows = Array.isArray(data?.data) ? data.data : [];
        return rows.map((post) => {
          const permalink = post.permalink
            ? String(post.permalink).startsWith('http')
              ? String(post.permalink)
              : `https://www.reddit.com${post.permalink}`
            : `https://www.reddit.com/r/${post.subreddit || sub}/comments/${post.id}/`;
          return {
            platform: 'reddit',
            source: `r/${post.subreddit || sub}`,
            url: permalink,
            title: String(post.title || '').trim(),
            author: post.author ? `u/${post.author}` : null,
            posted_at:
              typeof post.created_utc === 'number'
                ? new Date(post.created_utc * 1000).toISOString().slice(0, 10)
                : null,
            excerpt: String(post.selftext || post.title || '').trim().slice(0, 520),
          };
        });
      })
    );

    for (const r of subResults) {
      if (r.status === 'fulfilled' && Array.isArray(r.value)) {
        items.push(...r.value);
      }
    }
    if (items.length > 0) {
      return { source: 'reddit_archive', status: 'ok', items };
    }
  } catch {
    // fall through
  }

  // 1c. PullPush public Reddit archive (zero-key, cloud-friendly)
  try {
    const brandTokens = normalizeBrand(brand)
      .split(' ')
      .filter((t) => t.length >= 3 && !BRAND_STOPWORDS.has(t));
    const pullQueries = [
      `${brand} ${shortProduct} halal`.trim(),
      `${brand} halal`.trim(),
    ];
    const seenUrls = new Set();
    const pullResults = await Promise.allSettled(
      pullQueries.map(async (q) => {
        const url = `https://api.pullpush.io/reddit/search/submission/?q=${encodeURIComponent(
          q
        )}&size=8&sort=desc`;
        const res = await fetchWithTimeout(url, { headers: { Accept: 'application/json' } }, 5000, fetchImpl);
        if (!res.ok) return [];
        const data = await res.json();
        return Array.isArray(data?.data) ? data.data : [];
      })
    );

    for (const r of pullResults) {
      if (r.status !== 'fulfilled') continue;
      for (const post of r.value) {
        if (!post || !post.title) continue;
        const permalink = post.permalink
          ? String(post.permalink).startsWith('http')
            ? String(post.permalink)
            : `https://www.reddit.com${post.permalink}`
          : post.id
          ? `https://www.reddit.com/r/${post.subreddit || 'reddit'}/comments/${post.id}/`
          : null;
        if (!permalink || seenUrls.has(permalink)) continue;

        const hay = `${post.title || ''} ${post.selftext || ''}`.toLowerCase();
        const mentionsBrand =
          brandTokens.length === 0 || brandTokens.some((t) => hay.includes(t));
        const subLow = String(post.subreddit || '').toLowerCase();
        const relevantSub =
          REDDIT_SUBREDDITS.some((s) => s.toLowerCase() === subLow) ||
          ['kosher', 'vegan', 'food', 'cheese', 'islam', 'muslim', 'groceries', 'nutrition', 'glutenfree'].includes(
            subLow
          );
        const hasDietaryHint =
          /\b(halal|haram|mushbooh|zabiha|kosher|vegetarian|vegan|rennet|enzyme|gelatin|whey|pork|lard|alcohol|ethanol|ingredients?)\b/i.test(
            hay
          );

        if (!mentionsBrand || (!relevantSub && !hasDietaryHint)) continue;
        seenUrls.add(permalink);
        items.push({
          platform: 'reddit',
          source: `r/${post.subreddit || 'reddit'}`,
          url: permalink,
          title: String(post.title || '').trim(),
          author: post.author && post.author !== '[deleted]' ? `u/${post.author}` : null,
          posted_at:
            typeof post.created_utc === 'number'
              ? new Date(post.created_utc * 1000).toISOString().slice(0, 10)
              : null,
          excerpt: String(post.selftext || post.title || '').trim().slice(0, 520),
        });
      }
    }
    if (items.length > 0) {
      return { source: 'reddit_pullpush', status: 'ok', items: items.slice(0, 8) };
    }
  } catch {
    // fall through
  }

  // 1d. Public Reddit search JSON fallback
  try {
    const url = `https://www.reddit.com/search.json?q=${encodeURIComponent(query)}&sort=relevance&limit=6`;
    const res = await fetchWithTimeout(url, { headers: { Accept: 'application/json' } }, 4500, fetchImpl);
    if (res.ok) {
      const data = await res.json();
      const children = data?.data?.children || [];
      for (const ch of children) {
        const post = ch?.data;
        if (!post) continue;
        items.push({
          platform: 'reddit',
          source: `r/${post.subreddit || 'reddit'}`,
          url: `https://www.reddit.com${post.permalink || ''}`,
          title: String(post.title || '').trim(),
          author: post.author ? `u/${post.author}` : null,
          posted_at:
            typeof post.created_utc === 'number'
              ? new Date(post.created_utc * 1000).toISOString().slice(0, 10)
              : null,
          excerpt: String(post.selftext || post.title || '').trim().slice(0, 520),
        });
      }
      return { source: 'reddit_public', status: 'ok', items };
    }
  } catch {
    // ignore
  }

  return { source: 'reddit', status: 'empty', items };
}

// ---------------------------------------------------------------------------
// Source 2: Web, Official Brand FAQs, and U.S. Halal Directories
// ---------------------------------------------------------------------------

export function classifyWebResult(url, brand, titleHint = '') {
  let host = '';
  let path = '';
  try {
    const u = new URL(url);
    host = u.hostname.toLowerCase();
    path = u.pathname.toLowerCase();
  } catch {
    return { platform: 'web', source: 'Web' };
  }

  let root = registrableDomain(host);
  // Google Search Grounding often returns vertexaisearch.cloud.google.com redirect URLs
  // while putting the actual site domain (e.g. "cabotcreamery.com") in chunk.web.title.
  if (
    root === 'google.com' &&
    path.includes('grounding-api-redirect') &&
    titleHint &&
    /^[a-z0-9.-]+\.[a-z]{2,}$/i.test(titleHint.trim())
  ) {
    root = registrableDomain(titleHint.trim());
  }

  if (root === 'reddit.com') {
    const m = path.match(/^\/r\/([^/]+)/i);
    return { platform: 'reddit', source: m ? `r/${m[1]}` : 'Reddit' };
  }

  if (HALAL_DIRECTORY_HOSTS[root]) {
    return { platform: 'halal_directory', source: HALAL_DIRECTORY_HOSTS[root] };
  }

  const brandTokens = normalizeBrand(brand)
    .split(' ')
    .filter((t) => t.length >= 3 && !BRAND_STOPWORDS.has(t));
  const compactBrand = brandTokens.join('');
  const hostFlat = root.split('.')[0].replace(/[^a-z0-9]/g, '');
  const isOfficialHost =
    (compactBrand && (hostFlat.includes(compactBrand) || compactBrand.includes(hostFlat))) ||
    brandTokens.some((tok) => hostFlat.includes(tok));

  if (isOfficialHost) {
    return {
      platform: 'brand_faq',
      source: `Official ${brand} site (${root})`,
    };
  }

  return { platform: 'web', source: root };
}

export function extractDdgResults(htmlText) {
  const results = [];
  const seen = new Set();

  // DuckDuckGo HTML lite result blocks: <a class="result__a" href="...">Title</a> ... <a class="result__snippet"...>Snippet</a>
  const blockRe =
    /<a[^>]*class=["'][^"']*result__a[^"']*["'][^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>([\s\S]*?)(?=<div[^>]*class=["'][^"']*result\b|$)/gi;

  let m;
  while ((m = blockRe.exec(htmlText)) !== null) {
    let rawHref = decodeHtmlEntities(m[1]).trim();
    const title = stripTags(m[2]);
    const rest = m[3] || '';
    const snipMatch = rest.match(/class=["'][^"']*result__snippet[^"']*["'][^>]*>([\s\S]*?)<\/(?:a|div|span)>/i);
    const snippet = snipMatch ? stripTags(snipMatch[1]) : '';

    let targetUrl = rawHref;
    if (rawHref.includes('uddg=')) {
      try {
        const parsed = new URL(rawHref.startsWith('http') ? rawHref : `https://duckduckgo.com${rawHref}`);
        const uddg = parsed.searchParams.get('uddg');
        if (uddg) targetUrl = uddg;
      } catch {
        continue;
      }
    }

    if (!isSafePublicUrl(targetUrl)) continue;
    const host = new URL(targetUrl).hostname.toLowerCase();
    const root = registrableDomain(host);
    if (AGGREGATOR_HOSTS.has(root) && root !== 'reddit.com') continue;
    if (seen.has(targetUrl)) continue;
    seen.add(targetUrl);

    results.push({ url: targetUrl, title, snippet });
    if (results.length >= 12) break;
  }

  return results;
}

async function braveWebSearch(query, apiKey, count = 6, fetchImpl = fetch) {
  const url = `https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(
    query
  )}&count=${count}&country=us&search_lang=en`;
  const res = await fetchWithTimeout(
    url,
    {
      headers: {
        Accept: 'application/json',
        'X-Subscription-Token': apiKey,
      },
    },
    5000,
    fetchImpl
  );
  if (!res.ok) return [];
  const data = await res.json();
  const rows = Array.isArray(data?.web?.results) ? data.web.results : [];
  return rows
    .filter((r) => r?.url && isSafePublicUrl(r.url))
    .map((r) => ({
      url: String(r.url),
      title: String(r.title || '').trim(),
      snippet: stripTags(r.description || ''),
      posted_at: r.page_age ? String(r.page_age).slice(0, 10) : null,
    }));
}

async function ddgWebSearch(query, fetchImpl = fetch) {
  const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`;
  const res = await fetchWithTimeout(url, { headers: { Accept: 'text/html' } }, 5000, fetchImpl);
  if (!res.ok) return [];
  const html = (await res.text()).slice(0, 300_000);
  return extractDdgResults(html).map((r) => ({ ...r, posted_at: null }));
}

export function extractBingRssResults(xmlText) {
  const results = [];
  const seen = new Set();
  const itemRe = /<item>([\s\S]*?)<\/item>/gi;
  let m;
  while ((m = itemRe.exec(xmlText)) !== null) {
    const block = m[1];
    const titleM = block.match(/<title>([\s\S]*?)<\/title>/i);
    const linkM = block.match(/<link>([\s\S]*?)<\/link>/i);
    const descM = block.match(/<description>([\s\S]*?)<\/description>/i);
    const targetUrl = linkM ? decodeHtmlEntities(linkM[1]).trim() : '';
    if (!targetUrl || !isSafePublicUrl(targetUrl)) continue;
    const root = registrableDomain(new URL(targetUrl).hostname);
    if (AGGREGATOR_HOSTS.has(root) && root !== 'reddit.com') continue;
    if (seen.has(targetUrl)) continue;
    seen.add(targetUrl);
    results.push({
      url: targetUrl,
      title: titleM ? stripTags(titleM[1]) : root,
      snippet: descM ? stripTags(descM[1]) : '',
      posted_at: null,
    });
    if (results.length >= 10) break;
  }
  return results;
}

async function bingRssSearch(query, fetchImpl = fetch) {
  const url = `https://www.bing.com/search?format=rss&q=${encodeURIComponent(query)}`;
  const res = await fetchWithTimeout(
    url,
    {
      headers: {
        Accept: 'application/rss+xml, application/xml, text/xml',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
      },
    },
    4500,
    fetchImpl
  );
  if (!res.ok) return [];
  const xml = (await res.text()).slice(0, 200_000);
  return extractBingRssResults(xml);
}

export function extractRelevantPageExcerpt(htmlText, brand, ingredients = []) {
  const cleanText = stripTags(htmlText);
  if (!cleanText) return '';

  const terms = [
    ...ingredients.map((i) => i.toLowerCase().trim()).filter(Boolean),
    ...INGREDIENT_KEYWORDS,
  ];
  const sentences = cleanText
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length >= 30 && s.length <= 360);

  const brandLow = normalizeBrand(brand);
  let best = '';
  let bestScore = 0;

  for (const s of sentences.slice(0, 220)) {
    const low = s.toLowerCase();
    let score = 0;
    for (const term of terms) {
      if (low.includes(term)) score += term.length >= 6 ? 3 : 2;
    }
    if (brandLow && normalizeBrand(s).includes(brandLow)) score += 2;
    if (score > bestScore) {
      bestScore = score;
      best = s;
    }
  }

  return bestScore >= 2 ? best.slice(0, 500) : '';
}

async function enrichTopWebItems(items, brand, ingredients, fetchImpl = fetch) {
  // Enrich up to 2 high-value non-Reddit pages (official brand FAQs or halal directories)
  const targets = items
    .filter((it) => it.platform === 'brand_faq' || it.platform === 'halal_directory')
    .slice(0, 2);

  await Promise.allSettled(
    targets.map(async (item) => {
      if (!isSafePublicUrl(item.url)) return;
      const res = await fetchWithTimeout(item.url, { headers: { Accept: 'text/html' } }, 3800, fetchImpl);
      if (!res.ok) return;
      const ctype = (res.headers.get('content-type') || '').toLowerCase();
      if (ctype && !ctype.includes('text/html') && !ctype.includes('text/plain')) return;
      const html = (await res.text()).slice(0, 180_000);
      const richExcerpt = extractRelevantPageExcerpt(html, brand, ingredients);
      if (richExcerpt && richExcerpt.length > (item.excerpt || '').length) {
        item.excerpt = richExcerpt;
      }
    })
  );
}

async function geminiGroundedWebSearch(brand, shortProduct, ingredients, env, fetchImpl = fetch) {
  const apiKey = env.GEMINI_API_KEY;
  if (!apiKey) return [];
  const model = (env.GEMINI_MODEL || 'gemini-2.5-flash').trim();
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(
    model
  )}:generateContent?key=${encodeURIComponent(apiKey)}`;

  const ingList = ingredients.length
    ? ingredients.slice(0, 5).join(', ')
    : 'enzymes, rennet, gelatin, whey, mono- and diglycerides, natural flavors';
  const prompt = [
    `Search the web for U.S. grocery ingredient sourcing information about "${brand} ${shortProduct}".`,
    `Focus specifically on: ${ingList}, and whether the U.S. version is halal, vegetarian, uses microbial/plant vs. animal-derived ingredients, or has official brand FAQ statements, Muslim Consumer Group / IFANCA / HFSAA / ISA Halal / VRG listings, or Reddit discussions.`,
    `Give a concise 3-5 sentence factual summary citing only what is supported by the search results. If sources conflict or vary by supplier/facility, say so explicitly. Never guess.`,
  ].join(' ');

  const res = await fetchWithTimeout(
    url,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        tools: [{ google_search: {} }],
        generationConfig: {
          temperature: 0.1,
          maxOutputTokens: 450,
        },
      }),
    },
    8000,
    fetchImpl
  );

  if (!res.ok) return [];
  const data = await res.json();
  const candidate = data?.candidates?.[0];
  if (!candidate) return [];

  const summaryText = (candidate?.content?.parts || [])
    .map((p) => p?.text || '')
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();

  const meta = candidate?.groundingMetadata || {};
  const chunks = Array.isArray(meta.groundingChunks) ? meta.groundingChunks : [];
  const supports = Array.isArray(meta.groundingSupports) ? meta.groundingSupports : [];

  // Map each chunk index to the grounded sentence(s) that cite it
  const chunkExcerpts = new Map();
  for (const sup of supports) {
    const segText = String(sup?.segment?.text || '').trim();
    const indices = Array.isArray(sup?.groundingChunkIndices) ? sup.groundingChunkIndices : [];
    if (!segText) continue;
    for (const idx of indices) {
      const prev = chunkExcerpts.get(idx) || [];
      if (prev.length < 2 && !prev.includes(segText)) {
        prev.push(segText);
        chunkExcerpts.set(idx, prev);
      }
    }
  }

  const results = [];
  const seen = new Set();
  for (let i = 0; i < chunks.length; i++) {
    const web = chunks[i]?.web;
    const uri = String(web?.uri || '').trim();
    const title = String(web?.title || '').trim();
    if (!uri || !isSafePublicUrl(uri) || seen.has(uri)) continue;
    seen.add(uri);
    const matchedSegments = chunkExcerpts.get(i) || [];
    const snippet = matchedSegments.length > 0 ? matchedSegments.join(' ') : summaryText;
    results.push({
      url: uri,
      title: title || 'Google Search source',
      snippet: snippet.slice(0, 520),
      posted_at: null,
      fromGemini: true,
    });
    if (results.length >= 8) break;
  }

  return results;
}

async function searchWebAndHalalSites(brand, shortProduct, ingredients, env, fetchImpl = fetch) {
  const ingHint = ingredients.length
    ? ingredients.slice(0, 3).join(' OR ')
    : 'enzymes OR rennet OR gelatin OR whey';
  const generalQuery = `"${brand}" ${shortProduct} (halal OR ${ingHint}) -site:reddit.com`;
  const directoryQuery = `"${brand}" ${shortProduct} (site:muslimconsumergroup.com OR site:ifanca.org OR site:hfsaa.org OR site:isahalal.com OR site:vrg.org OR site:isithalal.org)`;

  let rawResults = [];
  let engine = 'ddg';

  if (env.GEMINI_API_KEY) {
    engine = 'gemini_google_search';
    try {
      const geminiRows = await geminiGroundedWebSearch(
        brand,
        shortProduct,
        ingredients,
        env,
        fetchImpl
      );
      rawResults.push(...geminiRows);
    } catch {
      // fall through to Brave / DDG / Bing
    }
  }

  if (env.BRAVE_API_KEY) {
    engine = engine === 'gemini_google_search' ? 'gemini_and_brave' : 'brave';
    const [gen, dir] = await Promise.allSettled([
      braveWebSearch(generalQuery, env.BRAVE_API_KEY, 6, fetchImpl),
      braveWebSearch(directoryQuery, env.BRAVE_API_KEY, 5, fetchImpl),
    ]);
    if (gen.status === 'fulfilled') rawResults.push(...gen.value);
    if (dir.status === 'fulfilled') rawResults.push(...dir.value);
  } else if (rawResults.length === 0) {
    const [gen, dir] = await Promise.allSettled([
      ddgWebSearch(generalQuery, fetchImpl),
      ddgWebSearch(directoryQuery, fetchImpl),
    ]);
    if (gen.status === 'fulfilled') rawResults.push(...gen.value);
    if (dir.status === 'fulfilled') rawResults.push(...dir.value);

    // Zero-key Bing RSS fallback when DuckDuckGo blocks cloud edge IPs
    if (rawResults.length === 0) {
      try {
        const bingRows = await bingRssSearch(`${brand} ${shortProduct}`.trim(), fetchImpl);
        const officialRows = bingRows.filter((r) => {
          const { platform } = classifyWebResult(r.url, brand);
          return platform === 'brand_faq' || platform === 'halal_directory';
        });
        rawResults.push(...officialRows.slice(0, 3));
      } catch {
        // ignore
      }
    }
  }

  const seen = new Set();
  const items = [];
  for (const r of rawResults) {
    if (!r.url || seen.has(r.url)) continue;
    seen.add(r.url);
    const { platform, source } = classifyWebResult(r.url, brand, r.title || '');
    items.push({
      platform,
      source,
      url: r.url,
      title: r.title || source,
      author: null,
      posted_at: r.posted_at || null,
      excerpt: (r.snippet || '').slice(0, 520),
    });
  }

  // Prioritize official brand FAQs and U.S. halal directories first
  const priority = { brand_faq: 0, halal_directory: 1, web: 2, reddit: 3 };
  items.sort((a, b) => (priority[a.platform] ?? 9) - (priority[b.platform] ?? 9));

  // Only fetch HTML excerpts for direct non-redirect URLs
  const enrichable = items.filter((it) => !it.url.includes('grounding-api-redirect'));
  await enrichTopWebItems(enrichable, brand, ingredients, fetchImpl);

  const sourceTag =
    engine === 'gemini_google_search'
      ? 'gemini_google_search'
      : engine === 'gemini_and_brave'
      ? 'gemini_and_brave_search'
      : engine === 'brave'
      ? 'brave_web_and_halal_sites'
      : 'web_and_halal_sites';

  return {
    source: sourceTag,
    status: items.length ? 'ok' : 'empty',
    items: items.slice(0, 10),
  };
}

// ---------------------------------------------------------------------------
// Endpoint 2: /brand-contact (Official Support Discovery for Unknown Brands)
// ---------------------------------------------------------------------------

export function pickOfficialContactUrl(brand, candidates) {
  const tokens = normalizeBrand(brand)
    .split(' ')
    .filter((t) => t.length >= 3 && !BRAND_STOPWORDS.has(t));
  const compactBrand = tokens.join('');

  let bestUrl = null;
  let bestScore = -1;

  for (const url of candidates) {
    if (!isSafePublicUrl(url)) continue;
    let u;
    try {
      u = new URL(url);
    } catch {
      continue;
    }
    const root = registrableDomain(u.hostname);
    if (AGGREGATOR_HOSTS.has(root)) continue;
    const hostFlat = root.split('.')[0].replace(/[^a-z0-9]/g, '');
    const path = u.pathname.toLowerCase();

    let score = 0;
    let matched = false;
    if (compactBrand && (hostFlat.includes(compactBrand) || compactBrand.includes(hostFlat))) {
      matched = true;
      score += 50;
    } else {
      const hits = tokens.filter((t) => hostFlat.includes(t)).length;
      if (hits > 0) {
        matched = true;
        score += hits * 25;
      }
    }
    if (!matched) continue;

    if (/(contact|support|consumer|customer-care|help)/.test(path)) score += 30;
    else if (path.includes('faq')) score += 15;
    if (u.protocol === 'https:') score += 5;

    if (score > bestScore) {
      bestScore = score;
      bestUrl = url;
    }
  }

  return bestUrl;
}

export function extractEmailAndPhoneFromHtml(htmlText, pageUrl) {
  let expectedDomain = null;
  try {
    expectedDomain = registrableDomain(new URL(pageUrl).hostname);
  } catch {
    expectedDomain = null;
  }

  const candidates = [];
  for (const m of htmlText.matchAll(/mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/gi)) {
    candidates.push(m[1].trim());
  }
  for (const m of htmlText.matchAll(/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g)) {
    candidates.push(m[0].trim());
  }

  const seen = new Set();
  const valid = [];
  for (const addr of candidates) {
    const low = addr.toLowerCase();
    if (seen.has(low)) continue;
    seen.add(low);
    if (isValidSupportEmail(low, expectedDomain)) valid.push(low);
  }

  let email = null;
  if (valid.length > 0) {
    const rank = (addr) => {
      const localFlat = addr.split('@')[0].replace(/[^a-z0-9]/g, '');
      const idx = PREFERRED_LOCAL_HINTS.findIndex(
        (h) => localFlat === h || localFlat.includes(h)
      );
      return idx >= 0 ? idx : 200;
    };
    valid.sort((a, b) => rank(a) - rank(b));
    email = valid[0];
  }

  const phoneMatch = htmlText.match(
    /\b1?[-.\s]?\(?(8(?:00|33|44|55|66|77|88))\)?[-.\s]?(\d{3})[-.\s]?(\d{4})\b/
  );
  const phone = phoneMatch
    ? `1-${phoneMatch[1]}-${phoneMatch[2]}-${phoneMatch[3]}`
    : null;

  return { email, phone };
}

function findSameDomainContactLink(htmlText, baseUrl) {
  let base;
  try {
    base = new URL(baseUrl);
  } catch {
    return null;
  }
  const baseRoot = registrableDomain(base.hostname);
  let best = null;
  let bestScore = -1;

  for (const m of htmlText.matchAll(/<a[^>]*href=["']([^"'#]+)["'][^>]*>/gi)) {
    const rawHref = decodeHtmlEntities(m[1]).trim();
    if (!rawHref || rawHref.startsWith('mailto:') || rawHref.startsWith('tel:') || rawHref.startsWith('javascript:')) {
      continue;
    }
    let resolved;
    try {
      resolved = new URL(rawHref, base);
    } catch {
      continue;
    }
    if (!isSafePublicUrl(resolved.href)) continue;
    if (registrableDomain(resolved.hostname) !== baseRoot) continue;
    const path = resolved.pathname.toLowerCase();
    let score = -1;
    if (/\/(contact-us|contact|contactus|pages\/contact)\b/.test(path)) score = 10;
    else if (/\/(support|help|customer-care|consumer-care|customer-service|faq)\b/.test(path)) score = 6;
    if (score > bestScore && resolved.href !== base.href) {
      bestScore = score;
      best = resolved.href;
    }
  }
  return best;
}

async function geminiGroundedBrandContact(brand, env, fetchImpl = fetch) {
  const apiKey = env.GEMINI_API_KEY;
  if (!apiKey) return null;
  const model = (env.GEMINI_MODEL || 'gemini-2.5-flash').trim();
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(
    model
  )}:generateContent?key=${encodeURIComponent(apiKey)}`;

  const prompt = [
    `Find the official U.S. consumer care / customer support contact for the grocery brand "${brand}".`,
    `Return ONLY a compact JSON object with keys: "contact_url" (official contact/support URL or null), "email" (published support email on the brand's own domain, or null — NEVER guess or fabricate an email), "phone" (U.S. toll-free phone or null).`,
  ].join(' ');

  const res = await fetchWithTimeout(
    url,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        tools: [{ google_search: {} }],
        generationConfig: {
          temperature: 0.0,
          maxOutputTokens: 250,
        },
      }),
    },
    7500,
    fetchImpl
  );
  if (!res.ok) return null;
  const data = await res.json();
  const text = (data?.candidates?.[0]?.content?.parts || [])
    .map((p) => p?.text || '')
    .join('\n')
    .trim();
  if (!text) return null;

  const jsonMatch = text.match(/\{[\s\S]*\}/);
  if (!jsonMatch) return null;
  let parsed;
  try {
    parsed = JSON.parse(jsonMatch[0]);
  } catch {
    return null;
  }

  let contactUrl =
    typeof parsed.contact_url === 'string' && isSafePublicUrl(parsed.contact_url.trim())
      ? parsed.contact_url.trim()
      : null;
  if (contactUrl) {
    const root = registrableDomain(new URL(contactUrl).hostname);
    if (AGGREGATOR_HOSTS.has(root)) contactUrl = null;
  }

  const expectedDomain = contactUrl ? registrableDomain(new URL(contactUrl).hostname) : null;
  const rawEmail = typeof parsed.email === 'string' ? parsed.email.trim().toLowerCase() : null;
  const email = rawEmail && isValidSupportEmail(rawEmail, expectedDomain) ? rawEmail : null;
  const phone = typeof parsed.phone === 'string' && parsed.phone.trim() ? parsed.phone.trim() : null;

  if (!contactUrl && !email) return null;
  return { contact_url: contactUrl, email, phone };
}

async function handleBrandContact(brand, env, fetchImpl = fetch) {
  const cleaned = brand.trim();
  const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(
    `"${cleaned}" consumer care OR customer support contact email`
  )}`;
  const query = `"${cleaned}" official "contact us" consumer care OR customer support`;

  if (env.GEMINI_API_KEY) {
    try {
      const grounded = await geminiGroundedBrandContact(cleaned, env, fetchImpl);
      if (grounded && (grounded.contact_url || grounded.email)) {
        return {
          brand: cleaned,
          matched_query: cleaned,
          source: 'gemini_google_search',
          verified: false,
          contact_type: grounded.email ? 'email' : 'web_form',
          email: grounded.email,
          contact_url: grounded.contact_url,
          phone: grounded.phone,
          search_url: searchUrl,
          note: "Discovered via Google Search grounding on the brand's official site. Please verify before sending.",
        };
      }
    } catch {
      // fall through to Brave / DDG / Bing
    }
  }

  let results = [];
  try {
    results = env.BRAVE_API_KEY
      ? await braveWebSearch(query, env.BRAVE_API_KEY, 6, fetchImpl)
      : await ddgWebSearch(query, fetchImpl);
  } catch {
    results = [];
  }

  if (results.length === 0 && !env.BRAVE_API_KEY) {
    try {
      results = await bingRssSearch(cleaned, fetchImpl);
    } catch {
      results = [];
    }
  }

  const contactUrl = pickOfficialContactUrl(
    cleaned,
    results.map((r) => r.url)
  );
  if (!contactUrl) {
    return {
      brand: cleaned,
      matched_query: cleaned,
      source: 'not_found',
      verified: false,
      contact_type: 'unknown',
      email: null,
      contact_url: null,
      phone: null,
      search_url: searchUrl,
      note: 'No official support contact found automatically. Use the web search link to look up this brand.',
    };
  }

  let email = null;
  let phone = null;
  let finalUrl = contactUrl;
  try {
    const pageRes = await fetchWithTimeout(
      contactUrl,
      { headers: { Accept: 'text/html' } },
      4500,
      fetchImpl
    );
    if (pageRes.ok && isSafePublicUrl(pageRes.url || contactUrl)) {
      finalUrl = pageRes.url || contactUrl;
      const html = (await pageRes.text()).slice(0, 220_000);
      ({ email, phone } = extractEmailAndPhoneFromHtml(html, finalUrl));

      // If we landed on the brand homepage and didn't find a direct contact page/email yet, follow a same-domain /contact link
      const subContactLink = findSameDomainContactLink(html, finalUrl);
      if (subContactLink && (!email || new URL(finalUrl).pathname === '/')) {
        try {
          const subRes = await fetchWithTimeout(
            subContactLink,
            { headers: { Accept: 'text/html' } },
            4000,
            fetchImpl
          );
          if (subRes.ok && isSafePublicUrl(subRes.url || subContactLink)) {
            finalUrl = subRes.url || subContactLink;
            const subHtml = (await subRes.text()).slice(0, 220_000);
            const subExtracted = extractEmailAndPhoneFromHtml(subHtml, finalUrl);
            if (subExtracted.email) email = subExtracted.email;
            if (!phone && subExtracted.phone) phone = subExtracted.phone;
          }
        } catch {
          // keep homepage result
        }
      }
    }
  } catch {
    // Still return the official contact page URL even if fetching fails
  }

  return {
    brand: cleaned,
    matched_query: cleaned,
    source: 'web_lookup',
    verified: false,
    contact_type: email ? 'email' : 'web_form',
    email,
    contact_url: finalUrl,
    phone,
    search_url: searchUrl,
    note: "Discovered via web lookup on the brand's website. Please verify before sending.",
  };
}

// ---------------------------------------------------------------------------
// Main Worker Fetch Handler
// ---------------------------------------------------------------------------

export async function handleRequest(request, env = {}, ctx = null, fetchImpl = fetch) {
  const origin = resolveCorsOrigin(request.headers.get('Origin'), env);

  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders(origin) });
  }

  if (request.method !== 'GET') {
    return jsonResponse({ error: 'Method not allowed' }, 405, origin);
  }

  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, '') || '/';

  if (path === '/' || path === '/health') {
    return jsonResponse(
      {
        status: 'ok',
        service: 'halallens-research-worker',
        capabilities: {
          gemini_google_search: Boolean(env.GEMINI_API_KEY),
          brave_search: Boolean(env.BRAVE_API_KEY),
          reddit_oauth: Boolean(env.REDDIT_CLIENT_ID && env.REDDIT_CLIENT_SECRET),
          reddit_archive: true,
          web_fallback: true,
          halal_directories: Object.values(HALAL_DIRECTORY_HOSTS),
          brand_contact_lookup: true,
        },
      },
      200,
      origin
    );
  }

  if (path === '/scan') {
    const brand = (url.searchParams.get('brand') || '').trim();
    const product = (url.searchParams.get('product') || '').trim();
    const ingredientsRaw = (url.searchParams.get('ingredients') || '').trim();
    const fresh = url.searchParams.get('fresh') === '1';

    if (!brand && !product) {
      return jsonResponse({ error: 'brand or product query parameter is required' }, 400, origin);
    }

    const cache = typeof caches !== 'undefined' ? caches.default : null;
    const cacheKeyUrl = new URL(url.toString());
    cacheKeyUrl.searchParams.delete('fresh');
    const cacheKey = new Request(cacheKeyUrl.toString(), { method: 'GET' });

    if (cache && !fresh) {
      const cachedRes = await cache.match(cacheKey);
      if (cachedRes) {
        const cachedData = await cachedRes.json();
        return jsonResponse({ ...cachedData, cached: true }, 200, origin);
      }
    }

    const shortProduct = product.split(/\s+/).slice(0, 4).join(' ');
    const ingredients = ingredientsRaw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    const [redditRes, webRes] = await Promise.all([
      searchReddit(brand, shortProduct, env, fetchImpl),
      searchWebAndHalalSites(brand, shortProduct, ingredients, env, fetchImpl),
    ]);

    const seen = new Set();
    const combined = [];
    for (const item of [...webRes.items, ...redditRes.items]) {
      const key = (item.url || `${item.source}:${item.title}`).toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      combined.push(item);
    }

    const payload = {
      ok: true,
      cached: false,
      query: { brand, product: shortProduct, ingredients },
      sources_checked: [
        { source: webRes.source, status: webRes.status, count: webRes.items.length },
        { source: redditRes.source, status: redditRes.status, count: redditRes.items.length },
      ],
      items: combined.slice(0, 14),
    };

    const response = jsonResponse(payload, 200, origin, {
      'Cache-Control': 'public, max-age=86400',
    });

    if (cache && combined.length > 0 && ctx?.waitUntil) {
      ctx.waitUntil(cache.put(cacheKey, response.clone()));
    }

    return response;
  }

  if (path === '/brand-contact') {
    const brand = (url.searchParams.get('brand') || '').trim();
    if (!brand) {
      return jsonResponse({ error: 'brand query parameter is required' }, 400, origin);
    }
    const result = await handleBrandContact(brand, env, fetchImpl);
    return jsonResponse(result, 200, origin, {
      'Cache-Control': 'public, max-age=86400',
    });
  }

  return jsonResponse({ error: 'Not found' }, 404, origin);
}

export default {
  fetch(request, env, ctx) {
    return handleRequest(request, env, ctx);
  },
};
