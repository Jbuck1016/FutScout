// Local browser only; every external URL is blocked or fulfilled with synthetic data.
const {chromium}=require(process.env.PLAYWRIGHT_PATH||'C:/Users/jbuck/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('assert/strict'),fs=require('fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:900}});
 await context.route('**/*',r=>{const u=new URL(r.request().url());if(u.hostname==='127.0.0.1')return r.continue();if(u.pathname.includes('/rest/v1/'))return r.fulfill({json:[]});return r.abort()});
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto((process.env.AUDIT_ORIGIN||'http://127.0.0.1:8765')+'/players.html');await page.waitForTimeout(200);
 const player=await page.evaluate(async()=>{
   PLAYERS=Array.from({length:331},(_,i)=>({player_id:String(i+1),player_name:'Synthetic player '+(i+1),team:'Test FC',pool:'W',nineties:5,minutes:450,apps:5,starts:5}));PLGSCOPE='ALL';PLG['Test FC']='TEST';PLEAGUES=[{league:'TEST',display_name:'Test league'}];WEIGHTS={W:{}};DEFS=[{key:'prog_carries_90',label:'Carries',unit:'per 90',grp:'Carrying'},{key:'key_pass_90',label:'Key passes',unit:'per 90',grp:'Creation'}];fillTeamSel();renderList();const count=document.querySelectorAll('#plist .pitem').length;
   let resolve;sbAll=()=>new Promise(r=>resolve=r);TAB='Scatter';const slow=renderScatter();setTab('Player');resolve([]);await slow;const race=document.getElementById('main').textContent.includes('Find the player');
   PACT=[0,null,.3].map(xg=>({xg,is_shot:true,is_open_play:true,x:90,y:50,shot_outcome:'off'}));PCAR=[];PREC=[];EVF={game:'',score:'',phase:'',min:'',max:''};const shots=vizLayers('Shooting',PLAYERS[0]);
   sbAll=async()=>[];await pick('1');const first=new URL(location.href).searchParams.get('player');await pick('2');const second=new URL(location.href).searchParams.get('player');
   return {count,race,shots:shots.sub,first,second};
 });
 assert.equal(player.count,331);assert.equal(player.race,true);assert.match(player.shots,/0.30 known xG \(2\/3 available\)/);assert.equal(player.first,'1');assert.equal(player.second,'2');
 await page.goBack();await page.waitForTimeout(100);assert.equal(await page.evaluate(()=>String(SEL)),'1');
 const raceMatrix=await page.evaluate(async()=>{
   const result={};for(const name of ['renderRank','renderScatter','renderScout','renderCompare','loadStudioPlayer']){
     let done=[];sbAll=()=>new Promise(r=>done.push(r));loadEvidenceLayers=()=>new Promise(r=>done.push(()=>r({actions:[],carries:[],receipts:[],contextReady:true})));
     TAB={renderRank:'Rank',renderScatter:'Scatter',renderScout:'Scout',renderCompare:'Compare',loadStudioPlayer:'Plot studio'}[name];PILLAR=null;CMP={a:'1',b:'2',pool:'W'};
     const pending=name==='loadStudioPlayer'?window[name]('1'):window[name]();viewGeneration++;TAB='Player';document.getElementById('main').innerHTML='<h1>Latest view</h1>';done.forEach(r=>r([]));await pending;result[name]=document.getElementById('main').textContent==='Latest view';
   }
   return result;
 });assert.ok(Object.values(raceMatrix).every(Boolean));
 await page.evaluate(()=>{sbAll=async()=>[];loadEvidenceLayers=async()=>({actions:[],carries:[],receipts:[],contextReady:true});SEL='1';TAB='Player';PACT=[{xg:0,is_shot:true,is_open_play:true,x:90,y:50}];PCAR=[];PREC=[];PMCACHE={};EVIDENCE_PID='1';drill('shots_90')});
 await page.waitForTimeout(50);const focusTrap=await page.evaluate(()=>{const items=Array.from(document.querySelectorAll('#drillWrap button,#drillWrap select,#drillWrap input')).filter(x=>x.getClientRects().length&&!x.disabled);items[items.length-1].focus();return items[0].className});await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.className),focusTrap);assert.equal(await page.locator('#main').evaluate(el=>el.closest('.wrap').inert),true);await page.keyboard.press('Escape');await page.waitForTimeout(30);assert.equal(await page.locator('#drillWrap').isVisible(),false);
 const responsive=[];for(const theme of ['light','dark'])for(const width of [320,375,390,640,768,1024,1440,1920]){await page.setViewportSize({width,height:900});await page.evaluate(t=>{document.documentElement.classList.toggle('dark',t==='dark');setTab('Player')},theme);await page.waitForTimeout(20);responsive.push({theme,width,overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),offenders:await page.evaluate(()=>Array.from(document.querySelectorAll('*')).filter(el=>el.scrollWidth>el.clientWidth+2).slice(0,12).map(el=>[el.tagName,el.className,el.scrollWidth,el.clientWidth]))});if([390,1440].includes(width))await page.screenshot({path:'artifacts/ux-audit/player-synthetic-'+theme+'-'+width+'.png'})}
 await page.goto((process.env.AUDIT_ORIGIN||'http://127.0.0.1:8765')+'/search.html');await page.waitForTimeout(100);
 const search=await page.evaluate(async()=>{ROWS=Array.from({length:70},(_,i)=>({player_id:i+1,player:'Synthetic '+i,team:'Test',league:'TEST',pool:'W',pos:'W',nineties:5,xt_90:i}));PCT=buildPct(ROWS);apply();const links=document.querySelectorAll('#results a[href*="player="]').length;let resolve;sbRpc=()=>new Promise(r=>resolve=r);document.getElementById('askInput').value='test';const pending=runAsk();clearAsk();resolve({results:[]});await pending;return {links,cleared:document.getElementById('askOut').innerHTML===''}});
 assert.equal(search.links,70);assert.equal(search.cleared,true);
 await page.setViewportSize({width:390,height:900});await page.screenshot({path:'artifacts/ux-audit/search-synthetic-mobile.png'});
 await page.goto((process.env.AUDIT_ORIGIN||'http://127.0.0.1:8765')+'/sequences.html');await page.waitForTimeout(100);
 const sequence=await page.evaluate(async()=>{let resolve;sbRpc=()=>new Promise(r=>resolve=r);MODE='type';const old=loadCandidates();sequenceGeneration++;CANDS=[{seq_uid:'new',team:'New',path:[],xt_sum:0}];renderBrowse();resolve([{seq_uid:'old'}]);await old;return {kept:CANDS[0].seq_uid,trace:actionTrace({team:'Test',path:[{t:'Pass',x:1,y:2,ex:3,ey:4},{t:'Touch',x:3,y:4}]})}});
 assert.equal(sequence.kept,'new');assert.match(sequence.trace,/end coordinate unavailable/);
 assert.deepEqual(errors,[]);
 fs.writeFileSync('artifacts/ux-audit/player-research-tests.json',JSON.stringify({player,raceMatrix,responsive,search,sequenceRace:sequence.kept,errors},null,2));console.log(JSON.stringify({player,raceMatrix,responsive,search,sequenceRace:sequence.kept,errors},null,2));await browser.close();
})().catch(e=>{console.error(e);process.exitCode=1});
