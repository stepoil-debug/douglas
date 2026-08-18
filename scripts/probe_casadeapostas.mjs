import { chromium } from 'playwright';
import fs from 'node:fs';

const OUT = 'artifacts/cda-probe';
const BASE = 'https://casadeapostas.bet.br';
fs.mkdirSync(OUT, { recursive: true });

const write = (name, value) => fs.writeFileSync(
  `${OUT}/${name}`,
  typeof value === 'string' ? value : JSON.stringify(value, null, 2),
);

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  locale: 'pt-BR',
  timezoneId: 'America/Sao_Paulo',
  viewport: { width: 1600, height: 1100 },
});
await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: BASE }).catch(() => {});
const page = await context.newPage();

const network = [];
const consoleLines = [];
let popupUrl = '';
page.on('console', msg => consoleLines.push(`[${msg.type()}] ${msg.text()}`));
page.on('pageerror', err => consoleLines.push(`[pageerror] ${err.message}`));
page.on('response', res => {
  const url = res.url();
  if (/share|compart|coupon|cupom|betslip|bet.?slip|booking|book.?bet|slip/i.test(url)) {
    network.push({ status: res.status(), url });
  }
});
page.on('popup', popup => {
  popupUrl = popup.url();
  popup.on('load', () => { popupUrl = popup.url(); });
});

async function settle(ms = 5000) {
  await page.waitForTimeout(ms);
  for (const label of ['Aceitar', 'Aceitar todos', 'Continuar', 'Entendi', 'Fechar']) {
    const loc = page.getByRole('button', { name: new RegExp(`^${label}$`, 'i') });
    if (await loc.count()) {
      try { await loc.first().click({ timeout: 1200 }); } catch {}
    }
  }
}

async function eventLinks() {
  return page.evaluate(() => [...document.querySelectorAll('a[href*="/br/sports/event/"]')]
    .map(a => ({ text: (a.innerText || '').trim().replace(/\s+/g, ' '), href: a.href }))
    .filter((x, i, all) => x.href && all.findIndex(y => y.href === x.href) === i));
}

async function scanOdds() {
  return page.evaluate(() => {
    document.querySelectorAll('[data-probe-odd]').forEach(el => el.removeAttribute('data-probe-odd'));
    const visible = el => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width >= 28 && r.height >= 18 && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity || 1) > 0;
    };
    const out = [];
    let id = 0;
    for (const el of document.querySelectorAll('body *')) {
      if (!visible(el) || el.tagName === 'A') continue;
      const raw = (el.innerText || '').trim().replace(/\s+/g, ' ');
      if (!raw || raw.length > 95) continue;
      const text = raw.replace(/,/g, '.');
      if (/apostar|confirmar|depositar|entrar|cadastre|saque|saldo|retorno potencial/i.test(text)) continue;
      const matches = text.match(/(?:^|\s)(1\.\d{1,2}|[2-9]\.\d{1,2}|10\.\d{1,2})(?:$|\s)/g) || [];
      if (!matches.length) continue;
      const r = el.getBoundingClientRect();
      if (r.width > 560 || r.height > 145) continue;
      const s = getComputedStyle(el);
      const cls = String(el.className || '');
      const role = el.getAttribute('role') || '';
      const score =
        (/odd|price|market|outcome|selection|bet|option/i.test(cls) ? 5 : 0) +
        (s.cursor === 'pointer' ? 4 : 0) +
        (el.tagName === 'BUTTON' || role === 'button' ? 4 : 0) +
        (el.children.length <= 2 ? 2 : 0) -
        Math.min(4, Math.floor((r.width * r.height) / 18000));
      el.setAttribute('data-probe-odd', String(id));
      out.push({
        id: id++, tag: el.tagName, text: raw, cls: cls.slice(0, 320), role,
        cursor: s.cursor, score, x: Math.round(r.x), y: Math.round(r.y),
        w: Math.round(r.width), h: Math.round(r.height),
        html: el.outerHTML.slice(0, 700),
      });
    }
    return out.sort((a, b) => b.score - a.score || a.w * a.h - b.w * b.h).slice(0, 100);
  });
}

async function clickOdd(candidates) {
  for (const c of candidates.slice(0, 30)) {
    const loc = page.locator(`[data-probe-odd="${c.id}"]`).first();
    if (!await loc.count()) continue;
    try {
      await loc.scrollIntoViewIfNeeded({ timeout: 2500 });
      await loc.click({ timeout: 3500 });
      await page.waitForTimeout(2500);
      return c;
    } catch {
      try {
        const box = await loc.boundingBox();
        if (box) {
          await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(2500);
          return c;
        }
      } catch {}
    }
  }
  return null;
}

