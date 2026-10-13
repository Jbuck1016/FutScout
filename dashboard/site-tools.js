/* ---------------------------------------------------------------------------
   FutScout shared shell and tools.

   One file renders the shell on all 18 destinations: top bar (wordmark, group
   menus, SCOPE, freshness, GO TO, THEME), workspace row (breadcrumb, the page's
   own local tabs, population line, page actions), stale banner, phone bottom
   bar, the GO TO palette and the toast. It also owns the shared export code.

   Loaded synchronously in <head> so the theme is settled before first paint.
   Nothing here touches the DOM body until mount().

   PAGE CONTRACT
     <script>window.FutScout&&FutScout.mount()</script>   first thing in <body>
     data-fs-slot="tabs"     the page's existing local tab strip (moved, not copied,
                             so ids and listeners survive)
     data-fs-slot="scope"    the page's existing league picker
     data-fs-slot="actions"  page-level actions (PNG, PDF, REPORT ...)
     data-fs-slot="pop"      the population line
     FutScout.registerScope({options,value,onChange})   for pages whose league
                             control is not a <select> the shell can adopt
     FutScout.setFreshness(row)      row = {as_of,is_stale,hours_old}
     FutScout.setPopulation(text)
     FutScout.toast(text)
     FutScout.entitySearch(query)    the Go To search, shared with the palette
   Events on window: fs:theme {detail:{theme,dark}}, fs:narrow.
--------------------------------------------------------------------------- */
(function () {
  'use strict';

  /* The single destination registry. It drives the group menus, the palette
     and the phone bottom bar. */
  var DESTINATIONS = [
    ['Home', [['Home', 'index.html']]],
    ['Analyze', [
      ['Match analysis', 'match.html'],
      ['Possession sequences', 'sequences.html']
    ]],
    ['Scout', [
      ['Player fingerprints', 'players.html'],
      ['Team profiles', 'teams.html'],
      ['Scouting insights', 'insights.html'],
      ['Player search', 'search.html'],
      ['Market values', 'market-values.html']
    ]],
    ['Models', [
      ['Domestic forecasts', 'model-review.html'],
      ['Model laboratory', 'model-lab.html'],
      ['Worked match review', 'match-review.html']
    ]],
    ['Write', [['Writing lab', 'writing-lab.html'], ['Quick ingest', 'quick-ingest.html']]],
    ['Learn', [
      ['Field guide', 'guide.html'],
      ['Metric reference', 'glossary.html'],
      ['Evidence definitions', 'evidence-contracts.html'],
      ['Methodology', 'methodology.html'],
      ['Validation', 'validation.html']
    ]]
  ];

  /* Staleness. v_analytics_as_of already reports is_stale, and that existing
     server-side rule is used whenever the row carries it. This constant is only
     the fallback for a snapshot that arrives without the flag. PROVISIONAL:
     seven days, pending a decision from the backend owner. */
  var STALE_FALLBACK_HOURS = 7 * 24;

  var SB = 'https://xrsilhiffjoulyoqhdmp.supabase.co';
  var AK = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhyc2lsaGlmZmpvdWx5b3FoZG1wIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQ2Nzc5NDAsImV4cCI6MjEwMDI1Mzk0MH0.3_ccOJi0SBKOwHGxhJL3fsWCSSLoxZumzt-KH4wO8OU';
  var HD = {apikey: AK, Authorization: 'Bearer ' + AK};

  var root = document.documentElement;
  var mounted = false, adopted = false;
  var els = {};
  var freshness = null, freshnessFromPage = false, scopeReg = null;

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (char) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char];
    });
  }
  function store(kind, key, value) {
    try {
      var s = kind === 'session' ? sessionStorage : localStorage;
      if (arguments.length === 2) return s.getItem(key);
      if (value == null) s.removeItem(key); else s.setItem(key, value);
    } catch (e) {}
    return null;
  }
  function currentFile() {
    var name = location.pathname.split('/').pop();
    return name || 'index.html';
  }
  function currentGroup() {
    var file = currentFile(), found = null;
    DESTINATIONS.forEach(function (group) {
      group[1].forEach(function (item) { if (item[1] === file) found = {group: group[0], name: item[0]}; });
    });
    return found || {group: '', name: document.title || 'FutScout'};
  }

  /* ---------- Theme: one global control ---------- */
  function storedTheme() {
    var t = null;
    try { t = new URLSearchParams(location.search).get('theme'); } catch (e) {}
    if (t !== 'dark' && t !== 'light') t = store('local', 'theme');
    return t === 'dark' || t === 'light' ? t : null;
  }
  function isDark() {
    var t = root.getAttribute('data-theme');
    if (t) return t === 'dark';
    return !!(window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);
  }
  function applyTheme(theme, announce) {
    if (theme) root.setAttribute('data-theme', theme); else root.removeAttribute('data-theme');
    /* Page scripts that draw to canvas still ask html.dark which palette to
       use, so the class follows the attribute. It selects nothing in CSS. */
    root.classList.toggle('dark', isDark());
    if (els.theme) els.theme.setAttribute('aria-pressed', String(isDark()));
    if (announce) window.dispatchEvent(new CustomEvent('fs:theme', {detail: {theme: theme, dark: isDark()}}));
  }
  function toggleTheme() {
    var next = isDark() ? 'light' : 'dark';
    store('local', 'theme', next);
    applyTheme(next, true);
  }
  applyTheme(storedTheme(), false);
  if (window.matchMedia) {
    var mq = matchMedia('(prefers-color-scheme: dark)');
    var onScheme = function () { if (!root.getAttribute('data-theme')) applyTheme(null, true); };
    if (mq.addEventListener) mq.addEventListener('change', onScheme); else if (mq.addListener) mq.addListener(onScheme);
  }

  /* Print is always light, like every other export. */
  var printRestore;
  window.addEventListener('beforeprint', function () {
    if (printRestore !== undefined) return;
    printRestore = root.getAttribute('data-theme');
    root.setAttribute('data-theme', 'light'); root.classList.remove('dark');
  });
  window.addEventListener('afterprint', function () {
    if (printRestore === undefined) return;
    var t = printRestore; printRestore = undefined;
    applyTheme(t, false);
  });

  /* ---------- Shell markup ---------- */
  function groupMenus() {
    var here = currentGroup(), file = currentFile();
    return DESTINATIONS.map(function (group) {
      var active = group[0] === here.group;
      return '<details class="fs-group' + (active ? ' is-active' : '') + '">' +
        '<summary' + (active ? ' aria-current="true"' : '') + '>' + esc(group[0]) + '</summary>' +
        '<div class="fs-menu" role="group" aria-label="' + esc(group[0]) + ' destinations">' +
        group[1].map(function (item) {
          return '<a href="' + item[1] + '"' + (item[1] === file ? ' aria-current="page"' : '') + '>' + esc(item[0]) + '</a>';
        }).join('') + '</div></details>';
    }).join('');
  }
  function scopeLabel() {
    var v = store('local', 'leagueScope') || 'ALL';
    return v === 'ALL' ? 'All leagues' : v;
  }

  function mount() {
    if (mounted || !document.body) return;
    mounted = true;
    var here = currentGroup();
    var mac = /mac/i.test(navigator.platform || '');
    var shell = document.createElement('header');
    shell.className = 'fs-shell';
    shell.setAttribute('data-fs-shell', '');
    shell.innerHTML =
      '<div class="fs-top">' +
        '<button type="button" class="fs-burger" id="fsBurger" aria-label="Open Go to: all destinations and search">&#9776;</button>' +
        '<a class="fs-mark" href="index.html" aria-label="FutScout home">FUTSCOUT<span>_</span></a>' +
        '<nav class="fs-groups" id="fsGroups" aria-label="Site sections">' + groupMenus() + '</nav>' +
        '<div class="fs-right">' +
          '<label class="fs-scope"><span class="fs-lab">Scope</span><span class="fs-scope-slot" id="fsScopeSlot">' +
            '<select id="fsScopeSel" disabled aria-label="League scope" title="This page does not filter by league. The scope you chose elsewhere is kept."><option>' + esc(scopeLabel()) + '</option></select>' +
          '</span></label>' +
          '<span class="fs-fresh" id="fsFresh" role="status"><i class="fs-dot" aria-hidden="true"></i><span id="fsFreshText">Data &hellip;</span></span>' +
          '<span class="fs-goto" id="fsGoto"><button type="button" class="fs-k" id="fsGotoBtn" aria-haspopup="dialog" aria-controls="fsPalette">Go to <kbd>' + (mac ? '&#8984;K' : 'Ctrl K') + '</kbd></button></span>' +
          '<button type="button" class="fs-k" id="fsThemeBtn" aria-pressed="' + isDark() + '" aria-label="Dark theme" title="Switch between the light and dark theme for the whole site">Theme</button>' +
        '</div>' +
      '</div>' +
      '<div class="fs-ws">' +
        '<span class="fs-crumb" id="fsCrumb">// ' + esc(here.name) + '</span>' +
        '<div class="fs-ws-tabs" id="fsTabsSlot"></div>' +
        '<div class="fs-ws-right"><span class="fs-pop" id="fsPop"></span><span class="fs-actions" id="fsActionsSlot"></span></div>' +
      '</div>' +
      '<div class="fs-banner fs-banner-stale fs-shell-stale" id="fsStale" hidden>' +
        '<span class="fs-banner-label">Stale</span>' +
        '<span class="fs-banner-text" id="fsStaleText"></span>' +
        '<button type="button" class="fs-k" id="fsStaleRefresh">Refresh</button>' +
      '</div>';
    var placeholder = document.querySelector('[data-fs-shell-here]');
    if (placeholder) placeholder.replaceWith(shell); else document.body.insertBefore(shell, document.body.firstChild);

    els.shell = shell;
    els.theme = shell.querySelector('#fsThemeBtn');
    els.fresh = shell.querySelector('#fsFresh');
    els.freshText = shell.querySelector('#fsFreshText');
    els.stale = shell.querySelector('#fsStale');
    els.pop = shell.querySelector('#fsPop');
    els.crumb = shell.querySelector('#fsCrumb');

    els.theme.addEventListener('click', toggleTheme);
    shell.querySelector('#fsGotoBtn').addEventListener('click', function () { openPalette(''); });
    shell.querySelector('#fsBurger').addEventListener('click', function () { openPalette(''); });
    shell.querySelector('#fsStaleRefresh').addEventListener('click', function () { location.reload(); });
    wireMenus(shell.querySelector('#fsGroups'));
    renderFreshness();

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready);
    else ready();
  }

  /* Group menus: <details>, closed on outside click and Escape, focus trapped
     while open, focus returned to the summary on close. */
  function wireMenus(nav) {
    var groups = Array.prototype.slice.call(nav.querySelectorAll('details'));
    function close(d, refocus) {
      if (!d.open) return;
      d.open = false;
      if (refocus) d.querySelector('summary').focus();
    }
    groups.forEach(function (d) {
      d.addEventListener('toggle', function () {
        if (d.open) groups.forEach(function (o) { if (o !== d) o.open = false; });
      });
      d.addEventListener('keydown', function (event) {
        if (!d.open) return;
        var items = [d.querySelector('summary')].concat(Array.prototype.slice.call(d.querySelectorAll('.fs-menu a')));
        var i = items.indexOf(document.activeElement);
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(d, true); }
        else if (event.key === 'Tab') {
          event.preventDefault();
          items[(i + (event.shiftKey ? -1 : 1) + items.length) % items.length].focus();
        } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault();
          items[(i + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
        }
      });
    });
    document.addEventListener('pointerdown', function (event) {
      groups.forEach(function (d) { if (d.open && !d.contains(event.target)) close(d, false); });
    });
  }

  /* ---------- Slots ---------- */
  function adopt() {
    if (!mounted) return;
    var map = {tabs: '#fsTabsSlot', scope: '#fsScopeSlot', actions: '#fsActionsSlot', pop: '#fsPop'};
    Object.keys(map).forEach(function (name) {
      var host = els.shell.querySelector(map[name]);
      document.querySelectorAll('[data-fs-slot="' + name + '"]').forEach(function (node) {
        if (els.shell.contains(node)) return;
        if (name === 'scope') {
          var placeholder = host.querySelector('#fsScopeSel');
          if (placeholder) placeholder.remove();
        }
        host.appendChild(node);
      });
    });
    var crumb = document.body.getAttribute('data-fs-crumb');
    if (crumb) els.crumb.textContent = '// ' + crumb;
    adopted = true;
  }

  /* A page whose league control is not a select (chips, cards) registers its
     scope here; the shell then renders the select and the page keeps its own
     control in sync through onChange. */
  function registerScope(config) {
    scopeReg = config || null;
    if (!mounted || !scopeReg) return;
    var host = els.shell.querySelector('#fsScopeSlot');
    var select = host.querySelector('#fsScopeSel');
    if (!select) { select = document.createElement('select'); select.id = 'fsScopeSel'; host.appendChild(select); }
    select.disabled = !!config.disabled;
    select.setAttribute('aria-label', 'League scope');
    select.title = config.title || 'League scope for this page. The choice carries to every page that can filter by league.';
    select.innerHTML = (config.options || []).map(function (o) {
      return '<option value="' + esc(o.value) + '"' + (String(o.value) === String(config.value) ? ' selected' : '') + '>' + esc(o.label) + '</option>';
    }).join('');
    select.onchange = function () { if (scopeReg && scopeReg.onChange) scopeReg.onChange(select.value); };
  }
  function setScopeValue(value) {
    var select = mounted && els.shell.querySelector('#fsScopeSel');
    if (select && !select.disabled) select.value = value;
  }

  /* ---------- Freshness ---------- */
  function fmtSnapshot(date) {
    var mon = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'][date.getMonth()];
    function two(n) { return (n < 10 ? '0' : '') + n; }
    return two(date.getDate()) + ' ' + mon + ' ' + two(date.getHours()) + ':' + two(date.getMinutes());
  }
  function freshnessState() {
    if (!freshness || !freshness.as_of) return null;
    var date = new Date(freshness.as_of);
    if (isNaN(date)) return null;
    var hours = Math.max(0, (Date.now() - date.getTime()) / 36e5);
    var stale = typeof freshness.is_stale === 'boolean' ? freshness.is_stale : hours > STALE_FALLBACK_HOURS;
    return {date: date, hours: hours, stale: stale, rule: typeof freshness.is_stale === 'boolean' ? 'source' : 'fallback',
      text: fmtSnapshot(date), age: Math.round(hours) + 'h old'};
  }
  function renderFreshness() {
    if (!mounted) return;
    var s = freshnessState();
    els.fresh.classList.toggle('is-stale', !!(s && s.stale));
    els.fresh.classList.toggle('is-missing', !s);
    if (!s) {
      els.freshText.textContent = 'Data snapshot not reported';
      els.fresh.title = 'No analytics snapshot time has been supplied to this page.';
      els.stale.hidden = true;
      return;
    }
    els.freshText.textContent = 'Data ' + s.text + ' · ' + s.age;
    els.fresh.title = (freshnessFromPage ? 'Snapshot reported by this page.' : 'Shared analytics snapshot (v_analytics_as_of). This page reports no snapshot of its own.') +
      ' Age is measured from the last completed analytics rebuild, not from this page load.';
    els.stale.hidden = !s.stale;
    if (s.stale) {
      els.shell.querySelector('#fsStaleText').textContent = 'Snapshot ' + s.text + ', ' + s.age + '. ' +
        (s.rule === 'source' ? 'The source marks this rebuild as stale.' : 'Older than the provisional ' + (STALE_FALLBACK_HOURS / 24) + '-day threshold.') +
        ' Newer matches may be missing; everything shown is still the last verified rebuild.';
    }
  }
  function setFreshness(row, fromPage) {
    if (row && row.as_of) {
      freshness = {as_of: row.as_of, is_stale: row.is_stale, hours_old: row.hours_old};
      freshnessFromPage = fromPage !== false;
      store('session', 'fsSnapshot', JSON.stringify(freshness));
    } else if (fromPage !== false) {
      freshnessFromPage = true;
    }
    renderFreshness();
  }
  function loadSharedFreshness() {
    if (freshness) return;
    var cached = store('session', 'fsSnapshot');
    if (cached) { try { freshness = JSON.parse(cached); freshnessFromPage = false; renderFreshness(); return; } catch (e) {} }
    /* The same read the player and team pages already make. */
    fetch(SB + '/rest/v1/v_analytics_as_of?select=*', {headers: HD})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (rows) { if (!freshnessFromPage && rows && rows[0]) setFreshness(rows[0], false); })
      .catch(function () {});
  }
  function snapshotStamp() {
    var s = freshnessState();
    return s ? {snapshot: s.date.toISOString(), text: s.text, age: s.age, stale: s.stale} : null;
  }

  /* ---------- Toast ---------- */
  var toastTimer = null;
  function toast(text) {
    if (!document.body) return;
    var node = document.getElementById('fsToast');
    if (!node) {
      node = document.createElement('div');
      node.id = 'fsToast'; node.className = 'fs-toast';
      node.setAttribute('role', 'status'); node.setAttribute('aria-live', 'polite');
      document.body.appendChild(node);
    }
    node.textContent = text;
    node.classList.add('on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { node.classList.remove('on'); }, 2200);
  }

  /* ---------- Entity search (the Go To search, shared with the home find bar) ---------- */
  var entityData = null, entityPromise = null;
  function sbAll(table, params) {
    var PG = 1000, all = [], off = 0;
    function page() {
      var u = new URL(SB + '/rest/v1/' + table);
      Object.keys(params || {}).forEach(function (k) { u.searchParams.set(k, params[k]); });
      return fetch(u, {headers: Object.assign({}, HD, {Range: off + '-' + (off + PG - 1), 'Range-Unit': 'items'})})
        .then(function (r) { if (!r.ok) throw new Error(table + ' ' + r.status); return r.json(); })
        .then(function (d) {
          if (!Array.isArray(d) || !d.length) return all;
          all = all.concat(d);
          if (d.length < PG) return all;
          off += PG; return page();
        });
    }
    return page();
  }
  function loadEntities() {
    if (entityPromise) return entityPromise;
    entityPromise = Promise.all([
      sbAll('mv_team_all', {select: 'team,matches'}),
      sbAll('mv_player_season', {select: 'player_id,player_name,team,nineties'}),
      sbAll('mv_player_role', {select: 'player_id,pool'}),
      sbAll('v_league_matches', {select: 'game_id,date,home_team,away_team,home_score,away_score', home_score: 'not.is.null', order: 'date.desc'}),
      sbAll('team_names', {select: 'event_name,match_name,display_name'})
    ]).then(function (r) {
      var names = {}, roles = {};
      (r[4] || []).forEach(function (m) { names[m.event_name] = m.display_name; names[m.match_name] = m.display_name; });
      (r[2] || []).forEach(function (x) { roles[x.player_id] = x.pool; });
      entityData = {
        tname: function (t) { return names[t] || t || ''; },
        teams: r[0] || [],
        players: (r[1] || []).map(function (p) { return {id: p.player_id, name: p.player_name, team: p.team, n90: +p.nineties, pool: roles[p.player_id] || ''}; })
          .sort(function (a, b) { return b.n90 - a.n90; }),
        matches: r[3] || []
      };
      return entityData;
    }).catch(function (error) { entityPromise = null; throw error; });
    return entityPromise;
  }
  function entitySearch(query) {
    var v = String(query || '').toLowerCase().trim();
    if (!v) return Promise.resolve([]);
    return loadEntities().then(function (d) {
      var p = d.players.filter(function (x) { return (x.name || '').toLowerCase().indexOf(v) >= 0; }).slice(0, 7).map(function (x) {
        return {kind: 'player', tag: x.pool || 'PL', name: x.name, meta: d.tname(x.team) + ' · ' + x.n90.toFixed(1) + '×90', href: 'players.html?player=' + encodeURIComponent(x.id)};
      });
      var t = d.teams.filter(function (x) { return d.tname(x.team).toLowerCase().indexOf(v) >= 0; }).slice(0, 5).map(function (x) {
        return {kind: 'team', tag: 'TEAM', name: d.tname(x.team), meta: x.matches + ' matches', href: 'teams.html?team=' + encodeURIComponent(x.team)};
      });
      var m = d.matches.filter(function (x) { return (d.tname(x.home_team) + ' ' + d.tname(x.away_team)).toLowerCase().indexOf(v) >= 0; }).slice(0, 4).map(function (x) {
        return {kind: 'match', tag: 'MTCH', name: d.tname(x.home_team) + ' ' + x.home_score + '–' + x.away_score + ' ' + d.tname(x.away_team), meta: String(x.date).slice(0, 10), href: 'match.html?game=' + encodeURIComponent(x.game_id)};
      });
      return p.concat(t, m);
    });
  }

  /* ---------- Palette ---------- */
  var paletteSeq = 0, paletteReturn = null;
  function buildPalette() {
    var dialog = document.getElementById('fsPalette');
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'fsPalette'; dialog.className = 'fs-palette';
    dialog.setAttribute('aria-label', 'Go to: destinations, players, teams and matches');
    dialog.innerHTML =
      '<div class="fs-pal-head"><span class="fs-lab">Go to</span>' +
        '<input id="fsPalInput" type="search" autocomplete="off" spellcheck="false" placeholder="Destination, player, team or match" aria-label="Search destinations, players, teams and matches">' +
        '<button type="button" class="fs-k" id="fsPalClose">Esc</button></div>' +
      '<div class="fs-pal-body">' +
        '<nav id="fsDestinationLinks" aria-label="All FutScout destinations"></nav>' +
        '<div id="fsPalHits" aria-live="polite"></div>' +
      '</div>';
    document.body.appendChild(dialog);
    var input = dialog.querySelector('#fsPalInput');
    input.addEventListener('input', function () { renderPalette(input.value); });
    dialog.querySelector('#fsPalClose').addEventListener('click', function () { dialog.close(); });
    dialog.addEventListener('click', function (event) { if (event.target === dialog) dialog.close(); });
    dialog.addEventListener('close', function () {
      if (paletteReturn && document.contains(paletteReturn)) paletteReturn.focus();
      paletteReturn = null;
    });
    dialog.addEventListener('keydown', function (event) {
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
      var rows = Array.prototype.slice.call(dialog.querySelectorAll('a.fs-pal-row:not([hidden])'));
      if (!rows.length) return;
      event.preventDefault();
      var i = rows.indexOf(document.activeElement);
      var next = event.key === 'ArrowDown' ? (i + 1) % rows.length : (i <= 0 ? -1 : i - 1);
      if (next < 0) input.focus(); else rows[next].focus();
    });
    input.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter') return;
      var first = dialog.querySelector('a.fs-pal-row:not([hidden])');
      if (first) { event.preventDefault(); location.href = first.href; }
    });
    return dialog;
  }
  function renderPalette(query, group) {
    var dialog = buildPalette(), file = currentFile();
    var v = String(query || '').toLowerCase().trim();
    var nav = dialog.querySelector('#fsDestinationLinks');
    nav.innerHTML = DESTINATIONS.map(function (g) {
      var rows = g[1].map(function (item) {
        var hit = (!v || (item[0] + ' ' + g[0]).toLowerCase().indexOf(v) >= 0) && (!group || group === g[0]);
        return '<a class="fs-pal-row" href="' + item[1] + '"' + (item[1] === file ? ' aria-current="page"' : '') + (hit ? '' : ' hidden') + '>' +
          '<span class="fs-tag">' + esc(g[0]) + '</span><span class="fs-pal-name">' + esc(item[0]) + '</span>' +
          (item[1] === file ? '<span class="fs-pal-meta">You are here</span>' : '') + '</a>';
      }).join('');
      return '<div class="fs-pal-group" data-group="' + esc(g[0]) + '">' + rows + '</div>';
    }).join('');
    var hits = dialog.querySelector('#fsPalHits');
    var seq = ++paletteSeq;
    if (!v) { hits.innerHTML = '<p class="fs-pal-note">Type to search players, teams and matches.</p>'; return; }
    hits.innerHTML = '<p class="fs-pal-note">Searching players, teams and matches&hellip;</p>';
    entitySearch(v).then(function (list) {
      if (seq !== paletteSeq) return;
      hits.innerHTML = list.length ? list.map(function (x) {
        return '<a class="fs-pal-row" href="' + esc(x.href) + '"><span class="fs-tag">' + esc(x.tag) + '</span>' +
          '<span class="fs-pal-name">' + esc(x.name) + '</span><span class="fs-pal-meta">' + esc(x.meta) + '</span></a>';
      }).join('') : '<p class="fs-pal-note">No player, team or match contains &ldquo;' + esc(v) + '&rdquo;.</p>';
    }).catch(function () {
      if (seq !== paletteSeq) return;
      hits.innerHTML = '<p class="fs-pal-note">Player, team and match search is unavailable right now. Destinations above still work.</p>';
    });
  }
  function openPalette(query, group) {
    var dialog = buildPalette();
    if (dialog.open) { dialog.close(); return; }
    paletteReturn = document.activeElement;
    var input = dialog.querySelector('#fsPalInput');
    input.value = query || '';
    renderPalette(input.value, group);
    if (dialog.showModal) dialog.showModal(); else dialog.setAttribute('open', '');
    input.focus();
  }
  document.addEventListener('keydown', function (event) {
    if ((event.metaKey || event.ctrlKey) && !event.altKey && String(event.key).toLowerCase() === 'k') {
      event.preventDefault();
      openPalette('');
    }
  });

  /* ---------- Phone bottom bar ---------- */
  function buildBottomBar() {
    if (document.getElementById('fsBottom')) return;
    var here = currentGroup();
    var bar = document.createElement('nav');
    bar.id = 'fsBottom'; bar.className = 'fs-bottom';
    bar.setAttribute('aria-label', 'Site sections');
    bar.innerHTML = DESTINATIONS.map(function (g) {
      var active = g[0] === here.group ? ' class="is-active" aria-current="true"' : '';
      return g[1].length === 1
        ? '<a href="' + g[1][0][1] + '"' + active + '>' + esc(g[0]) + '</a>'
        : '<button type="button" data-group="' + esc(g[0]) + '"' + active + '>' + esc(g[0]) + '</button>';
    }).join('');
    bar.addEventListener('click', function (event) {
      var b = event.target.closest('button[data-group]');
      if (b) openPalette('', b.dataset.group);
    });
    document.body.appendChild(bar);
  }

  /* ---------- Narrow class ----------
     Layouts collapse on the width the app actually has, not the viewport, so a
     canvas beside a rail collapses when IT is narrow. */
  function observeNarrow(node, limit) {
    if (!node || !window.ResizeObserver || node.__fsNarrow) return;
    node.__fsNarrow = true;
    limit = limit || 900;
    new ResizeObserver(function (entries) {
      var width = entries[0].contentRect.width;
      var narrow = width > 0 && width <= limit;
      if (node.classList.contains('narrow') !== narrow) {
        node.classList.toggle('narrow', narrow);
        window.dispatchEvent(new CustomEvent('fs:narrow', {detail: {node: node, narrow: narrow}}));
      }
    }).observe(node);
  }

  /* ---------- Exports ---------- */
  function safeName(value) {
    return String(value || 'futscout-visual').trim().replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase();
  }
  function exportLabel(card) {
    var title = card.querySelector('[data-chart-title],.viz-title,.sect-h span,h1,h2,h3');
    return title && title.textContent.trim() ? title.textContent.trim() : 'FutScout visual';
  }
  function loadScript(src, ready) {
    if (ready()) return Promise.resolve();
    return new Promise(function (resolve, reject) {
      var existing = document.querySelector('script[src="' + src + '"]');
      var script = existing || document.createElement('script');
      function done() { ready() ? resolve() : reject(new Error('Export library did not initialize')); }
      script.addEventListener('load', done, {once: true});
      script.addEventListener('error', function () { reject(new Error('Could not load the export library')); }, {once: true});
      if (!existing) { script.src = src; document.head.appendChild(script); }
    });
  }
  async function ensureExportLibraries(format) {
    await loadScript('https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js', function () { return !!window.html2canvas; });
    if (format === 'pdf') {
      await loadScript('https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js', function () { return !!(window.jspdf && window.jspdf.jsPDF); });
    }
  }

  /* The stamp every export carries. Known keys lead in a fixed order; anything
     else a page supplies follows. Snapshot time and export time are separate
     values on purpose: one is the data, the other is the download. */
  var STAMP_ORDER = ['entity','subject','workspace','view','scope','league','cohort','population','window','filters','poolNote','valuationDate','source','coverage'];
  var STAMP_LABEL = {entity:'Entity',subject:'Entity',workspace:'Workspace',view:'View',scope:'Scope',league:'League',cohort:'Cohort',population:'Population',window:'Time window',filters:'Filters',poolNote:'Pool',valuationDate:'Valuation date',source:'Source',coverage:'Coverage'};
  function stampValue(value) {
    if (value == null || value === '') return '';
    if (typeof value === 'object') { try { return JSON.stringify(value); } catch (e) { return String(value); } }
    return String(value);
  }
  function stampRows(metadata, snapshot, exportTime, sourceURL) {
    var rows = [], seen = {};
    STAMP_ORDER.forEach(function (key) {
      var v = stampValue(metadata && metadata[key]);
      if (v) { rows.push([STAMP_LABEL[key], v]); seen[key] = true; }
    });
    Object.keys(metadata || {}).forEach(function (key) {
      if (seen[key] || key === 'url' || key === 'sourceURL' || key === 'exportedAt') return;
      var v = stampValue(metadata[key]);
      if (v) rows.push([key.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/_/g, ' '), v]);
    });
    if (!rows.length) rows.push(['Scope', 'As labelled in this view; no further provenance supplied by the page']);
    rows.push(['Data snapshot', snapshot ? snapshot.text + ' · ' + snapshot.age + (snapshot.stale ? ' · STALE' : '') + ' (' + snapshot.snapshot + ')' : 'Not reported']);
    rows.push(['Exported', exportTime + ' (export time, not data freshness)']);
    rows.push(['Source page', sourceURL]);
    return rows;
  }
  function stampBlock(label, metadata, snapshot, exportTime, sourceURL) {
    var block = document.createElement('div');
    block.className = 'fs-stamp';
    block.innerHTML = '<div class="fs-stamp-head"><span class="fs-mark">FUTSCOUT<span>_</span></span><span class="fs-stamp-title">' + esc(label) + '</span></div>' +
      '<dl>' + stampRows(metadata, snapshot, exportTime, sourceURL).map(function (row) {
        return '<dt>' + esc(row[0]) + '</dt><dd>' + esc(row[1]) + '</dd>';
      }).join('') + '</dl>';
    return block;
  }
  /* The same lines for CSV and clipboard outputs. */
  function exportHeaderLines(card) {
    var metadata = {};
    try { metadata = typeof window.futScoutExportContext === 'function' ? (window.futScoutExportContext(card) || {}) : {}; } catch (e) {}
    return stampRows(metadata, snapshotStamp(), new Date().toISOString(), location.href);
  }

  async function captureCard(card, format, button) {
    var label = exportLabel(card),sourceURL=location.href,exportTime=new Date().toISOString(),snapshot=snapshotStamp(),clone=card.cloneNode(true),metadata={};try{metadata=JSON.parse(JSON.stringify(card.dataset.exportContext?JSON.parse(card.dataset.exportContext):(typeof window.futScoutExportContext==='function'?window.futScoutExportContext(card):{})))}catch(error){metadata={contextError:'Context unavailable'}}card.querySelectorAll('canvas').forEach(function(source,i){var target=clone.querySelectorAll('canvas')[i];target.width=source.width;target.height=source.height;target.getContext('2d').drawImage(source,0,0)});
    var control=button&&(button.closest('.fs-card-export')||button);
    if(control)control.classList.add('fs-exporting');
    try {
      await ensureExportLibraries(format);
    } catch (error) {
      if(control)control.classList.remove('fs-exporting');
      toast('Export unavailable: ' + error.message);
      return;
    }
    var stage = document.createElement('div');
    /* Exports ignore the page theme: the stage re-declares the light tokens. */
    stage.className = 'fs-export-stage fs-light';
    // The card pixels, metadata and URL were captured before the first await.
    // Immutable metadata captured above.
    // Do not consult live page state after export libraries resolve.
    clone.querySelectorAll('.fs-card-export,.fs-export-bar,.viz-exp,[data-export],input,select').forEach(function (node) { node.remove(); });
    clone.querySelectorAll('button').forEach(function(node){var text=document.createElement('span');text.innerHTML=node.innerHTML;text.className=node.className;text.style.cssText=node.style.cssText;node.replaceWith(text);});
    clone.querySelectorAll('details').forEach(function(node){node.open=true;});
    stage.appendChild(clone);
    stage.appendChild(stampBlock(label, metadata, snapshot, exportTime, sourceURL));
    document.body.appendChild(stage);
    clone.querySelectorAll('*').forEach(function (node) {
      var style = getComputedStyle(node);
      if (style.overflowY === 'auto' || style.overflowY === 'scroll' || style.maxHeight !== 'none') {
        node.style.maxHeight = 'none';
        node.style.height = 'auto';
        node.style.overflow = 'visible';
      }
    });
    clone.style.maxHeight = 'none';
    clone.style.overflow = 'visible';
    /* html2canvas rasterises each inline SVG as a standalone image, where
       stylesheet classes and var() do not resolve. The stage is in the live
       document under the light tokens, so resolve the paint here and write it
       onto every SVG node. */
    (function(){
      var px=document.createElement('canvas');px.width=px.height=1;var cx=px.getContext('2d'),memo={};
      function plain(value){
        if(!value||!/(?:color|oklch|oklab|lab|lch|color-mix)\(/.test(value))return value;
        if(memo[value])return memo[value];
        cx.clearRect(0,0,1,1);cx.fillStyle=value;cx.fillRect(0,0,1,1);var d=cx.getImageData(0,0,1,1).data;
        return memo[value]='rgba('+d[0]+','+d[1]+','+d[2]+','+(d[3]/255)+')';
      }
      var props=['fill','stroke','stroke-width','stroke-dasharray','stroke-linecap','stroke-linejoin','opacity','fill-opacity','stroke-opacity','color','font-family','font-size','font-weight','letter-spacing','text-anchor','dominant-baseline','visibility','display'];
      stage.querySelectorAll('svg, svg *').forEach(function(node){
        var cs=getComputedStyle(node);
        props.forEach(function(prop){var v=cs.getPropertyValue(prop);if(v)node.style.setProperty(prop,plain(v));});
      });
    })();
    // Wide tables must expand the capture surface, not disappear beyond its edge.
    stage.style.width=Math.max(1120,stage.scrollWidth)+'px';
    try {
      var bg = getComputedStyle(stage).backgroundColor;
      var canvas = await window.html2canvas(stage, {backgroundColor: bg, scale: 2, useCORS: true, width:stage.scrollWidth, windowWidth: stage.scrollWidth, height: stage.scrollHeight, windowHeight: stage.scrollHeight,
        onclone: function(doc) {
          // Always light: the cloned document drops the dark theme entirely.
          doc.documentElement.setAttribute('data-theme','light'); doc.documentElement.classList.remove('dark');
          // html2canvas 1.4 cannot parse modern color()/oklch() output from color-mix.
          // Let the browser resolve those colours, then serialize an sRGB equivalent.
          var pixel=doc.createElement('canvas'); pixel.width=pixel.height=1;
          var ctx=pixel.getContext('2d'), cache={};
          function rgba(value) {
            if(cache[value]) return cache[value];
            ctx.clearRect(0,0,1,1); ctx.fillStyle=value; ctx.fillRect(0,0,1,1);
            var p=ctx.getImageData(0,0,1,1).data;
            return cache[value]='rgba('+p[0]+','+p[1]+','+p[2]+','+(p[3]/255)+')';
          }
          doc.querySelectorAll('*').forEach(function(node){
            var style=doc.defaultView.getComputedStyle(node);
            ['color','backgroundColor','borderTopColor','borderRightColor','borderBottomColor','borderLeftColor','outlineColor','fill','stroke'].forEach(function(prop){
              var value=style[prop]; if(value && /(?:color|oklch|oklab|lab|lch)\(/.test(value))node.style[prop]=rgba(value);
            });
          });
        }});
      var base = safeName((document.title || 'FutScout') + '-' + label);
      if (format === 'png') {
        var anchor = document.createElement('a');
        anchor.download = base + '.png';
        anchor.href = canvas.toDataURL('image/png');
        anchor.click();
        toast('PNG exported \u00B7 light \u00B7 stamped');
      } else {
        if (!window.jspdf || !window.jspdf.jsPDF) throw new Error('PDF library is unavailable');
        var jsPDF = window.jspdf.jsPDF;
        var landscape = canvas.width / canvas.height >= 1.45;
        var pdf = new jsPDF({orientation: landscape ? 'l' : 'p', unit: 'pt', format: 'a4'});
        var pw = pdf.internal.pageSize.getWidth();
        var ph = pdf.internal.pageSize.getHeight();
        var ratio = (pw - 32) / canvas.width;
        var sliceHeight = Math.floor((ph - 48) / ratio);
        var stageTop=stage.getBoundingClientRect().top;
        var boundaries=Array.from(stage.querySelectorAll('tr,.rank-row,.frow,.match')).map(function(node){var r=node.getBoundingClientRect();return {top:Math.round((r.top-stageTop)*2),bottom:Math.round((r.bottom-stageTop)*2)};});
        var headers=Array.from(stage.querySelectorAll('table')).map(function(table){var head=table.querySelector('thead');if(!head)return null;var h=head.getBoundingClientRect(),t=table.getBoundingClientRect();return {top:Math.round((h.top-stageTop)*2),height:Math.round(h.height*2),bottom:Math.round((t.bottom-stageTop)*2)};}).filter(Boolean);
        for (var offset=0,page=1;offset<canvas.height;page++) {
          if (offset) pdf.addPage();
          var header=offset?headers.find(function(h){return offset>h.top+h.height&&offset<h.bottom;}):null;
          var repeat=header?header.height:0;
          var end=Math.min(canvas.height,offset+sliceHeight-repeat);
          var crossing=boundaries.find(function(row){return row.top>offset&&row.top<end&&row.bottom>end;});
          if(crossing)end=crossing.top;
          var slice=document.createElement('canvas');
          slice.width=canvas.width; slice.height=end-offset;
          slice.getContext('2d').drawImage(canvas,0,offset,canvas.width,slice.height,0,0,canvas.width,slice.height);
          if(header){var headCanvas=document.createElement('canvas');headCanvas.width=canvas.width;headCanvas.height=header.height;headCanvas.getContext('2d').drawImage(canvas,0,header.top,canvas.width,header.height,0,0,canvas.width,header.height);pdf.addImage(headCanvas.toDataURL('image/jpeg',.92),'JPEG',16,16,headCanvas.width*ratio,headCanvas.height*ratio,undefined,'FAST');}
          pdf.addImage(slice.toDataURL('image/jpeg',.92),'JPEG',16,16+repeat*ratio,slice.width*ratio,slice.height*ratio,undefined,'FAST');
          pdf.setFontSize(9); pdf.text('FutScout · '+page,16,ph-12);
          offset=end;
        }
        pdf.save(base + '.pdf');
        toast('PDF exported \u00B7 light \u00B7 stamped');
      }
    } catch (error) {
      toast('Export failed: ' + error.message);
    } finally {
      stage.remove();
      if(control)control.classList.remove('fs-exporting');
    }
  }

  window.FutScoutExports={capture:captureCard};
  function exportTable(card){
    var rows=Array.from(card.querySelectorAll('table tr')).map(function(row){return Array.from(row.querySelectorAll('th,td')).map(function(cell){return '"'+cell.textContent.trim().replace(/"/g,'""')+'"';}).join(',');});
    /* Header lines: scope, filters, cohort, snapshot time, export time, source. */
    var head=exportHeaderLines(card).map(function(row){return '"'+String(row[0]).replace(/"/g,'""')+'","'+String(row[1]).replace(/"/g,'""')+'"';});
    head.unshift('"FutScout","'+exportLabel(card).replace(/"/g,'""')+'"');
    rows=head.concat([''],rows);
    var url=URL.createObjectURL(new Blob(['﻿'+rows.join('\r\n')],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=safeName(exportLabel(card))+'.csv';a.click();setTimeout(function(){URL.revokeObjectURL(url)},1000);toast('CSV exported \u00B7 stamped');
  }

  function exportable(card) {
    if (card.closest('.fs-export-stage') || card.matches('.studio-controls,.controls,[data-export-manual]') || card.querySelector('.viz-exp,[data-export]')) return false;
    return !!card.querySelector('svg,canvas,table,.pizza-shell,.rankbar');
  }

  function enhanceExports() {
    document.querySelectorAll('.sect,.panel,[data-export-card]').forEach(function (card) {
      if (card.querySelector('.sect,.panel,[data-export-card]')) return;
      if (!exportable(card) || card.querySelector(':scope > .fs-export-bar,:scope > .sect-h .fs-card-export')) return;
      var controls = document.createElement('div');
      controls.className = 'fs-card-export';
      controls.innerHTML = '<button type="button" data-format="png">PNG</button><button type="button" data-format="pdf">PDF</button>';
      if(card.querySelector('table'))controls.insertAdjacentHTML('beforeend','<button type="button" data-format="csv">CSV</button>');
      controls.querySelectorAll('button').forEach(function (button) {
        button.setAttribute('aria-label', 'Download ' + exportLabel(card) + ' as ' + button.dataset.format.toUpperCase());
        button.addEventListener('click', function () { if(button.dataset.format==='csv')exportTable(card);else captureCard(card, button.dataset.format, button); });
      });
      var heading = card.querySelector(':scope > .sect-h');
      if (heading) heading.appendChild(controls);
      else {
        var bar = document.createElement('div');
        bar.className = 'fs-export-bar';
        bar.appendChild(controls);
        card.insertBefore(bar, card.firstChild);
      }
    });
  }

  /* The workspace row is dropped on phone when it has neither tabs nor
     actions. Slots hold adopted containers, so emptiness is measured by
     controls, not by child nodes. */
  function markWorkspace() {
    var ws = els.shell.querySelector('.fs-ws');
    var has = !!ws.querySelector('#fsTabsSlot :is(a,button), #fsActionsSlot :is(a,button)');
    ws.classList.toggle('is-empty', !has);
  }

  /* ---------- Ready ---------- */
  function ready() {
    adopt();
    markWorkspace();
    new MutationObserver(markWorkspace).observe(els.shell.querySelector('.fs-ws'), {childList: true, subtree: true});
    if (scopeReg) registerScope(scopeReg);
    buildBottomBar();
    buildPalette();
    renderPalette('');
    loadSharedFreshness();
    document.querySelectorAll('[data-fs-app],main').forEach(function (node) { observeNarrow(node); });
    if(['methodology.html','guide.html','validation.html','evidence-contracts.html','glossary.html'].includes(currentFile())){
      document.querySelectorAll('table').forEach(function(table){if(table.parentElement.classList.contains('fs-table-scroll'))return;var region=document.createElement('div');region.className='fs-table-scroll';region.tabIndex=0;region.setAttribute('role','region');region.setAttribute('aria-label','Scrollable evidence table');table.before(region);region.appendChild(table);});
    }
    enhanceExports();
    var queued = false;
    new MutationObserver(function () {
      if (queued) return;
      queued = true;
      requestAnimationFrame(function () { queued = false; enhanceExports(); });
    }).observe(document.body, {childList: true, subtree: true});
  }

  window.FutScout = {
    destinations: DESTINATIONS,
    STALE_FALLBACK_HOURS: STALE_FALLBACK_HOURS,
    mount: mount,
    adopt: adopt,
    registerScope: registerScope,
    setScopeValue: setScopeValue,
    setFreshness: setFreshness,
    snapshot: snapshotStamp,
    exportHeaderLines: exportHeaderLines,
    setPopulation: function (text) { if (mounted) els.pop.textContent = text || ''; },
    toast: toast,
    openPalette: openPalette,
    entitySearch: entitySearch,
    observeNarrow: observeNarrow,
    isDark: isDark,
    setTheme: function (theme) { store('local', 'theme', theme); applyTheme(theme, true); },
    toggleTheme: toggleTheme
  };

  /* Older regression scripts flip the theme through a page-level toggleTheme();
     the pages no longer define one, so the name points at the global control. */
  if (typeof window.toggleTheme !== 'function') window.toggleTheme = toggleTheme;

  /* A page that has not been given the body hook still gets the shell. */
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
})();
