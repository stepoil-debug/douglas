import { chromium } from 'playwright';
import fs from 'node:fs';

const OUT = 'artifacts/bet365-share-probe';
const SHARE_URL = process.env.BET365_SAMPLE_SHARE_URL || 'https://www.bet365.bet.br/s/r/ZMmHq';
fs.mkdirSync(OUT, { recursive: true });
const write = (name, value) => fs.writeFileSync(`${OUT}/${name}`, typeof value === 'string' ? value : JSON.stringify(value, null, 2));

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  locale: 'pt-BR',
  timezoneId: 'America/Sao_Paulo',
  viewport: { width: 1600, height: 1000 },
});
const page = await context.newPage();
const requests = [];
const responses = [];
const consoleLines = [];
const interesting = /share|shared|bet.?slip|betslip|coupon|selection|event|sports|s\/r|bet365/i;

page.on('console', msg => consoleLines.push(`[${msg.type()}] ${msg.text()}`));
page.on('pageerror', err => consoleLines.push(`[pageerror] ${err.message}`));
page.on('request', req => {
  const url = req.url();
  if (!interesting.test(url)) return;
  let postData = '';
  try { postData = req.postData() || ''; } catch {}
  requests.push({ method: req.method(), url, resourceType: req.resourceType(), postData: postData.slice(0, 10000) });
});
page.on('response', async res => {
  const url = res.url();
  if (!interesting.test(url)) return;
  let body = '';
  const headers = await res.allHeaders().catch(() => ({}));
  const type = String(headers['content-type'] || '');
  if (/json|text|html/i.test(type) && !/javascript/i.test(type)) {
    try { body = (await res.text()).slice(0, 20000); } catch {}
  }
  responses.push({ status: res.status(), url, contentType: type, body });
});

try {
  await page.goto(SHARE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(10000);
  const finalUrl = page.url();
  const title = await page.title();
  const body = (await page.locator('body').innerText().catch(() => '')).slice(0, 150000);
  await page.screenshot({ path: `${OUT}/shared-slip.png`, fullPage: true });
  write('body.txt', body);

  const scripts = await page.evaluate(() => [...document.scripts].map(s => s.src).filter(Boolean));
  const resources = await page.evaluate(() => performance.getEntriesByType('resource').map(r => r.name));
  const jsUrls = [...new Set([...scripts, ...resources.filter(x => /\.js(?:\?|$)/i.test(x))])].slice(0, 25);
  const bundleHits = [];
  const terms = ['sharebet', 'sharedbet', '/s/r/', 'betslip'];
  for (const url of jsUrls) {
    try {
      const res = await context.request.get(url, { timeout: 7000 });
      if (!res.ok()) continue;
      const text = await res.text();
      const lower = text.toLowerCase();
      for (const term of terms) {
        const idx = lower.indexOf(term);
        if (idx >= 0) bundleHits.push({ script: url, term, snippet: text.slice(Math.max(0, idx - 1200), Math.min(text.length, idx + 2600)) });
      }
    } catch {}
  }

  const endpointCandidates = [...new Set([...requests.map(x => x.url), ...responses.map(x => x.url)])]
    .filter(u => /share|shared|bet.?slip|betslip|s\/r|coupon/i.test(u));
  const slipLoaded = /cupom|bilhete|aposta|seleç|selec|retorno|ganhos|odds|cotação|cotacao/i.test(body);
  const blocked = /access denied|forbidden|não disponível|nao disponivel|restricted|bloqueado|cloudflare/i.test(body);

  write('requests.json', requests);
  write('responses.json', responses);
  write('bundle_hits.json', bundleHits);
  const summary = {
    ok: true,
    requestedUrl: SHARE_URL,
    finalUrl,
    title,
    slipLoaded,
    blocked,
    bodyPreview: body.slice(0, 5000),
    requestCount: requests.length,
    responseCount: responses.length,
    endpointCandidates,
    bundleHitCount: bundleHits.length,
    bundleTerms: [...new Set(bundleHits.map(x => x.term))],
  };
  write('summary.json', summary);
  console.log(JSON.stringify(summary, null, 2));
} catch (err) {
  write('summary.json', { ok: false, requestedUrl: SHARE_URL, url: page.url(), message: String(err?.message || err) });
  write('error.txt', String(err?.stack || err));
  console.error(err);
  process.exitCode = 1;
} finally {
  write('console.txt', consoleLines.join('\n'));
  await browser.close();
}
