#!/usr/bin/env node
/* Reproducible visual baselines for the three data-visualization surfaces.
 * Run with --update after an intentional visual change, then without it in CI.
 * Requires playwright, pixelmatch and pngjs on NODE_PATH. */
'use strict';
const fs=require('fs'),path=require('path'),http=require('http'),os=require('os');
const {execFileSync}=require('child_process');
const {chromium}=require('playwright');
const pixelmatchModule=require('pixelmatch');
const pixelmatch=pixelmatchModule.default||pixelmatchModule;
const {PNG}=require('pngjs');

const ROOT=path.resolve(__dirname,'../..');
const DASH=path.join(ROOT,'dashboard');
const OUT=path.join(__dirname,'visual-baselines');
const update=process.argv.includes('--update');
const only=(process.argv.find(a=>a.startsWith('--case='))||'').split('=')[1];
// Keep deterministic live fixtures inside the active season boundary. These
// ids are updated only when the registered season changes.
const player='367185',game='1983546';

function server(){
  const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.png':'image/png'};
  return http.createServer((req,res)=>{
    const clean=decodeURIComponent((req.url||'/').split('?')[0]).replace(/^\/+/, '')||'index.html';
    const file=path.resolve(DASH,clean);
    if(!file.startsWith(DASH)||!fs.existsSync(file)){res.writeHead(404);return res.end('not found')}
    res.writeHead(200,{'Content-Type':mime[path.extname(file)]||'application/octet-stream'});
    fs.createReadStream(file).pipe(res);
  });
}
function compare(name,actual){
  const expected=path.join(OUT,name),received=path.join(OUT,name.replace('.png','.received.png'));
  if(update||!fs.existsSync(expected)){fs.writeFileSync(expected,actual);console.log(`UPDATED ${name}`);return}
  const a=PNG.sync.read(actual),e=PNG.sync.read(fs.readFileSync(expected));
  if(a.width!==e.width||a.height!==e.height){fs.writeFileSync(received,actual);throw new Error(`${name}: dimensions ${a.width}x${a.height}, expected ${e.width}x${e.height}`)}
  const diff=new PNG({width:a.width,height:a.height});
  const changed=pixelmatch(e.data,a.data,diff.data,a.width,a.height,{threshold:.12,includeAA:false});
  const ratio=changed/(a.width*a.height);
  if(ratio>.002){fs.writeFileSync(received,actual);fs.writeFileSync(path.join(OUT,name.replace('.png','.diff.png')),PNG.sync.write(diff));throw new Error(`${name}: ${(ratio*100).toFixed(3)}% pixels differ`)}
  for(const suffix of ['.received.png','.diff.png']){const f=path.join(OUT,name.replace('.png',suffix));if(fs.existsSync(f))fs.unlinkSync(f)}
  console.log(`PASS    ${name} (${(ratio*100).toFixed(3)}%)`);
}
async function snap(page,name,selector,viewportOnly){
  await page.waitForTimeout(350);
  const buf=selector?await page.locator(selector).first().screenshot({animations:'disabled'}):await page.screenshot({fullPage:!viewportOnly,animations:'disabled'});
  compare(name,buf);
}
async function exportBaseline(page,name,trigger,isPdf){
  await page.evaluate(pdf=>{
    window.__visualExport=null;
    if(pdf&&window.jspdf&&window.jspdf.jsPDF){
      window.jspdf.jsPDF.API.save=function(){window.__visualExport=this.output('datauristring')};
    }else{
      HTMLAnchorElement.prototype.click=function(){window.__visualExport=this.href};
    }
  },isPdf);
  await trigger();
  await page.waitForFunction(()=>window.__visualExport,{timeout:90000});
  const uri=await page.evaluate(()=>window.__visualExport);
  const bytes=Buffer.from(uri.slice(uri.indexOf(',')+1),'base64');
  const tmp=path.join(os.tmpdir(),`visual-${process.pid}-${name}${isPdf?'.pdf':'.png'}`);
  fs.writeFileSync(tmp,bytes);
  if(!isPdf){compare(`${name}.png`,bytes);fs.unlinkSync(tmp);return}
  const out=tmp.replace(/\.pdf$/,''),pdftoppm=process.env.PDFTOPPM||
    'C:\\Users\\jbuck\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\native\\poppler\\Library\\bin\\pdftoppm.exe';
  execFileSync(pdftoppm,['-png','-f','1','-singlefile','-r','96',tmp,out],{stdio:'ignore'});
  compare(`${name}-pdf.png`,fs.readFileSync(out+'.png'));
  fs.unlinkSync(tmp);fs.unlinkSync(out+'.png');
}
async function main(){
  fs.mkdirSync(OUT,{recursive:true});
  const externalBase=(process.env.VISUAL_BASE_URL||'').replace(/\/$/,'');
  const s=externalBase?null:server();
  if(s)await new Promise(ok=>s.listen(0,'127.0.0.1',ok));
  const base=externalBase||`http://127.0.0.1:${s.address().port}`;
  const browser=await chromium.launch({headless:true,
    executablePath:process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'});
  try{
    const cases=[
      {name:'player-desktop-dark',url:`players.html?player=${player}`,size:{width:1440,height:950},ready:'.fs-identity-name',act:()=>`setGrp('Defending')`,sel:'#main'},
      {name:'player-mobile-dark',url:`players.html?player=${player}`,size:{width:390,height:844},ready:'.fs-identity-name',act:()=>`setGrp('Tempo')`,sel:'#main'},
      {name:'team-tablet-light',url:'teams.html?team=Arsenal',size:{width:900,height:1050},theme:'light',ready:'.fs-identity-name',act:()=>`setTab('Maps')`,sel:'#main'},
      {name:'team-desktop-monochrome',url:'teams.html?team=Arsenal',size:{width:1440,height:950},ready:'.fs-identity-name',act:()=>`setTab('Maps')`,mono:true,sel:'#main'},
      {name:'match-desktop-dark',url:`match.html?game=${game}`,size:{width:1440,height:950},ready:'.pitch-canvas',sel:'#pitchArea'},
      {name:'match-mobile-light',url:`match.html?game=${game}`,size:{width:390,height:844},theme:'light',ready:'.pitch-canvas',sel:'#pitchArea'},
      {name:'insights-desktop-light',url:'insights.html',size:{width:1280,height:900},theme:'light',ready:'.card',css:'#content .sec:first-child .card:nth-child(n+7){display:none}',sel:'#content .sec'},
      {name:'sequences-desktop-dark',url:'sequences.html',size:{width:1280,height:900},ready:'.scard',sel:'#main'},
      {name:'player-compare-desktop',url:`players.html?player=${player}`,size:{width:1280,height:900},ready:'.fs-identity-name',act:()=>`setTab('Compare')`,after:'.cmp-card',sel:'#main'},
      {name:'team-rankings-mobile',url:'teams.html?team=Arsenal',size:{width:390,height:844},ready:'.fs-identity-name',act:()=>`setTab('Rankings')`,after:'#main table',sel:'#main'},
      {name:'validation-desktop-light',url:'validation.html',size:{width:1280,height:900},theme:'light',ready:'#msStatus',viewport:true},
      {name:'methodology-desktop-dark',url:'methodology.html',size:{width:1280,height:900},ready:'#mGoals',viewport:true}
    ];
    for(const c of cases.filter(c=>!only||c.name.includes(only))){
      const page=await browser.newPage({viewport:c.size,deviceScaleFactor:1});
      page.on('pageerror',e=>console.error(`PAGE ${c.name}: ${e.message}`));
      page.on('response',async r=>{
        if(r.status()>=400){
          let body='';try{body=(await r.text()).slice(0,500)}catch{}
          console.error(`HTTP ${c.name}: ${r.status()} ${r.url()} ${body}`);
        }
      });
      await page.addInitScript(t=>{localStorage.setItem('theme',t);localStorage.setItem('siteAccess','granted-v1')},c.theme||'dark');
      await page.goto(`${base}/${c.url}`,{waitUntil:'domcontentloaded'});
      try{
        await page.locator(c.ready).first().waitFor({state:'visible',timeout:45000});
      }catch(error){
        console.error(`READY ${c.name}: ${(await page.locator('body').innerText()).slice(0,1200)}`);
        throw error;
      }
      if(c.act){await page.evaluate(c.act());await page.locator(c.after||'.pitch-box').first().waitFor({state:'visible',timeout:20000})}
      if(c.css)await page.addStyleTag({content:c.css});
      if(c.mono)await page.addStyleTag({content:'html{filter:grayscale(1)!important}'});
      await snap(page,`${c.name}.png`,c.sel,c.viewport);
      await page.close();
    }
    if(!only||only==='exports'){
      const page=await browser.newPage({viewport:{width:1440,height:950},acceptDownloads:true});
      page.on('dialog',async d=>{console.error(`EXPORT DIALOG: ${d.message()}`);await d.dismiss()});
      page.on('pageerror',e=>console.error(`EXPORT PAGE: ${e.message}`));
      await page.addInitScript(()=>{localStorage.setItem('theme','dark');localStorage.setItem('siteAccess','granted-v1')});
      await page.goto(`${base}/players.html?player=${player}`,{waitUntil:'domcontentloaded'});
      await page.locator('.fs-identity-name').waitFor({timeout:45000});await page.evaluate(()=>setGrp('Defending'));
      await page.locator('.pitch-box').waitFor();
      await exportBaseline(page,'player-export-png',()=>page.locator('.viz-exp button').nth(0).click(),false);
      await exportBaseline(page,'player-export',()=>page.locator('.viz-exp button').nth(1).click(),true);
      await page.goto(`${base}/teams.html?team=Arsenal`,{waitUntil:'domcontentloaded'});
      await page.locator('.fs-identity-name').waitFor({timeout:45000});await page.evaluate(()=>setTab('Maps'));await page.locator('.fs-pitchbox').waitFor();
      await exportBaseline(page,'team-export-png',()=>page.evaluate(()=>exportPNG()),false);
      await exportBaseline(page,'team-export',()=>page.evaluate(()=>exportPDF()),true);
      await page.goto(`${base}/match.html?game=${game}`,{waitUntil:'domcontentloaded'});
      await page.locator('.pitch-canvas').first().waitFor({timeout:45000});
      await exportBaseline(page,'match-export-png',()=>page.evaluate(()=>downloadPNG(document.querySelector('.pitch-canvas'),'Progressive passing')),false);
      await exportBaseline(page,'match-export',()=>page.evaluate(()=>downloadPDF(document.querySelector('.pitch-canvas'),'Progressive passing')),true);
      await page.close();
    }
  } finally {
    await browser.close();
    if(s)await new Promise(ok=>s.close(ok));
  }
}
main().catch(e=>{console.error(e.stack||e);process.exit(1)});
