const {chromium}=require(process.env.PLAYWRIGHT_PATH||'C:/Users/jbuck/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path');
(async()=>{const baseline=process.argv.includes('--baseline');const out=path.resolve('artifacts/ux-audit',baseline?'before':'after');fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({channel:'msedge',headless:true});const results=[];
for(const theme of ['light','dark'])for(const width of (baseline?[390,1440]:[320,375,390,640,768,1024,1440,1920])){
const context=await browser.newContext({viewport:{width,height:900}});
await context.addInitScript(t=>localStorage.setItem('theme',t),theme);
await context.route('**/*',route=>{const u=new URL(route.request().url());if(u.hostname!=='127.0.0.1')return route.abort();if(!baseline)return route.continue();const file=path.resolve('artifacts/ux-audit/baseline/dashboard','.'+u.pathname);return fs.existsSync(file)?route.fulfill({path:file,contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'application/octet-stream'}):route.fulfill({status:404,body:''});});
for(const name of ['index','players','teams','match','sequences','search','insights','market-values','glossary','guide','methodology','validation','evidence-contracts','model-review','model-lab','match-review','writing-lab','quick-ingest']){
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto((process.env.AUDIT_ORIGIN||'http://127.0.0.1:8765')+'/'+name+'.html',{waitUntil:'domcontentloaded'});await page.waitForTimeout(150);
 const nav=page.locator('#fsGoto button');if(await nav.count()){if(await nav.isVisible())await nav.click();else await page.evaluate(()=>FutScout.openPalette(''));}
 await page.screenshot({path:path.join(out,`${name}-${theme}-${width}.png`)});
 const state=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+2,links:document.querySelectorAll('#fsDestinationLinks a').length,bg:document.querySelector('#fsPalette')?getComputedStyle(document.querySelector('#fsPalette')).backgroundColor:null}));
 results.push({name,theme,width,...state,errors});await page.close();
}await context.close();}
await browser.close();fs.writeFileSync(path.join(out,'browser-smoke.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results.filter(r=>r.errors.length||r.overflow||r.links!==18),null,2));})();
