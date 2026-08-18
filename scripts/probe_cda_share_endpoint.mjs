import { chromium } from 'playwright';
import fs from 'node:fs';

const OUT='artifacts/cda-share-endpoint';
const BASE='https://casadeapostas.bet.br';
fs.mkdirSync(OUT,{recursive:true});
const write=(n,v)=>fs.writeFileSync(`${OUT}/${n}`,typeof v==='string'?v:JSON.stringify(v,null,2));

const browser=await chromium.launch({headless:true});
const context=await browser.newContext({locale:'pt-BR',timezoneId:'America/Sao_Paulo'});
const page=await context.newPage();

try{
  await page.goto(`${BASE}/br/sports`,{waitUntil:'domcontentloaded',timeout:60000});
  await page.waitForTimeout(6500);
  const resources=await page.evaluate(()=>performance.getEntriesByType('resource').map(r=>r.name));
  const scripts=await page.evaluate(()=>[...document.scripts].map(s=>s.src).filter(Boolean));
  const js=[...new Set([...scripts,...resources.filter(u=>/\.js(?:\?|$)/i.test(u))])].slice(0,100);
  const needles=['/api/bets/sharebets','sharebets','shareBetslip','sharebetslip','shareBet','share betslip'];
  const matches=[];
  for(let i=0;i<js.length;i+=8){
    const batch=js.slice(i,i+8);
    const loaded=await Promise.all(batch.map(async url=>{
      try{const r=await context.request.get(url,{timeout:9000});if(!r.ok())return null;return {url,text:await r.text()}}catch{return null}
    }));
    for(const item of loaded.filter(Boolean)){
      const lower=item.text.toLowerCase();
      for(const raw of needles){
        const n=raw.toLowerCase();
        let pos=0,count=0;
        while(count<12){
          const idx=lower.indexOf(n,pos);if(idx<0)break;
          const snippet=item.text.slice(Math.max(0,idx-4500),Math.min(item.text.length,idx+8500));
          matches.push({script:item.url,needle:raw,index:idx,snippet});
          pos=idx+n.length;count++;
        }
      }
    }
  }
  const endpointMatches=matches.filter(m=>m.snippet.includes('/api/bets/sharebets'));
  const summary={ok:true,scripts:js.length,totalMatches:matches.length,endpointMatches:endpointMatches.length,scriptsWithEndpoint:[...new Set(endpointMatches.map(m=>m.script))]};
  write('summary.json',summary);
  write('endpoint_matches.json',endpointMatches);
  console.log(JSON.stringify(summary,null,2));
}catch(e){write('summary.json',{ok:false,message:String(e?.message||e)});process.exitCode=1}
finally{await browser.close()}
