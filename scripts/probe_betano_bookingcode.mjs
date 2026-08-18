import { chromium } from 'playwright';
import fs from 'node:fs';

const OUT = 'artifacts/betano-bookingcode-probe';
const BASE = 'https://www.betano.bet.br';
const SAMPLE_CODE = process.env.BETANO_SAMPLE_BOOKING_CODE || 'F8UJR3LW';
fs.mkdirSync(OUT, { recursive: true });
const write = (name, value) => fs.writeFileSync(`${OUT}/${name}`, typeof value === 'string' ? value : JSON.stringify(value, null, 2));

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  locale: 'pt-BR',
  timezoneId: 'America/Sao_Paulo',
  viewport: { width: 1600, height: 1000 },
});
const page = await context.newPage();
const network = [];
const requests = [];
const consoleLines = [];

const interesting = /booking|book.?code|bet.?slip|betslip|coupon|cupom|share|selection|event|sportsbook|betano/i;
page.on('console', msg => consoleLines.push(`[${msg.type()}] ${msg.text()}`));
page.on('pageerror', err => consoleLines.push(`[pageerror] ${err.message}`));
page.on('request', req => {
  const url = req.url();
  if (interesting.test(url)) {
    let postData = '';
    try { postData = req.postData() || ''; } catch {}
    requests.push({ method: req.method(), url, resourceType: req.resourceType(), postData: postData.slice(0, 4000) });
  }
});
page.on('response', async res => {
  const url = res.url();
  if (!interesting.test(url)) return;
  const headers = await res.allHeaders().catch(() => ({}));
  let body = '';
  const type = String(headers['content-type'] || '');
  if (/json|text|javascript/i.test(type)) {
    try { body = (await res.text()).slice(0, 12000); } catch {}
  }
  network.push({ status: res.status(), url, contentType: type, body });
});

async function dismiss() {
  for (const label of ['Aceitar', 'Aceitar todos', 'Continuar', 'Entendi', 'Fechar']) {
    const loc = page.getByRole('button', { name: new RegExp(`^${label}$`, 'i') });
    if (await loc.count()) {
      try { await loc.first().click({ timeout: 1200 }); } catch {}
    }
  }
}

try {
  const bookingUrl = `${BASE}/bookingcode/${SAMPLE_CODE}`;
  await page.goto(bookingUrl, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await page.waitForTimeout(12000);
  await dismiss();
  await page.waitForTimeout(2500);

  const finalUrl = page.url();
  const title = await page.title();
  const bodyText = (await page.locator('body').innerText().catch(() => '')).slice(0, 120000);
  write('body.txt', bodyText);
  await page.screenshot({ path: `${OUT}/bookingcode.png`, fullPage: true });

  const scripts = await page.evaluate(() => [...document.scripts].map(s => s.src).filter(Boolean));
  const resources = await page.evaluate(() => performance.getEntriesByType('resource').map(r => r.name));
  const jsUrls = [...new Set([...scripts, ...resources.filter(u => /\.js(?:\?|$)/i.test(u))])].slice(0, 120);

  const bundleHits = [];
  for (const url of jsUrls) {
    try {
      const response = await context.request.get(url, { timeout: 25000 });
      if (!response.ok()) continue;
      const text = await response.text();
      const lower = text.toLowerCase();
      const keys = ['bookingcode', 'booking code', 'bookcode', 'book code', 'booking-code', 'booking_code'];
      for (const key of keys) {
        let from = 0;
        let count = 0;
        while (count < 8) {
          const idx = lower.indexOf(key, from);
          if (idx < 0) break;
          bundleHits.push({
            script: url,
            keyword: key,
            snippet: text.slice(Math.max(0, idx - 900), Math.min(text.length, idx + 1700)),
          });
          from = idx + key.length;
          count += 1;
        }
      }
    } catch {}
  }

  write('requests.json', requests);
  write('network.json', network);
  write('bundle_hits.json', bundleHits);
  write('scripts.json', jsUrls);

  const geoblocked = /não está disponível|nao esta disponivel|outside brazil|fora do brasil|localização|localizacao|location/i.test(bodyText);
  const codeVisible = bodyText.toUpperCase().includes(SAMPLE_CODE.toUpperCase());
  const betslipLanguage = /cupom|bilhete|aposta|seleç|selec|odd|cotação|cotacao/i.test(bodyText);
  const endpointCandidates = [...new Set([
    ...requests.map(x => x.url),
    ...network.map(x => x.url),
  ])].filter(u => /booking|book.?code|bet.?slip|betslip|coupon|cupom|share/i.test(u));

  const summary = {
    ok: true,
    sampleCode: SAMPLE_CODE,
    requestedUrl: bookingUrl,
    finalUrl,
    title,
    geoblocked,
    codeVisible,
    betslipLanguage,
    requestCount: requests.length,
    networkCount: network.length,
    endpointCandidates,
    bundleHitCount: bundleHits.length,
    bundleKeywords: [...new Set(bundleHits.map(x => x.keyword))],
    bodyPreview: bodyText.slice(0, 2500),
  };
  write('summary.json', summary);
  console.log(JSON.stringify(summary, null, 2));
} catch (err) {
  const summary = { ok: false, sampleCode: SAMPLE_CODE, message: String(err?.message || err), url: page.url() };
  write('summary.json', summary);
  write('error.txt', String(err?.stack || err));
  console.error(err);
  process.exitCode = 1;
} finally {
  write('console.txt', consoleLines.join('\n'));
  await browser.close();
}
