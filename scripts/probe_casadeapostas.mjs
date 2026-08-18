import { chromium } from 'playwright';
import fs from 'node:fs';

const OUT = 'artifacts/cda-probe';
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  locale: 'pt-BR',
  timezoneId: 'America/Sao_Paulo',
  viewport: { width: 1600, height: 1000 },
});
const page = await context.newPage();
const consoleLines = [];
page.on('console', msg => consoleLines.push(`[${msg.type()}] ${msg.text()}`));
page.on('pageerror', err => consoleLines.push(`[pageerror] ${err.message}`));

try {
  await page.goto('https://casadeapostas.bet.br/br/sports', { waitUntil: 'domcontentloaded', timeout: 90000 });
  await page.waitForTimeout(12000);

  // Best effort cookie/geolocation banners; never submit a wager.
  for (const label of ['Aceitar', 'Aceitar todos', 'Continuar', 'Entendi']) {
    const btn = page.getByRole('button', { name: new RegExp(`^${label}$`, 'i') });
    if (await btn.count()) {
      try { await btn.first().click({ timeout: 2500 }); } catch {}
    }
  }

  await page.screenshot({ path: `${OUT}/sports.png`, fullPage: true });
  fs.writeFileSync(`${OUT}/sports.html`, await page.content());
  fs.writeFileSync(`${OUT}/body.txt`, (await page.locator('body').innerText()).slice(0, 100000));

  const elements = await page.evaluate(() => {
    const visible = el => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
    };
    const rows = [];
    for (const el of document.querySelectorAll('button,a,input,[role="button"],[aria-label],[title]')) {
      if (!visible(el)) continue;
      rows.push({
        tag: el.tagName,
        text: (el.innerText || el.value || '').trim().replace(/\s+/g, ' ').slice(0, 240),
        aria: el.getAttribute('aria-label'),
        title: el.getAttribute('title'),
        placeholder: el.getAttribute('placeholder'),
        href: el.getAttribute('href'),
        cls: String(el.className || '').slice(0, 300),
      });
    }
    return rows;
  });
  fs.writeFileSync(`${OUT}/elements.json`, JSON.stringify(elements, null, 2));

  const keywords = /compart|share|cupom|bilhete|aposta|buscar|pesquis|futebol/i;
  const interesting = elements.filter(row => keywords.test(JSON.stringify(row))).slice(0, 500);
  fs.writeFileSync(`${OUT}/interesting.json`, JSON.stringify(interesting, null, 2));

  const summary = {
    ok: true,
    url: page.url(),
    title: await page.title(),
    visibleElements: elements.length,
    interestingElements: interesting.length,
    shareCandidates: interesting.filter(x => /compart|share/i.test(JSON.stringify(x))),
  };
  fs.writeFileSync(`${OUT}/summary.json`, JSON.stringify(summary, null, 2));
  console.log(JSON.stringify(summary, null, 2));
} catch (err) {
  fs.writeFileSync(`${OUT}/error.txt`, String(err?.stack || err));
  console.error(err);
  process.exitCode = 1;
} finally {
  fs.writeFileSync(`${OUT}/console.txt`, consoleLines.join('\n'));
  await browser.close();
}
