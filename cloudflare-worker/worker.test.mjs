import assert from 'node:assert/strict';
import test from 'node:test';
import {
  classifyWebResult,
  extractDdgResults,
  extractEmailAndPhoneFromHtml,
  extractRelevantPageExcerpt,
  handleRequest,
  isSafePublicUrl,
  isValidSupportEmail,
  resolveCorsOrigin,
} from './worker.js';

test('CORS allows GitHub Pages and localhost, blocks unknown origins', () => {
  assert.equal(
    resolveCorsOrigin('https://omermd007.github.io'),
    'https://omermd007.github.io'
  );
  assert.equal(resolveCorsOrigin('http://localhost:5173'), 'http://localhost:5173');
  assert.equal(resolveCorsOrigin('http://127.0.0.1:8000'), 'http://127.0.0.1:8000');
  assert.equal(resolveCorsOrigin('https://evil.example.org'), null);
  assert.equal(
    resolveCorsOrigin('https://custom.domain.com', {
      ALLOWED_ORIGINS: 'https://custom.domain.com',
    }),
    'https://custom.domain.com'
  );
});

test('SSRF URL and support email guards reject unsafe targets and placeholders', () => {
  assert.equal(isSafePublicUrl('https://www.tillamook.com/faq'), true);
  assert.equal(isSafePublicUrl('http://127.0.0.1:8000/api'), false);
  assert.equal(isSafePublicUrl('http://169.254.169.254/latest'), false);
  assert.equal(isSafePublicUrl('http://localhost/admin'), false);
  assert.equal(isSafePublicUrl('file:///etc/passwd'), false);
  assert.equal(isSafePublicUrl('https://user:pass@brand.com/contact'), false);

  assert.equal(isValidSupportEmail('help@goodles.com', 'www.goodles.com'), true);
  assert.equal(isValidSupportEmail('support@example.com'), false);
  assert.equal(isValidSupportEmail('noreply@goodles.com', 'goodles.com'), false);
  assert.equal(isValidSupportEmail('privacy@goodles.com', 'goodles.com'), false);
  assert.equal(isValidSupportEmail('care@otherdomain.com', 'goodles.com'), false);
});

test('classifyWebResult distinguishes brand FAQs, U.S. halal directories, Reddit, and web', () => {
  assert.deepEqual(
    classifyWebResult('https://www.tillamook.com/faq/cheese-enzymes', 'Tillamook'),
    { platform: 'brand_faq', source: 'Official Tillamook site (tillamook.com)' }
  );
  assert.deepEqual(
    classifyWebResult('https://www.muslimconsumergroup.com/product/kraft', 'Kraft'),
    { platform: 'halal_directory', source: 'Muslim Consumer Group' }
  );
  assert.deepEqual(
    classifyWebResult('https://www.ifanca.org/certified-products', 'Saffron Road'),
    { platform: 'halal_directory', source: 'IFANCA' }
  );
  assert.deepEqual(
    classifyWebResult('https://www.reddit.com/r/halal/comments/abc123/', 'Kraft'),
    { platform: 'reddit', source: 'r/halal' }
  );
});

test('extractDdgResults parses DDG HTML links and filters aggregators', () => {
  const html = `
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.muslimconsumergroup.com%2Fcheese">MCG Cheese Guide</a>
      <a class="result__snippet">Tillamook uses microbial enzymes in retail cheddar.</a>
    </div>
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fpissedconsumer.com%2Ftillamook">PissedConsumer</a>
      <a class="result__snippet">Complaints</a>
    </div>
  `;
  const parsed = extractDdgResults(html);
  assert.equal(parsed.length, 1);
  assert.equal(parsed[0].url, 'https://www.muslimconsumergroup.com/cheese');
  assert.match(parsed[0].snippet, /microbial enzymes/i);
});

test('GET /health returns capabilities and CORS header', async () => {
  const req = new Request('https://halallens-scanner.workers.dev/health', {
    headers: { Origin: 'https://omermd007.github.io' },
  });
  const res = await handleRequest(req, { BRAVE_API_KEY: 'test-key' });
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('Access-Control-Allow-Origin'), 'https://omermd007.github.io');
  const body = await res.json();
  assert.equal(body.status, 'ok');
  assert.equal(body.capabilities.brave_search, true);
  assert.equal(body.capabilities.reddit_archive, true);
  assert.equal(body.capabilities.brand_contact_lookup, true);
});

