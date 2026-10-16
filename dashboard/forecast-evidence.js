/* Shared read-only explanation ledger. Legacy snapshots are never reconstructed. */
(() => {
  const esc = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => value == null ? 'missing' : Number(value).toLocaleString(undefined,{maximumSignificantDigits:8});
  window.forecastEvidence = explanation => {
    const rows = explanation?.feature_ledger;
    if (!rows?.length) return '<p class="copy scope">Full transformed-feature ledger was not captured in this legacy snapshot. The summary inputs below are contextual, not the complete set of fitted windows. Historical values have not been reconstructed from current data.</p>';
    return '<details class="feature-ledger"><summary>Inspect exact fitted inputs and rolling windows ('+rows.length+')</summary><p>Each row shows one grouped numeric model input. A suffix of 3, 5 or 10 means a trailing-match window—not days. Raw is the saved input; model input includes preprocessing before scaling. Missing values may be imputed. These are log goal-rate contributions, not goals or probability points. Intercept and categorical league effects are not included in this grouped ledger.</p><div style="overflow:auto"><table><thead><tr><th>Feature / window</th><th>Raw</th><th>Model input</th><th>Home scaled × coefficient</th><th>Away scaled × coefficient</th><th>Home − away</th></tr></thead><tbody>'+rows.map(r=>'<tr><td>'+esc(r.feature)+'</td><td>'+number(r.raw_value)+'</td><td>'+number(r.model_input)+'</td><td>'+number(r.home_transformed)+' × '+number(r.home_coefficient)+'</td><td>'+number(r.away_transformed)+' × '+number(r.away_coefficient)+'</td><td>'+number(r.log_rate_balance_contribution)+'</td></tr>').join('')+'</tbody></table></div></details>';
  };
})();
