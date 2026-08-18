import { chromium } from 'playwright';
import fs from 'node:fs';

const OUT = 'artifacts/cda-probe';
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  locale: 'pt-BR',
  timezoneId: 'America/Sao_Paulo',
  viewport: { width: 1600, height: 1100 },
});
await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'https://casadeapostas.bet.br' }).catch(() => {});

const page = await context.newPage();
const consoleLines = [];
const networkCandidates = [];
let popupUrl = null;

page.on('console', msg => consoleLines.push(`[${msg.type()}] ${msg.text()}`));
page.on('pageerror', err => consoleLines.push(`[pageerror] ${err.message}`));
page.on('response', response => {
  const url = response.url();
  if (/share|compart|coupon|cupom|betslip|bet-slip|booking|book.?bet|slip/i.test(url)) {
    networkCandidates.push({ status: response.status(), url });
  }
});
page.on('popup', popup => {
  popupUrl = popup.url();
  popup.on('load', () => { popupUrl = popup.url(); });
});

function write(name, value) {
  fs.writeFileSync(`${OUT}/${name}`, typeof value === 'string' ? value : JSON.stringify(value, null, 2));
}

async function dismissBanners() {
  for (const label of ['Aceitar', 'Aceitar todos', 'Continuar', 'Entendi', 'Fechar']) {
    const btn = page.getByRole('button', { name: new RegExp(`^${label}$`, 'i') });
    if (await btn.count()) {
      try { await btn.first().click({ timeout: 1800 }); } catch {}
    }
  }
}

async function visibleElements() {
  return page.evaluate(() => {
    const visible = el => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity || 1) > 0;
    };
    const rows = [];
    const selector = 'button,a,input,[role="button"],[aria-label],[title],[data-testid],[data-test],[class*="odd" i],[class*="bet" i],[class*="share" i]';
    for (const el of document.querySelectorAll(selector)) {
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      rows.push({
        tag: el.tagName,
        text: (el.innerText || el.value || '').trim().replace(/\s+/g, ' ').slice(0, 320),
        aria: el.getAttribute('aria-label'),
        title: el.getAttribute('title'),
        placeholder: el.getAttribute('placeholder'),
        href: el.getAttribute('href'),
        testid: el.getAttribute('data-testid') || el.getAttribute('data-test'),
        cls: String(el.className || '').slice(0, 400),
        x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
      });
    }
    return rows;
  });
}

function shareCandidates(elements) {
  return elements.filter(row => /compart|share|enviar|copiar link|copy link/i.test(JSON.stringify(row)));
}

function oddsCandidates(elements) {
  return elements.filter(row => {
    const text = String(row.text || '').replace(',', '.');
    const nums = text.match(/\b(?:1|2|3|4|5|6|7|8|9|10)\.\d{1,2}\b/g) || [];
    if (!nums.length) return false;
    if (!/BUTTON|DIV|SPAN/.test(String(row.tag))) return false;
    if (/apostar|confirmar|depositar|saque/i.test(text)) return false;
    return row.w > 24 && row.h > 18 && row.w < 650 && row.h < 180;
  });
}

async function clickFirstSafeOdd() {
  const candidates = await page.locator('button,[role="button"]').evaluateAll(elements => {
    const visible = el => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
    };
    return elements.map((el, index) => ({
      index,
      text: (el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 220),
      rect: (() => { const r = el.getBoundingClientRect(); return { x:r.x,y:r.y,w:r.width,h:r.height }; })(),
      visible: visible(el),
    })).filter(row => {
      if (!row.visible) return false;
      const t = row.text.replace(',', '.');
      if (/apostar|confirmar|depositar|entrar|cadastre|login/i.test(t)) return false;
      const odds = t.match(/\b(?:1|2|3|4|5|6|7|8|9|10)\.\d{1,2}\b/g) || [];
      return odds.length > 0 && row.rect.w > 25 && row.rect.h > 20 && row.rect.w < 650 && row.rect.h < 180;
    }).slice(0, 40);
  });

  write('selection_candidates.json', candidates);
  for (const candidate of candidates) {
    const loc = page.locator('button,[role="button"]').nth(candidate.index);
    try {
      await loc.scrollIntoViewIfNeeded({ timeout: 2000 });
      await loc.click({ timeout: 3000 });
      await page.waitForTimeout(3500);
      const body = await page.locator('body').innerText();
      if (/cupom|bilhete|minhas apostas|aposta simples|aposta múltipla|retorno potencial|valor da aposta/i.test(body)) {
        return candidate;
      }
      // A selection may still be active without those labels; keep the first successful click.
      return candidate;
    } catch {}
  }
  return null;
}