async function scanShareAndSlip() {
  return page.evaluate(() => {
    const visible = el => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
    };
    const row = el => {
      const r = el.getBoundingClientRect();
      return {
        tag: el.tagName,
        text: (el.innerText || el.value || '').trim().replace(/\s+/g, ' ').slice(0, 300),
        aria: el.getAttribute('aria-label'), title: el.getAttribute('title'),
        testid: el.getAttribute('data-testid') || el.getAttribute('data-test'),
        href: el.getAttribute('href'), cls: String(el.className || '').slice(0, 350),
        html: el.outerHTML.slice(0, 1000), x: Math.round(r.x), y: Math.round(r.y),
        w: Math.round(r.width), h: Math.round(r.height),
      };
    };
    const all = [...document.querySelectorAll('button,a,[role="button"],[aria-label],[title],[data-testid],[data-test],svg')]
      .filter(visible).map(row);
    const shares = all.filter(x => /compart|share|copiar.?link|copy.?link|enviar|mdi-share|fa-share|lucide-share/i.test(JSON.stringify(x)));
    const betting = all.filter(x => /apostar|cupom|bilhete|aposta|retorno|share|compart/i.test(JSON.stringify(x)));

    let aroundBet = [];
    const betButton = [...document.querySelectorAll('button,[role="button"]')].find(el => /^(apostar|fazer aposta|confirmar aposta)$/i.test((el.innerText || '').trim()));
    if (betButton) {
      let root = betButton.parentElement;
      for (let i = 0; i < 5 && root; i++, root = root.parentElement) {
        const candidates = [...root.querySelectorAll('button,a,[role="button"],[aria-label],[title],svg')].filter(visible).map(row);
        if (candidates.length > aroundBet.length) aroundBet = candidates;
        if (candidates.length >= 3) break;
      }
    }
    return { all: all.slice(0, 1000), shares, betting: betting.slice(0, 300), aroundBet: aroundBet.slice(0, 100) };
  });
}

async function clickShare(shares, aroundBet) {
  const direct = [...shares, ...aroundBet.filter(x => /share|compart|copiar.?link|enviar/i.test(JSON.stringify(x)))];
  for (const item of direct) {
    const selectors = [];
    if (item.aria) selectors.push(`[aria-label=${JSON.stringify(item.aria)}]`);
    if (item.title) selectors.push(`[title=${JSON.stringify(item.title)}]`);
    if (item.testid) selectors.push(`[data-testid=${JSON.stringify(item.testid)}]`, `[data-test=${JSON.stringify(item.testid)}]`);
    for (const selector of selectors) {
      try {
        const loc = page.locator(selector).first();
        if (await loc.count()) { await loc.click({ timeout: 2500 }); await page.waitForTimeout(2200); return item; }
      } catch {}
    }
    if (item.text) {
      try {
        const loc = page.getByText(item.text, { exact: true }).first();
        if (await loc.count()) { await loc.click({ timeout: 2500 }); await page.waitForTimeout(2200); return item; }
      } catch {}
    }
  }
  return null;
}

try {
  await page.goto(`${BASE}/br/sports`, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await settle(8000);
  const links = await eventLinks();
  write('event_links.json', links.slice(0, 50));
  if (!links.length) throw new Error('No visible event links');

  const chosen = links[0];
  await page.goto(chosen.href, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await settle(8000);
  write('event_body.txt', (await page.locator('body').innerText()).slice(0, 150000));
  await page.screenshot({ path: `${OUT}/event.png`, fullPage: true });

  const candidates = await scanOdds();
  write('event_odds_candidates.json', candidates);
  if (!candidates.length) throw new Error('No odds-like custom elements found on event page');

  const selected = await clickOdd(candidates);
  if (!selected) throw new Error('Could not click any odds-like element');

  const slipBody = (await page.locator('body').innerText()).slice(0, 160000);
  await page.screenshot({ path: `${OUT}/slip.png`, fullPage: true });
  write('slip_body.txt', slipBody);
  const scan = await scanShareAndSlip();
  write('share_candidates.json', scan.shares);
  write('betting_elements.json', scan.betting);
  write('around_bet_button.json', scan.aroundBet);

  const clickedShare = await clickShare(scan.shares, scan.aroundBet);
  await page.waitForTimeout(1500);
  const afterBody = (await page.locator('body').innerText()).slice(0, 160000);
  write('after_share_body.txt', afterBody);
  await page.screenshot({ path: `${OUT}/after_share.png`, fullPage: true });

  let clipboard = '';
  try { clipboard = await page.evaluate(() => navigator.clipboard.readText()); } catch {}
  const afterScan = await scanShareAndSlip();
  const urlsInBody = afterBody.match(/https?:\/\/[^\s<>"']+/g) || [];
  const hrefs = afterScan.all.map(x => x.href).filter(Boolean);
  const generatedUrls = [...new Set([clipboard, popupUrl, ...urlsInBody, ...hrefs, ...network.map(x => x.url)].filter(Boolean))]
    .filter(url => /casadeapostas|share|slip|coupon|cupom|booking|book/i.test(url));

  const summary = {
    ok: true,
    stage: 'FILLED_SLIP',
    event: chosen,
    selectionClicked: selected,
    hasSlipLanguage: /cupom|bilhete|retorno potencial|valor da aposta|aposta simples|aposta múltipla/i.test(slipBody),
    shareCandidates: scan.shares,
    aroundBetButton: scan.aroundBet,
    shareClicked: clickedShare,
    clipboard,
    popupUrl,
    generatedUrls,
    networkCandidates: network,
  };
  write('summary.json', summary);
  console.log(JSON.stringify(summary, null, 2));
} catch (err) {
  let diagnostics = [];
  try { diagnostics = await scanOdds(); } catch {}
  const summary = {
    ok: false, stage: 'ERROR', message: String(err?.message || err), url: page.url(),
    oddsCandidates: diagnostics.slice(0, 30), networkCandidates: network,
  };
  write('summary.json', summary);
  write('error.txt', String(err?.stack || err));
  console.error(err);
  process.exitCode = 1;
} finally {
  write('console.txt', consoleLines.join('\n'));
  await browser.close();
}
