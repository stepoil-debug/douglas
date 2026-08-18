import { chromium } from 'playwright';
import fs from 'node:fs';

const OUT='artifacts/cda-share-endpoint';
const BASE='https://casadeapostas.bet.br';
fs.mkdirSync(OUT,{recursive:true});
const write=(n,v)=>fs.writeFileSync(`${OUT}/${n}`,typeof v==='string'?v:JSON.stringify(v,null,2));

const browser=await chromium.launch({headless:true});
const context=await browser.newContext({locale:'pt-BR',timezoneId:'America/Sao_Paulo'});
const page=await context.newPage();

function extracts(text, pattern, before=4500, after=9000, limit=12){
  const lower=text.toLowerCase();
  const needle=pattern.toLowerCase();
  const out=[]; let pos=0;
  while(out.length<limit){
    const idx=lower.indexOf(needle,pos); if(idx<0)break;
    out.push({pattern,index:idx,snippet:text.slice(Math.max(0,idx-before),Math.min(text.length,idx+after))});
    pos=idx+needle.length;
  }
  return out;
}

try{
  await page.goto(`${BASE}/br/sports`,{waitUntil:'domcontentloaded',timeout:60000});
  await page.waitForTimeout(6500);
  const resources=await page.evaluate(()=>performance.getEntriesByType('resource').map(r=>r.name));
  const scripts=await page.evaluate(()=>[...document.scripts].map(s=>s.src).filter(Boolean));
  const js=[...new Set([...scripts,...resources.filter(u=>/\.js(?:\?|$)/i.test(u))])].slice(0,100);
  const targetNeedles=['/api/bets/sharebets','shareBetSlip:','shareData:','tB=','tB =','a5)(','a5)(','restoreBetSlip','retrieveSharedBet'];
  const matches=[];
  let targetScript='';
  let targetText='';
  for(let i=0;i<js.length;i+=8){
    const batch=js.slice(i,i+8);
    const loaded=await Promise.all(batch.map(async url=>{
      try{const r=await context.request.get(url,{timeout:9000});if(!r.ok())return null;return {url,text:await r.text()}}catch{return null}
    }));
    for(const item of loaded.filter(Boolean)){
      if(item.text.includes('/api/bets/sharebets')){targetScript=item.url;targetText=item.text;break}
    }
    if(targetText)break;
  }
  if(!targetText)throw new Error('sharebets bundle not found');

  for(const needle of targetNeedles){
    for(const row of extracts(targetText,needle)) matches.push({script:targetScript,...row});
  }
  const specific=[];
  for(const regex of [
    /tB\s*=\s*async/g,
    /tB\s*=\s*\(/g,
    /shareBetSlip\s*:/g,
    /\(0,[A-Za-z_$][\w$]*\.a5\)\(/g,
    /\.a5\)\(/g,
  ]){
    let m,count=0;
    while((m=regex.exec(targetText))&&count<15){specific.push({pattern:String(regex),index:m.index,snippet:targetText.slice(Math.max(0,m.index-6500),Math.min(targetText.length,m.index+12000))});count++}
  }

  const summary={ok:true,script:targetScript,targetLength:targetText.length,matches:matches.length,specificMatches:specific.length,patterns:[...new Set(matches.map(m=>m.pattern))]};
  write('summary.json',summary);
  write('endpoint_matches.json',matches);
  write('specific_matches.json',specific);
  console.log(JSON.stringify(summary,null,2));
}catch(e){write('summary.json',{ok:false,message:String(e?.message||e)});process.exitCode=1}
finally{await browser.close()}