async function clickShareCandidate(elements) {
  const rows = shareCandidates(elements);
  write('share_candidates_before_click.json', rows);
  for (const row of rows) {
    const selectors = [];
    if (row.aria) selectors.push(`[aria-label=${JSON.stringify(row.aria)}]`);
    if (row.title) selectors.push(`[title=${JSON.stringify(row.title)}]`);
    if (row.testid) selectors.push(`[data-testid=${JSON.stringify(row.testid)}]`, `[data-test=${JSON.stringify(row.testid)}]`);
    for (const selector of selectors) {
      const loc = page.locator(selector).first();
      if (await loc.count()) {
        try { await loc.click({ timeout: 2500 }); await page.waitForTimeout(2500); return row; } catch {}
      }
    }
    const text = String(row.text || '').trim();
    if (text) {
      const loc = page.getByText(text, { exact: true }).first();
      if (await loc.count()) {
        try { await loc.click({ timeout: 2500 }); await page.waitForTimeout(2500); return row; } catch {}
      }
    }
  }
  return null;
}

try {
  await page.goto('https://casadeapostas.bet.br/br/sports', { waitUntil: 'domcontentloaded', timeout: 90000 });
  await page.waitForTimeout(9000);
  await dismissBanners();

  const sportsElements = await visibleElements();
  write('sports_elements.json', sportsElements);
  await page.screenshot({ path: `${OUT}/sports.png`, fullPage: true });

  const eventLinks = sportsElements
    .filter(row => row.href && /\/br\/sports\/event\//i.test(row.href))
    .map(row => ({ text: row.text, href: row.href }))
    .filter((row, index, all) => all.findIndex(x => x.href === row.href) === index);
  write('event_links.json', eventLinks.slice(0, 50));
  if (!eventLinks.length) throw new Error('No event link was visible on sports page');

  const chosenEvent = eventLinks[0];
  const eventUrl = new URL(chosenEvent.href, page.url()).href;
  await page.goto(eventUrl, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await page.waitForTimeout(9000);
  await dismissBanners();

  const eventElements = await visibleElements();
  write('event_elements.json', eventElements);
  write('event_odds_candidates.json', oddsCandidates(eventElements));
  write('event_body.txt', (await page.locator('body').innerText()).slice(0, 120000));
  await page.screenshot({ path: `${OUT}/event.png`, fullPage: true });

  const selected = await clickFirstSafeOdd();
  if (!selected) throw new Error('Could not identify/click a safe odds selection on event page');

  const slipElements = await visibleElements();
  const slipBody = (await page.locator('body').innerText()).slice(0, 120000);
  write('slip_elements.json', slipElements);
  write('slip_body.txt', slipBody);
  await page.screenshot({ path: `${OUT}/slip.png`, fullPage: true });

  const shares = shareCandidates(slipElements);
  const clickedShare = await clickShareCandidate(slipElements);
  const afterShareElements = await visibleElements();
  const afterShareBody = (await page.locator('body').innerText()).slice(0, 120000);
  write('after_share_elements.json', afterShareElements);
  write('after_share_body.txt', afterShareBody);
  await page.screenshot({ path: `${OUT}/after_share.png`, fullPage: true });

  let clipboard = '';
  try { clipboard = await page.evaluate(() => navigator.clipboard.readText()); } catch {}

  const bodyUrls = [...new Set((afterShareBody.match(/https?:\/\/[^\s<>"']+/g) || []).map(x => x.replace(/[),.;]+$/, '')))];
  const linkElements = afterShareElements.filter(row => row.href && /share|bet|sports|slip|coupon|cupom|book/i.test(row.href));
  const generatedUrls = [...new Set([
    clipboard,
    popupUrl,
    ...bodyUrls,
    ...linkElements.map(x => x.href),
    ...networkCandidates.map(x => x.url),
  ].filter(Boolean))];

  const summary = {
    ok: true,
    stage: 'FILLED_SLIP',
    sportsUrl: 'https://casadeapostas.bet.br/br/sports',
    event: { label: chosenEvent.text, url: eventUrl },
    selectionClicked: selected,
    shareCandidates: shares,
    shareClicked: clickedShare,
    clipboard,
    popupUrl,
    generatedUrls,
    networkCandidates,
    hasFilledSlipLanguage: /cupom|bilhete|retorno potencial|valor da aposta|aposta múltipla/i.test(slipBody),
    hasShareAfterSelection: shares.length > 0,
  };
  write('summary.json', summary);
  console.log(JSON.stringify(summary, null, 2));
} catch (err) {
  const summary = { ok: false, stage: 'ERROR', message: String(err?.message || err), url: page.url(), networkCandidates };
  write('summary.json', summary);
  write('error.txt', String(err?.stack || err));
  console.error(err);
  process.exitCode = 1;
} finally {
  write('console.txt', consoleLines.join('\n'));
  await browser.close();
}
