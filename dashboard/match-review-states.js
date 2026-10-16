(() => {
  'use strict';
  const data = window.MATCH_REVIEW?.score_states;
  if (!data || !document.getElementById('timeline')) return;
  const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const section = document.createElement('section');
  section.className = 'panel';
  section.setAttribute('data-export-card', '');
  section.innerHTML = `<div class="kicker">Retrospective / Score-state review</div><h2>What changed after the lead?</h2>
    <p>Compare chances over the same stretch of the game. The state is relative to ${esc(data.teams[0])}; when they lead, ${esc(data.teams[1])} trail. This describes the match, not why the result happened.</p>
    <div style="display:flex;flex-wrap:wrap;gap:16px"><label>Time window<br><select id="state-window">${data.windows.map(w => `<option value="${esc(w.id)}">${esc(w.label)}</option>`).join('')}</select></label>
    <label>Score before the event<br><select id="state-filter"><option value="all">All states</option><option value="level">Level</option><option value="home_leading">${esc(data.teams[0])} leading</option><option value="away_leading">${esc(data.teams[1])} leading</option></select></label></div>
    <div id="state-result" aria-live="polite"></div><p class="caption">${esc(data.method)}</p>
    ${data.same_second_goal_warning ? '<p class="notice">Multiple shots share a goal timestamp. Their ordering within that second follows the source archive.</p>' : ''}`;
  document.getElementById('timeline').closest('section').after(section);
  const windowSelect = section.querySelector('#state-window'), stateSelect = section.querySelector('#state-filter');
  function render() {
    const row = data.rows.find(r => r.window === windowSelect.value && r.state === stateSelect.value);
    const time = `${Math.floor(row.seconds / 60)}m ${row.seconds % 60}s`;
    section.querySelector('#state-result').innerHTML = row.seconds === 0 ? '<p class="notice">No clock exposure in this state/window. No rate can be estimated.</p>' :
      `<p><strong>${time}</strong> of shared match-clock exposure${row.seconds < 900 ? ' · short sample: rates are especially noisy' : ''}.</p><div class="tablewrap"><table><thead><tr><th>Team</th><th>Shots</th><th>Fitted xG</th><th>Shots / 90 clock minutes</th></tr></thead><tbody>${row.teams.map((t, i) => `<tr><th>${esc(data.teams[i])}</th><td>${t.shots}</td><td>${t.xg.toFixed(3)}</td><td>${t.shots_per90?.toFixed(1) ?? '—'}</td></tr>`).join('')}</tbody></table></div>`;
  }
  windowSelect.onchange = stateSelect.onchange = render;
  render();
})();
