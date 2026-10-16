// Focused, network-free state checks for Match Analysis deep links and filters.
// Browser layout verification complements these assertions; CSS cannot be
// accurately laid out by a Node VM.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const page = fs.readFileSync(path.resolve(__dirname, '../../dashboard/match.html'), 'utf8');
const scripts = [...page.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
const source = scripts.at(-1)[1].replace(/\binit\(\);\s*$/, '');
const select = {value: '', options: [], set innerHTML(_value) {this.options = []; this.value = '';}, appendChild(option) {this.options.push(option);}};
const count = {textContent: ''};
let checked = [{value: 'ENG-Premier League'}];
const context = {
  console,
  URLSearchParams,
  location: {search: '?game=fixture-42'},
  window: {innerHeight: 720, matchMedia: () => ({matches: false})},
  document: {
    querySelectorAll: () => checked,
    getElementById: id => ({matchSel: select, matchCount: count})[id] || null,
    createElement: () => ({value: '', textContent: ''}),
  },
};
vm.createContext(context);
vm.runInContext(source, context, {filename: 'match.html'});

const read = expression => vm.runInContext(expression, context);
read("LEAGUES=[{v:'ENG-Premier League',l:'Premier League',n:50},{v:'USA-MLS',l:'MLS',n:100}]; SELCOMPS=new Set(['ENG-Premier League']); LEAGUE_OF={Brighton:'ENG-Premier League'}; TEAMS={Brighton:{name:'Brighton',comps:LEAGUES},__ALL__:{name:'__ALL__',comps:LEAGUES}};");
assert.equal(read("inComps('__ALL__')"), true, 'All teams must remain selectable for a league filter');
assert.equal(read("inComps('Brighton')"), true);

read("S.matches=[{game_id:'fixture-42',date:'2026-09-30',home_team:'Brighton',away_team:'Arsenal',home_score:3,away_score:0,competition:'ENG-Premier League'},{game_id:'fixture-99',date:'2026-09-30',home_team:'LAFC',away_team:'Galaxy',home_score:1,away_score:0,competition:'USA-MLS'}];");
read('renderMatchSelectFiltered()');
assert.equal(count.textContent, '1 played matches');
assert.equal(select.options.length, 1);
select.value = 'fixture-42';
read('renderMatchSelectFiltered()');
assert.equal(select.value, 'fixture-42', 'Rebuilding options must preserve the selected fixture');
read("S.viewTeam='Brighton'; S.events=[{team:'Brighton',type:'Pass',outcome_type:'Successful',is_open_play:true,x:40,y:50,end_x:80,end_y:50},{team:'Brighton',type:'Pass',outcome_type:'Unsuccessful',is_open_play:true,x:40,y:50,end_x:80,end_y:50},{team:'Brighton',type:'Pass',outcome_type:'Successful',is_open_play:false,x:40,y:50,end_x:80,end_y:50}];");
assert.equal(read("getFiltered('xt').length"), 1, 'xT map must not credit failed or set-piece passes');
assert.ok(read('getXT(80,50)>getXT(40,50)'), 'positive progression should increase grid threat');
read("S.carries=[{team:'Brighton',start_x:40,start_y:50,end_x:80,end_y:50,period:1,minute:12},{team:'Arsenal',start_x:40,start_y:50,end_x:80,end_y:50,period:1,minute:13}];");
assert.equal(read("getFiltered('xt_carry').length"), 1, 'carry threat needs its own team-scoped event feed');

// Stub network and render routines while exercising the actual deep-link state
// transition. A Premier League fixture must override the default MLS scope.
read("SELCOMPS=new Set(['USA-MLS']); S.team='__ALL__'; MATCH2EV={Brighton:'Brighton'};");
context.sbAll = async () => [{game_id:'fixture-42',date:'2026-09-30',home_team:'Brighton',away_team:'Arsenal',home_score:3,away_score:0,competition:'ENG-Premier League',season:'2627'}];
context.applyTheme = () => {};
context.initTeamSwitcher = () => {};
context.initCompFilters = () => {};
context.loadMatches = async () => {};
context.loadMatch = async gameId => {context.loadedGame = gameId;};
context.loadSeasonStats = () => {};
read('openDeepLink()').then(() => {
  assert.deepEqual([...read('SELCOMPS')], ['ENG-Premier League']);
  assert.equal(read('S.team'), 'Brighton');
  assert.equal(select.value, 'fixture-42');
  assert.equal(context.loadedGame, 'fixture-42');
  assert.match(page, /\.pitch-area\{flex:0 0 auto;[^}]*min-height:540px/, 'Pitch area needs an explicit visible height');
  assert.match(page, /\.content\{[^}]*overflow-y:auto/, 'Match content must scroll instead of clipping plots');
  assert.match(page, /v_player_carries/, 'Pass/carry xT view needs real inferred carry records');
  console.log('PASS Match Analysis deep-link, all-team filter, fixture preservation, and pitch layout contracts');
}).catch(error => {console.error(error); process.exitCode = 1;});
