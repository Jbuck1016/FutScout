const fs=require('fs'),assert=require('assert'),vm=require('vm'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../../dashboard/players.html'),'utf8');
const helper=source.match(/function metricRateSuffix\(d\)\{[^\n]+\}/)[0];
const context={};vm.createContext(context);vm.runInContext(helper,context);
for(const key of ['pass_cmp_90','territory_90'])assert.equal(context.metricRateSuffix({key}),' per 90');
for(const key of ['pass_pct','median_ttr','xg_per_shot','chain_share'])assert.equal(context.metricRateSuffix({key}),'');
assert(!source.includes("+' per 90 · '+esc(d.grp)"));
console.log('PASS: rate metrics retain /90; percentages, durations and per-shot ratios do not');
