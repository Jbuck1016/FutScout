const fs=require('fs'),vm=require('vm'),assert=require('assert');
const context={window:{}};vm.createContext(context);vm.runInContext(fs.readFileSync('dashboard/forecast-evidence.js','utf8'),context);
assert(context.window.forecastEvidence({}).includes('legacy snapshot'));
const result=context.window.forecastEvidence({feature_ledger:[{feature:'team.shots_10<script>',raw_value:4,model_input:4,home_transformed:1,away_transformed:2,home_coefficient:.2,away_coefficient:.1,log_rate_balance_contribution:0}]});
assert(result.includes('team.shots_10&lt;script&gt;')&&!result.includes('<script>'));
assert(result.includes('trailing-match window')&&result.includes('log goal-rate'));
console.log('PASS: exact feature ledger, escaping, units and explicit legacy fallback');