test('GET /scan aggregates Brave web + halal directories + Arctic Shift Reddit + FAQ extraction', async () => {
  const mockFetch = async (url) => {
    const u = String(url);
    if (u.startsWith('https://api.search.brave.com/')) {
      return new Response(
        JSON.stringify({
          web: {
            results: [
              {
                url: 'https://www.tillamook.com/faq/enzymes',
                title: 'Are Tillamook cheese enzymes vegetarian?',
                description: 'Learn about Tillamook enzymes.',
                page_age: '2026-09-15T00:00:00',
              },
              {
                url: 'https://www.muslimconsumergroup.com/tillamook-cheddar',
                title: 'Tillamook Cheddar — Halal Status',
                description: 'MCG lists Tillamook cheddar as using microbial rennet.',
              },
            ],
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    }
    if (u.startsWith('https://arctic-shift.photon-reddit.com/')) {
      if (u.includes('subreddit=halal')) {
        return new Response(
          JSON.stringify({
            data: [
              {
                id: 'abc123',
                subreddit: 'halal',
                permalink: '/r/halal/comments/abc123/tillamook_cheddar/',
                title: 'Confirmed Tillamook U.S. cheddar uses microbial enzymes',
                author: 'us_shopper',
                created_utc: 1785000000,
                selftext: 'I contacted Tillamook and they confirmed their cheddar uses microbial enzymes.',
              },
            ],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        );
      }
      return new Response(JSON.stringify({ data: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (u === 'https://www.tillamook.com/faq/enzymes') {
      return new Response(
        '<html><body><p>Welcome to Tillamook.</p><p>All Tillamook retail cheddar cheeses are made with non-animal microbial enzymes (fermentation-produced chymosin) suitable for vegetarians.</p></body></html>',
        { status: 200, headers: { 'Content-Type': 'text/html' } }
      );
    }
    return new Response('', { status: 404 });
  };

  const req = new Request(
    'https://halallens-scanner.workers.dev/scan?brand=Tillamook&product=Sharp+Cheddar&ingredients=enzymes,cheese+culture',
    { headers: { Origin: 'https://omermd007.github.io' } }
  );
  const res = await handleRequest(req, { BRAVE_API_KEY: 'fake-key' }, null, mockFetch);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.ok, true);
  assert.equal(body.items.length, 3);

  const faq = body.items.find((i) => i.platform === 'brand_faq');
  assert.ok(faq);
  assert.match(faq.excerpt, /non-animal microbial enzymes/i);

  const dir = body.items.find((i) => i.platform === 'halal_directory');
  assert.ok(dir);
  assert.equal(dir.source, 'Muslim Consumer Group');

  const reddit = body.items.find((i) => i.platform === 'reddit');
  assert.ok(reddit);
  assert.equal(reddit.source, 'r/halal');
});

test('GET /brand-contact discovers official contact page and filters out bad emails', async () => {
  const mockFetch = async (url) => {
    const u = String(url);
    if (u.startsWith('https://api.search.brave.com/')) {
      return new Response(
        JSON.stringify({
          web: {
            results: [
              { url: 'https://pissedconsumer.com/sunrise-bakery', title: 'Complaints' },
              { url: 'https://www.sunrisebakery.com/contact-us', title: 'Contact Sunrise Bakery' },
            ],
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    }
    if (u === 'https://www.sunrisebakery.com/contact-us') {
      return new Response(
        `<html><body>
          <a href="mailto:noreply@sunrisebakery.com">No Reply</a>
          <a href="mailto:test@example.com">Placeholder</a>
          <a href="mailto:care@sunrisebakery.com">Consumer Care</a>
          <p>Toll free: 1-800-555-0142</p>
        </body></html>`,
        { status: 200, headers: { 'Content-Type': 'text/html' } }
      );
    }
    return new Response('', { status: 404 });
  };

  const req = new Request(
    'https://halallens-scanner.workers.dev/brand-contact?brand=Sunrise+Bakery',
    { headers: { Origin: 'https://omermd007.github.io' } }
  );
  const res = await handleRequest(req, { BRAVE_API_KEY: 'fake-key' }, null, mockFetch);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.source, 'web_lookup');
  assert.equal(body.contact_type, 'email');
  assert.equal(body.email, 'care@sunrisebakery.com');
  assert.equal(body.contact_url, 'https://www.sunrisebakery.com/contact-us');
  assert.equal(body.phone, '1-800-555-0142');
});

test('extractRelevantPageExcerpt picks the highest-signal ingredient sentence', () => {
  const html = `
    <html><body>
      <p>Subscribe to our newsletter for seasonal coupons and recipes.</p>
      <p>Our cream cheese uses only bacterial cheese cultures and vegetarian microbial enzymes.</p>
    </body></html>
  `;
  const excerpt = extractRelevantPageExcerpt(html, 'Philadelphia', ['cheese culture']);
  assert.match(excerpt, /bacterial cheese cultures/i);
});

test('extractEmailAndPhoneFromHtml ranks consumer care email above generic info', () => {
  const html = `
    <a href="mailto:info@acmedairy.com">Info</a>
    <a href="mailto:customercare@acmedairy.com">Care</a>
  `;
  const res = extractEmailAndPhoneFromHtml(html, 'https://acmedairy.com/contact');
  assert.equal(res.email, 'customercare@acmedairy.com');
});
