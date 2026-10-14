#!/usr/bin/env node
'use strict';

const {chromium}=require('playwright');
const base=(process.env.SMOKE_BASE_URL||'https://futscout.xyz').replace(/\/$/,'');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

const checks=[
  ['Validation','validation.html','#liveSub'],
  ['Methodology','methodology.html','#mGoals'],
  ['Player','players.html?player=367185','.fs-identity-name'],
  ['Team','teams.html?team=Arsenal','.fs-identity-name'],
  ['Match','match.html?game=1993913','.pitch-canvas'],
  ['Insights','insights.html','#content'],
  ['Sequences','sequences.html','#main'],
];

(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:chrome});
  let failed=false;
  try{
    for(const [name,url,ready] of checks){
      const page=await browser.newPage({viewport:{width:1280,height:900}});
      const errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      page.on('response',r=>{if(r.status()>=400&&!/favicon\.ico(?:\?|$)/.test(r.url()))errors.push(`HTTP ${r.status()} ${r.url()}`)});
      await page.addInitScript(()=>localStorage.setItem('siteAccess','granted-v1'));
      const response=await page.goto(`${base}/${url}`,{waitUntil:'domcontentloaded',timeout:60000});
      let visible=false;
      try{await page.locator(ready).first().waitFor({state:'visible',timeout:45000});visible=true}catch{}
      const status=response&&response.status();
      const title=await page.title();
      const ok=status===200&&visible&&errors.length===0;
      console.log(`${ok?'PASS':'FAIL'} ${name}: HTTP ${status}, ready=${visible}, title=${JSON.stringify(title)}${errors.length?`, errors=${errors.join(' | ')}`:''}`);
      if(!ok)failed=true;
      await page.close();
    }
  }finally{await browser.close()}
  if(failed)process.exit(1);
})().catch(e=>{console.error(e.stack||e);process.exit(1)});
