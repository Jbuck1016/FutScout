(() => {
'use strict';
const data=window.MATCH_REVIEW, root=document.getElementById('review');
const requested=new URLSearchParams(location.search).get('game');
if(!data || (requested && requested!==data.match.game_id)){root.textContent='No verified review bundle is available for this fixture. Return to Model Lab to inspect the saved forecasts.';return;}
const m=data.match, $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=n=>(n*100).toFixed(1)+'%', num=(n,d=2)=>Number(n).toFixed(d);
try{document.documentElement.classList.toggle('dark',localStorage.getItem('theme')==='dark');}catch(e){}
$('theme').onclick=()=>{const dark=document.documentElement.classList.toggle('dark');try{localStorage.setItem('theme',dark?'dark':'light');}catch(e){}};
$('pdf').onclick=()=>window.print();
function ribbon(p){return `<div class="labels"><span class="home">Brighton</span><span>Draw</span><span class="away">Arsenal</span></div><div class="ribbon" role="img" aria-label="Brighton ${pct(p.H)}, draw ${pct(p.D)}, Arsenal ${pct(p.A)}"><span class="h" style="width:${p.H*100}%">${pct(p.H)}</span><span style="width:${p.D*100}%">${pct(p.D)}</span><span class="a" style="width:${p.A*100}%">${pct(p.A)}</span></div>`;}
$('probabilities').innerHTML=ribbon(m.probabilities);
$('scores').innerHTML=`<div><b>${num(m.home_expected_goals)}–${num(m.away_expected_goals)}</b><small>Pre-match expected goals</small></div><div><b>${num(m.log_loss,3)}</b><small>Realised log loss</small></div><div><b>${num(m.brier,3)}</b><small>Multiclass Brier</small></div>`;
$('drivers').innerHTML=m.forecast_drivers.map(d=>`<div class="driver"><b>${esc(d.label)}<span class="signed ${d.goal_balance_effect>=0?'home':'away'}">${d.goal_balance_effect>=0?'+':''}${num(d.goal_balance_effect,3)}</span></b><p>${esc(d.detail)}</p></div>`).join('');
const sums=team=>data.shots.filter(s=>s.team===team).reduce((v,s)=>v+Number(s.xg),0);
const metrics=[['Shots',17,11,0,'All recorded attempts'],['Fitted xG · shot feed',sums('Brighton'),sums('Arsenal'),2,'28 / 28 attempts have estimates'],['Field tilt',m.tactical.home.field_tilt_pct,m.tactical.away.field_tilt_pct,1,'Percent · archived team observation'],['Completed box entries',14,20,0,'Completed passes · not all attempted entries']];
$('metrics').innerHTML='<div class="labels"><span class="home">Brighton</span><span class="away">Arsenal</span></div>'+metrics.map(([label,h,a,d,desc])=>`<div class="row"><div class="rowheader"><strong>${num(h,d)}</strong><span>${label}</span><strong>${num(a,d)}</strong></div><div class="bars" aria-hidden="true"><i style="width:${100*h/(h+a)}%"></i><i style="width:${100*a/(h+a)}%"></i></div><p class="caption">${desc}. Bar shows share of the two-team total.</p></div>`).join('');
const svg=(width,height,title,body)=>`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(title)}"><title>${esc(title)}</title><rect width="100%" height="100%" fill="var(--paper)"/>${body}<text x="20" y="${height-12}" font-size="12">FutScout · Brighton 3–0 Arsenal · 19 Sep 2026 · event feed retrieved ${esc(data.events_retrieved_on)}</text></svg>`;
const markTitle=s=>`${s.team}: ${s.player}, ${s.minute}:${String(s.second).padStart(2,'0')}, fitted xG ${num(s.xg,4)}, ${s.is_goal?'goal':'not a goal'}`;
let map='';
for(const [i,team] of ['Brighton','Arsenal'].entries()){
 const ox=25+i*540,oy=62,w=500,h=w*68/105,color=i?'var(--away)':'var(--home)';
 map+=`<text x="${ox}" y="30" font-size="22" font-weight="700">${team} · ${data.shots.filter(s=>s.team===team).length} shots · ${num(sums(team))} xG</text><g transform="translate(${ox},${oy})" fill="none" stroke="var(--line)" stroke-width="1.5"><rect width="${w}" height="${h}"/><path d="M250 0V${h}"/><circle cx="250" cy="${h/2}" r="43.57"/><rect x="421.43" y="65.81" width="78.57" height="192"/><rect x="473.81" y="118.43" width="26.19" height="87.24"/><rect x="0" y="65.81" width="78.57" height="192"/><rect x="0" y="118.43" width="26.19" height="87.24"/></g>`;
 for(const s of data.shots.filter(s=>s.team===team)){map+=`<circle tabindex="0" aria-label="${esc(markTitle(s))}" cx="${ox+s.x*w/100}" cy="${oy+(100-s.y)*h/100}" r="${Math.sqrt(Number(s.xg))*22}" fill="${s.is_goal?color:'var(--paper)'}" stroke="${color}" stroke-width="2"><title>${esc(markTitle(s))}</title></circle>`;}
 map+=`<text x="${ox+w/2}" y="415" text-anchor="middle" font-size="14">Attack direction →</text>`;
}
map+='<text x="25" y="447" font-size="14">Circle area = fitted xG · filled = goal · hollow = other attempt · both teams attack right</text>';
$('shotmaps').innerHTML=svg(1090,488,'Shot maps: Brighton 17 attempts, Arsenal 11. Both teams attack right.',map);
const elapsedShots=data.shots.map((s,i)=>({...s,elapsed:(data.score_states?.shot_elapsed_seconds[i] ?? (s.minute*60+s.second))/60})).sort((a,b)=>a.elapsed-b.elapsed);
const duration=(data.score_states?.duration_seconds ?? 5760)/60;
let timeline='';const x=t=>55+t/duration*960,y=v=>280-v/2*210;
for(let value=0;value<=2;value+=.5)timeline+=`<path d="M55 ${y(value)}H1015" stroke="var(--line)"/><text x="40" y="${y(value)+5}" text-anchor="end" font-size="14">${value}</text>`;
for(const minute of [0,15,30,45,60,75,90])timeline+=`<text x="${x(minute)}" y="305" text-anchor="middle" font-size="14">${minute}′</text>`;
timeline+='<text x="535" y="328" text-anchor="middle" font-size="13">Elapsed match minutes · added time included · halftime excluded</text>';
timeline+='<text x="55" y="25" font-size="18" font-weight="700">Cumulative fitted xG</text><text x="690" y="25" font-size="16" style="fill:var(--home)">Brighton —</text><text x="865" y="25" font-size="16" style="fill:var(--away)">Arsenal - -</text>';
for(const [i,team] of ['Brighton','Arsenal'].entries()){
let total=0,d=`M${x(0)} ${y(0)}`,goals='';
for(const s of elapsedShots.filter(s=>s.team===team)){const t=s.elapsed;d+=`H${x(t)}V${y(total+=Number(s.xg))}`;if(s.is_goal)goals+=`<circle cx="${x(t)}" cy="${y(total)}" r="6" fill="var(--${i?'away':'home'})"><title>${esc(markTitle(s))}</title></circle><text x="${x(t)}" y="${y(total)-14}" text-anchor="middle" font-size="14">Goal ${s.minute+1}′</text>`;}
d+=`H${x(duration)}`;timeline+=`<path d="${d}" fill="none" stroke="var(--${i?'away':'home'})" stroke-width="3" ${i?'stroke-dasharray="8 5"':''}/>${goals}`;
}
$('timeline').innerHTML=svg(1060,360,'Cumulative fitted xG and goal timing. Brighton scored in minutes 31, 45 and 57.',timeline);
$('shots').innerHTML=data.shots.map(s=>`<tr><td>${esc(s.team)}</td><td>${esc(s.player)}</td><td>${s.minute}:${String(s.second).padStart(2,'0')}</td><td>${num(s.xg,4)}</td><td>${s.is_goal?'Goal':'Other attempt'}</td></tr>`).join('');
const c=data.challenger;$('challenger').innerHTML=ribbon({H:c.home_win_probability,D:c.draw_probability,A:c.away_win_probability})+`<p class="caption">${esc(data.challenger_model)} · comparison as of ${esc(data.challenger_scope.as_of)}</p>`;
$('provenance').innerHTML=`<strong>Provenance</strong><p>Frozen forecast: ${esc(data.provenance.as_of)}. Saved report generated: ${esc(data.provenance.generated_at)}. Model: ${esc(data.provenance.model_version)}. Match key: ${esc(m.game_id)}. Shot source: ${esc(data.event_source)}.</p><p>Report SHA-256: ${esc(data.report_sha256)}</p><p>Visual reference: <a href="https://johnspacemuller.substack.com/p/premier-league-match-dashboards">John Muller’s Athletic match dashboards</a>. Independent FutScout implementation; no affiliation. Current scope: one worked review, not an automatically generated verdict.</p>`;
document.querySelectorAll('[data-export]').forEach(button=>button.onclick=async()=>{
 const node=$(button.dataset.export).querySelector('svg').cloneNode(true),styles=getComputedStyle(document.documentElement);
 for(const el of [node,...node.querySelectorAll('*')]){for(const attr of ['fill','stroke','style']){const v=el.getAttribute(attr);if(v)el.setAttribute(attr,v.replace(/var\((--[\w-]+)\)/g,(_,key)=>styles.getPropertyValue(key).trim()));}if(el.tagName==='text')el.setAttribute('fill',el.getAttribute('style')?.includes('fill:')?el.getAttribute('style').split('fill:')[1]:styles.getPropertyValue('--ink').trim());}
 const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(node)],{type:'image/svg+xml'}));
 try{const img=new Image();img.src=url;await img.decode();const box=node.viewBox.baseVal,canvas=document.createElement('canvas');canvas.width=box.width*2;canvas.height=box.height*2;canvas.getContext('2d').drawImage(img,0,0,canvas.width,canvas.height);const a=document.createElement('a');a.download=`brighton-arsenal-${button.dataset.export}.png`;a.href=canvas.toDataURL('image/png');a.click();}catch(e){button.textContent='Export failed — retry';}finally{URL.revokeObjectURL(url);}
});
})();
