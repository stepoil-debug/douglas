import { chromium } from 'playwright';
import fs from 'node:fs';

const OUT = 'artifacts/cda-share-bundles';
const BASE = 'https://casadeapostas.bet.br';
fs.mkdirSync(OUT, { recursive: true });
const write = (name, value) => fs.writeFileSync(`${OUT}/${name}`, typeof value === 'string' ? value : JSON.stringify(value, null, 2));

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ locale: 'pt-BR', timezoneId: 'America/Sao_Paulo' });
const page = await context.newPage();

try {
  await page.goto(`${BASE}/br/sports`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(9000);
  const resources = await page.evaluate(() => performance.getEntriesByType('resource').map(r => r.name));
  const scripts = await page.evaluate(() => [...document.scripts].map(s => s.src).filter(Boolean));
  const jsUrls = [...new Set([...scripts, ...resources.filter(u => /\.js(?:\?|$)/i.test(u))])].slice(0, 100);

  const terms = [
    'sharebet', 'share bet', 'sharebetslip', 'share betslip', 'shareSlip', 'shareBetslip',
    'bookingcode', 'booking code', 'bookcode', 'betSlipShare', 'betslip/share',
    'copy link', 'copiar link', 'compartilhar', 'share', 'betslip'
  ];
  const hits = [];
  let scanned = 0;

  const chunks = [];
  for (let i = 0; i < jsUrls.length; i += 8) chunks.push(jsUrls.slice(i, i + 8));
  for (const chunk of chunks) {
    const results = await Promise.all(chunk.map(async url => {
      try {
        const res = await context.request.get(url, { timeout: 12000 });
        if (!res.ok()) return null;
        const text = await res.text();
        return { url, text };
      } catch { return null; }
    }));
    for (const item of results.filter(Boolean)) {
      scanned++;
      const lower = item.text.toLowerCase();
      for (const raw of terms) {
        const term = raw.toLowerCase();
        let pos = 0, count = 0;
        while (count < 10) {
          const idx = lower.indexOf(term, pos);
          if (idx < 0) break;
          hits.push({
            script: item.url,
            term: raw,
            snippet: item.text.slice(Math.max(0, idx - 1400), Math.min(item.text.length, idx + 3000)),
          });
          pos = idx + term.length;
          count++;
        }
      }
    }
  }

  const endpointRegex = /https?:\\?\/\\?\/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+|\/[A-Za-z0-9._~/-]*(?:share|bet.?slip|booking|coupon|cupom)[A-Za-z0-9._~/?=&%-]*/ig;
  const endpoints = [];
  for (const hit of hits) {
    const found = hit.snippet.match(endpointRegex) || [];
    for (const value of found) endpoints.push(value.replace(/\\\//g, '/'));
  }

  const summary = {
    ok: true,
    scriptCount: jsUrls.length,
    scriptsScanned: scanned,
    hitCount: hits.length,
    termsFound: [...new Set(hits.map(h => h.term))],
    endpointCandidates: [...new Set(endpoints)].slice(0, 200),
  };
  write('summary.json', summary);
  write('hits.json', hits);
  write('scripts.json', jsUrls);
  console.log(JSON.stringify(summary, null, 2));
} catch (err) {
  write('summary.json', { ok: false, message: String(err?.message || err), url: page.url() });
  write('error.txt', String(err?.stack || err));
  process.exitCode = 1;
} finally {
  await browser.close();
}
