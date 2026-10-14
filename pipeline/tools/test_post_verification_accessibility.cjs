// Local shell/reflow checks. CSS zoom is explicitly not native browser zoom certification.
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require('C:/Users/jbuck/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const out=path.resolve('artifacts/ux-audit-post-verification');
(async()=>{const b=await chromium.launch({channel:'msedge'});const results=[];try{
for(const theme of ['light','dark'])for(const mode of ['touch','zoom']){
 const c=await b.newContext({viewport:{width:mode==='touch'?390:1440,height:1000},hasTouch:mode==='touch',reducedMotion:'reduce'});
 await c.addInitScript(t=>localStorage.setItem('theme',t),theme);await c.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
 for(const route of ['players','match','sequences','writing-lab','quick-ingest','model-lab','market-values','search']){
 const p=await c.newPage();await p.goto((process.env.AUDIT_ORIGIN||'http://127.0.0.1:8765')+'/'+route+'.html');if(mode==='zoom')await p.evaluate(()=>document.documentElement.style.zoom='2');
 const menu=p.locator('#fsGoto button');if(await menu.isVisible())await menu.click();else await p.evaluate(()=>FutScout.openPalette(''));assert.equal(await p.locator('#fsDestinationLinks a').count(),18);
 const state=await p.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+2,reduced:matchMedia('(prefers-reduced-motion: reduce)').matches,expanded:String(document.getElementById('fsPalette').open)}));assert.ok(!state.overflow,route+' '+mode+' overflow');assert.ok(state.reduced);assert.equal(state.expanded,'true');
 await p.keyboard.press('Escape');assert.ok(!await p.evaluate(()=>document.getElementById('fsPalette').open));if(await menu.isVisible())assert.ok(await menu.evaluate(e=>e===document.activeElement));results.push({route,theme,mode,...state});
 if(route==='players')await p.screenshot({path:path.join(out,`reflow-${theme}-${mode}.png`)});await p.close();
 }await c.close();
}fs.writeFileSync(path.join(out,'accessibility.json'),JSON.stringify({results,boundary:'32 local reduced-motion, touch-emulated or CSS-200%-zoom shell states; external data blocked; not native browser zoom or physical-device/screen-reader certification.'},null,2));console.log(results.length+' reflow/navigation checks passed');
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
