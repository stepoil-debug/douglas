import { chromium } from 'playwright';
import fs from 'node:fs';

const OUT = 'artifacts/cda-probe';
const BASE = 'https://casadeapostas.bet.br';
fs.mkdirSync(OUT, { recursive: true });
const write = (n,v) => fs.writeFileSync(`${OUT}/${n}`, typeof v === 'string' ? v : JSON.stringify(v,null,2));

const browser = await chromium.launch({ headless:true });
const context = await browser.newContext({ locale:'pt-BR', timezoneId:'America/Sao_Paulo', viewport:{width:1600,height:1100} });
const page = await context.newPage();

async function settle(ms=6000){
  await page.waitForTimeout(ms);
  for(const label of ['Aceitar','Aceitar todos','Continuar','Entendi','Fechar']){
    const b=page.getByRole('button',{name:new RegExp(`^${label}$`,'i')});
    if(await b.count()) try{await b.first().click({timeout:1000})}catch{}
  }
}

async function clickOneOdd(){
  const rows=await page.evaluate(()=>{
    let id=0; const out=[];
    const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>25&&r.height>18&&s.display!=='none'&&s.visibility!=='hidden'};
    for(const el of document.querySelectorAll('body *')){
      if(!visible(el)||el.tagName==='A')continue;
      const raw=(el.innerText||'').trim().replace(/\s+/g,' '); if(!raw||raw.length>70)continue;
      const t=raw.replace(/,/g,'.');
      if(/apostar|confirmar|depositar|entrar|cadastre|retorno/i.test(t))continue;
      if(!/(?:^|\s)(1\.\d{1,2}|[2-9]\.\d{1,2}|10\.\d{1,2})(?:$|\s)/.test(t))continue;
      const r=el.getBoundingClientRect(),s=getComputedStyle(el),cls=String(el.className||'');
      if(r.width>500||r.height>130)continue;
      const score=(/event-market-odd|odd|market|outcome|selection|price/i.test(cls)?8:0)+(s.cursor==='pointer'?5:0)+(el.children.length<=2?2:0);
      el.dataset.cdaOdd=String(id);
      out.push({id:id++,score,text:raw,tag:el.tagName,cls:cls.slice(0,300),cursor:s.cursor,w:Math.round(r.width),h:Math.round(r.height)});
    }
    return out.sort((a,b)=>b.score-a.score).slice(0,80);
  });
  write('control_probe_odds.json',rows);
  for(const row of rows){
    const loc=page.locator(`[data-cda-odd="${row.id}"]`).first();
    if(!await loc.count())continue;
    try{await loc.scrollIntoViewIfNeeded();await loc.click({timeout:2500});await page.waitForTimeout(2200);return row}catch{}
  }
  return null;
}

async function inspectSlip(){
  return page.evaluate(()=>{
    const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'};
    const info=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return {
      tag:el.tagName,text:(el.innerText||'').trim().replace(/\s+/g,' ').slice(0,300),
      aria:el.getAttribute('aria-label'),title:el.getAttribute('title'),role:el.getAttribute('role'),
      cls:String(el.className||'').slice(0,420),cursor:s.cursor,
      html:el.outerHTML.slice(0,1800),x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)
    }};
    const textEls=[...document.querySelectorAll('body *')].filter(el=>visible(el)&&/apostar|cupom|bilhete|retorno potencial|valor da aposta|aposta simples|aposta múltipla/i.test((el.innerText||'').trim())&&(el.innerText||'').trim().length<250);
    const anchors=textEls.map(info).slice(0,100);
    let bestRoot=null,bestControls=[];
    for(const anchor of textEls){
      let root=anchor;
      for(let depth=0;depth<9&&root;depth++,root=root.parentElement){
        const controls=[...root.querySelectorAll('button,a,[role="button"],[aria-label],[title],[class*="cursor-pointer"],svg')].filter(visible).map(info);
        if(controls.length>bestControls.length&&controls.length<=100){bestControls=controls;bestRoot=info(root)}
        if(controls.length>=5&&/apostar/i.test(root.innerText||'')){bestControls=controls;bestRoot=info(root);break}
      }
    }
    const iconOnly=bestControls.filter(x=>!x.text&&x.w<=90&&x.h<=90&&(x.tag==='BUTTON'||x.tag==='SVG'||x.cursor==='pointer'));
    const shareHints=bestControls.filter(x=>/share|compart|copiar|copy|enviar/i.test(JSON.stringify(x)));
    return {anchors,bestRoot,bestControls,iconOnly,shareHints};
  });
}

try{
  await page.goto(`${BASE}/br/sports`,{waitUntil:'domcontentloaded',timeout:90000});await settle(7000);
  const links=await page.evaluate(()=>[...document.querySelectorAll('a[href*="/br/sports/event/"]')].map(a=>({text:(a.innerText||'').trim().replace(/\s+/g,' '),href:a.href})).filter((x,i,a)=>x.href&&a.findIndex(y=>y.href===x.href)===i));
  if(!links.length)throw new Error('no event link');
  await page.goto(links[0].href,{waitUntil:'domcontentloaded',timeout:90000});await settle(7000);
  const selected=await clickOneOdd(); if(!selected)throw new Error('no selectable odd');
  const inspection=await inspectSlip();
  write('slip_controls_full.json',inspection);
  await page.screenshot({path:`${OUT}/slip_controls.png`,fullPage:true});
  const summary={ok:true,event:links[0],selection:selected,anchorCount:inspection.anchors.length,controlCount:inspection.bestControls.length,iconOnly:inspection.iconOnly,shareHints:inspection.shareHints,bestRoot:inspection.bestRoot};
  write('controls_summary.json',summary); console.log(JSON.stringify(summary,null,2));
}catch(e){write('controls_summary.json',{ok:false,message:String(e?.message||e),url:page.url()});process.exitCode=1}
finally{await browser.close()}
