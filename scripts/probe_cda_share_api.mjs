import { chromium } from 'playwright';
import fs from 'node:fs';

const OUT='artifacts/cda-share-api';
const BASE='https://casadeapostas.bet.br';
const ENDPOINT=`${BASE}/api/bets/sharebets`;
fs.mkdirSync(OUT,{recursive:true});
const write=(n,v)=>fs.writeFileSync(`${OUT}/${n}`,typeof v==='string'?v:JSON.stringify(v,null,2));

const browser=await chromium.launch({headless:true});
const context=await browser.newContext({locale:'pt-BR',timezoneId:'America/Sao_Paulo'});
const page=await context.newPage();

async function call(method,data,headers={}){
  try{
    const opts={method,headers:{'accept':'application/json,text/plain,*/*',...headers},timeout:20000};
    if(data!==undefined){opts.data=data;opts.headers['content-type']='application/json'}
    const r=await context.request.fetch(ENDPOINT,opts);
    const text=(await r.text()).slice(0,30000);
    return {method,status:r.status(),headers:await r.allHeaders(),text};
  }catch(e){return {method,error:String(e?.message||e)}}
}

try{
  await page.goto(`${BASE}/br/sports`,{waitUntil:'domcontentloaded',timeout:60000});
  await page.waitForTimeout(6000);
  const cookies=await context.cookies();
  const tests=[];
  tests.push(await call('GET'));
  tests.push(await call('POST',{}));
  tests.push(await call('POST',[]));
  tests.push(await call('POST',{bets:[]}));
  tests.push(await call('POST',{selections:[]}));
  tests.push(await call('POST',{items:[]}));
  tests.push(await call('POST',{betSlip:[]}));
  tests.push(await call('POST',{betslip:[]}));
  const summary={ok:true,endpoint:ENDPOINT,cookieNames:cookies.map(c=>c.name),tests:tests.map(t=>({method:t.method,status:t.status,error:t.error,text:(t.text||'').slice(0,3000)}))};
  write('summary.json',summary);write('full.json',tests);console.log(JSON.stringify(summary,null,2));
}catch(e){write('summary.json',{ok:false,message:String(e?.message||e)});process.exitCode=1}
finally{await browser.close()}
