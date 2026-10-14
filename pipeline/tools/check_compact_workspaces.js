const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const read=f=>fs.readFileSync(path.join(__dirname,'../../dashboard',f),'utf8');
const p=read('players.html'),m=read('match.html'),f=read('model-review.html');
for(const name of ['players.html','match.html','model-review.html','model-lab.html','match-review.html'])for(const s of read(name).matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))new vm.Script(s[1]);
assert(!p.includes('Start here · relative strength'));assert(!p.includes('Review question'));assert(!p.includes('class="profile-brief"'));
assert(!m.includes('Questions to investigate'));assert(!m.includes('renderMatchEvidence('));
assert(f.includes('<details class="review-health"'));assert(!f.includes('<details open class="review-health"'));
assert(!p.includes('<text x="43" y="71.2"'));assert.equal((p.match(/class="attack-direction"/g)||[]).length,2);
const c={PX:x=>x,PY:y=>y,eventSvg:(_a,s)=>s};vm.createContext(c);
vm.runInContext(p.slice(p.indexOf('function line(a,'),p.indexOf('function dot(a,')),c);
const mark=c.line({x:1,y:2,end_x:3,end_y:4},'#0b5f50',.15,.24);
assert.match(mark,/stroke-opacity="0.850"/);assert.match(mark,/stroke-width="0.238"/);
vm.runInContext(p.slice(p.indexOf('function pillarRows('),p.indexOf('async function renderPillarRank(')),c);
const rows=c.pillarRows([{player_id:1,score:0},{player_id:2,score:null},{player_id:3,score:80},{player_id:4,score:99}], [{player_id:1,player_name:'A'},{player_id:2,player_name:'B'},{player_id:3,player_name:'C'}]);
assert.deepEqual(Array.from(rows,r=>r.score),[80,0]);
assert(p.includes('aria-label="Compare '));assert(p.includes('aria-label="Pillar league"'));assert(p.includes('aria-label="Pillar role"'));
assert(read('shell.css').includes('.fs-group.is-active>summary{background:var(--ink);color:var(--bg)}'));
console.log('PASS: compact pages, removed prompts, high-opacity movements, unclipped direction, pillar missing/zero/cohort contracts and nav contrast');

