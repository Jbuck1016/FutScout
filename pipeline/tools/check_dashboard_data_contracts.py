#!/usr/bin/env python3
"""Static regression checks for dashboard data-to-visual contracts."""
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "dashboard"
ACTIVE_PAGES = [
    "index.html", "insights.html", "match.html", "players.html",
    "teams.html", "sequences.html",
]


def main() -> int:
    failures: list[str] = []

    def require(condition: bool, message: str) -> None:
        print(("PASS  " if condition else "FAIL  ") + message)
        if not condition:
            failures.append(message)

    pages = {name: (DASHBOARD / name).read_text(encoding="utf-8") for name in ACTIVE_PAGES}
    # Press Room moved focus rings into theme.css and PNG/PDF capture into
    # site-tools.js, so those contracts are read from the shared files.
    theme_css = (DASHBOARD / "theme.css").read_text(encoding="utf-8")
    site_tools = (DASHBOARD / "site-tools.js").read_text(encoding="utf-8")
    shared_pdf = ("toDataURL('image/jpeg',.92),'JPEG'" in site_tools and
                  "undefined,'FAST'" in site_tools)

    # Unknown league membership may remain visible in an unscoped list, but it
    # must never be silently filed into MLS or shown as a zero-match MLS state.
    silent_mls = re.compile(r"(?:\|\||\?\?)\s*['\"]USA-MLS['\"]")
    for name, source in pages.items():
        require(not silent_mls.search(source), f"{name}: no silent USA-MLS fallback")
    require("LEAGUES=[{v:'USA-MLS',l:'MLS',n:0}]" not in pages["match.html"],
            "match.html: no fabricated zero-match MLS league list")

    # Raw history is retained for ingestion and audit, but active pages must
    # read the current-season boundary rather than querying archive tables.
    raw_browser_read = re.compile(
        r"(?:sbAll|sbGet)\(['\"](?:events|matches|sequences|lineups)['\"]"
        r"|/rest/v1/(?:events|matches|sequences|lineups)(?:[?'\"]|$)"
    )
    for name, source in pages.items():
        require(not raw_browser_read.search(source),
                f"{name}: browser data reads are current-season scoped")

    players = pages["players.html"]
    require("sbAll('mv_player_season',{select:'player_id,player_name,team,nineties,apps,starts,minutes'})" in players,
            "players.html: directory reads the complete appearance population")
    require("Object.assign({},s,rmap[s.player_id]||{})" in players,
            "players.html: role classification is optional for directory membership")
    require(".filter(function(p){return +(p.apps||0)>0||+(p.minutes||0)>0})" in players,
            "players.html: substitute appearances qualify for the directory")
    require(not re.search(r"\.filter\([^\n]{0,160}starts[^\n]{0,80}>\s*0", players),
            "players.html: directory is not filtered to starters")
    require("lgOfTeam(peer.team)===lg" in players and "eligible role peers" in players,
            "players.html: displayed comparison cohort is limited to the player's league and role")

    # WhoScored y=0 is the right touchline. SVG y grows downward, so this
    # transform puts right-sided actions at the bottom of the displayed pitch.
    require("function PY(y){return (100-y)*0.68}" in players,
            "players.html: WhoScored y-axis is inverted once at the renderer boundary")
    require(players.count("PY(") >= 9,
            "players.html: pass, shot, carry, receipt and zone primitives share PY()")
    require("Attack is always left-to-right." in players and "Attack is left to right;" in players,
            "players.html: visual and accessible orientation labels agree")
    require("Orientation · attack left → right · team right = bottom edge" in players and
            "Orientation · attack left → right · team right = bottom edge" in pages["teams.html"] and
            "Orientation · attack bottom → top · team right = screen right" in pages["match.html"],
            "player, team and match pitches teach their page-specific orientation")
    require('data-chart-title="scatter"' in players and
            "axes are raw values in their labelled units" in players,
            "players.html: scatter has a visible title and measurement context")
    require("x0>=0?Math.max(0,x0-padX)" in players and
            "y0>=0?Math.max(0,y0-padY)" in players,
            "players.html: scatter padding cannot invent negative values for nonnegative metrics")
    require('<i style="background:var(--ink)"></i>Cohort</span>' in players and
            '<i style="background:var(--accent)"></i>Selected player</span>' in players,
            "players.html: scatter keys its point colours")
    require("function shotSizeKey()" in players and
            "Example marker sizes: 0.05, 0.20 and 0.50 expected goals" in players and
            "cfg.sizeKey?shotSizeKey()" in players,
            "players.html: shot xG size encoding has a proportional symbol key")
    require("function shotOutcomeLegend(live,off)" in players and
            "outcomeKey:true" in players and "cfg.outcomeKey?shotOutcomeLegend" in players,
            "players.html: shot outcome legend demonstrates each plotted glyph")
    # The drill-downs were a div carrying role="button" tabindex="0" and its own
    # Enter/Space onkeydown. They are real buttons now, so Enter and Space come
    # from the element rather than from a hand-rolled handler, and each says
    # which dialog it opens and whether that dialog is open.
    require("<button type=\"button\" class=\"val-link\"" in players and
            "aria-label=\"Plot '+esc(d.label)" in players and
            "aria-haspopup=\"dialog\" aria-controls=\"drillWrap\" aria-expanded=\"false\"" in players and
            "role=\"button\" tabindex=\"0\"" not in players,
            "players.html: metric pitch drill-downs are keyboard operable")
    require("role=\"dialog\" aria-modal=\"true\"" in players and
            "aria-label=\"Close pitch evidence\"" in players and
            "e.key==='Escape'" in players and "DRILL_RETURN.focus()" in players,
            "players.html: pitch evidence dialog manages close and return focus")
    require("window.FutScoutExports" in site_tools and shared_pdf,
            "shared exports write PDFs from a compressed opaque image")
    require('<div class="fs-cols-2 research"><div class="pitch-host">' in players and
            players.index('class="pitch-host"') < players.index('class="measures-host"'),
            "players.html: pitch precedes the long metric table in single-column layouts")
    require("function actionMark(" in players and
            all(shape in players for shape in ["'triangle'", "'diamond'", "'square'", "'cross'", "'ring'"]),
            "players.html: multi-action maps distinguish layers without colour")
    require('class="fs-overview player-overview"' in players and
            "OVOPEN=false" in players and
            'aria-expanded="\'+OVOPEN+\'" aria-controls="ovGrid"' in players,
            "players.html: overview is collapsed by default behind a labelled toggle")
    require("SC.x==='prog_carries_90'&&SC.y==='key_pass_90'" in players and
            "not a verdict on quality" in players,
            "players.html: quadrant labels are limited to a defensible pairing")
    require("'Plot studio'" in players and "function renderPlotStudio()" in players and
            "function studioEventPlot()" in players,
            "players.html: custom player plot studio is a first-class analysis path")
    require("function pizzaSvg(keys,title,mode)" in players and
            "segmented percentile pizza" in players and
            "ringSlice" in players and "openCategoryPizza" in players,
            "players.html: category and custom pizzas use readable segmented radial wedges")
    require("Build across categories" in players and "selectedMetricTray" in players and
            "the slice list keeps them" in players,
            "players.html: pizza builder preserves cross-category metric selections")
    require("profile-brief" not in players and "Review question" not in players,
            "players.html: profile carries no interpretation card (Press Room brief)")
    require("Attacking half" in players and "VZ.shotFocus" in players and
            "Math.max(0.52" in players,
            "players.html: shot maps support attacking-half focus and visible low-xG markers")
    require("playerChoiceList" in players and "Search player or team" in players and
            "chain-details" in players and "compareChainPlayer" in players,
            "players.html: large player pickers are searchable and chain comparisons are compact")
    require("loadingPanel" in players and "Loading player evidence" in players and
            "Building scatter plot" in players,
            "players.html: expensive views retain a labelled loading shell")
    require("eventContextControls" in players and "Score state" in players and
            "Through minute" in players and "filterContext" in players and
            "eventTip" in players,
            "players.html: event evidence supports fixture, phase, clock and score-state inspection")
    require("Completed passes" in players and "Progressive carries" in players and
            "Interceptions" in players and "PB.pattern" in players,
            "players.html: custom event maps can combine attacking and defensive evidence")
    require("const TABS=['Player','Rank','Scatter','Scout','Compare','Plot studio']" in players and
            "const categoryTabs=['All'].concat(groups,p.pool==='GK'?[]:['Chain roles'])" in players and
            "if(GRP==='Chain roles')renderChainRoles(p.player_id)" in players and
            "select:'role,raw,pct,pool,league'" in players and "cohort.pool" in players,
            "players.html: chain roles have one working home inside the player profile")
    require("const owner=new Map()" in players and "owner.size+' distinct actions plotted" in players and
            "source records match these filters" in players,
            "players.html: overlapping pitch layers and record counts describe what is actually shown")
    require("viewBox=arguments[5]||'-3 -3 111.5 78'" in players and
            'viewBox="-3 -3 111.5 78"' in players,
            "players.html: attack label and plot filters stay inside their bounds")
    require(".c-pct{display:block;font:500 11px" in players and
            "Top '+rows.length+' of '+SK.rows.length+' qualifying players" in players,
            "players.html: Scout has readable result hierarchy and sample context")
    require("function ordinal(n)" in players and "ordinal(r.pct)+' percentile" in players,
            "players.html: percentile ordinals use correct English suffixes")

    match = pages["match.html"]
    require("activeVizs:['progressive']" in match,
            "match.html: first match view defaults to the lower-density progressive-pass map")
    require("const dense=!S.selPlayer&&evts.length>60" in match and
            ".slice(0,36):evts" in match and
            "36 largest advances shown" in match,
            "match.html: dense progressive team views cap observed pass vectors")
    require("dense=!S.selPlayer&&evts.length>250" in match and
            "dense team view" in match,
            "match.html: dense all-pass maps fade context and explain how to refine it")
    require("sbAll('v_match_events'" in match and
            "marker area = fitted xG" in match and
            "15*Math.sqrt(xg)" in match and
            "uniform marker size" not in match,
            "match.html: shot area uses real fitted xG rather than a distance proxy")
    require(",failed=color===PASS_FAIL" in match and "ctx.setLineDash([])" in match and
            "ctx.moveTo(p2.cx-r,p2.cy-r)" in match and
            "Incomplete · dashed" in players,
            "player and match pass maps distinguish failure without colour alone")
    require("for(const viz of vizOrder())" in match and
            "if(S.activeVizs.length>=S.plotSlots)break" in match,
            "match.html: plot-count controls fill the requested number of slots")
    require(".pitch-area{flex:0 0 auto;display:grid;grid-template-columns:repeat(2,minmax(0,1fr))" in match and
            '.pitch-area[data-count="1"]{grid-template-columns:minmax(0,820px)}' in match and
            ".narrow .pitch-area{grid-template-columns:minmax(0,1fr)}" in match,
            "match.html: plot slots share a two-column grid that collapses to one when narrow")
    require("legendEl.innerHTML=items.map" in match and
            "Draw compact legend ON canvas" not in match,
            "match.html: defensive action legend stays outside the pitch")
    require('<label for="slotSel\'+i+\'">Slot ' in match and
            '<select id="slotSel\'+i+\'" class="slot-sel' in match and
            "btn.setAttribute('role','button')" not in match,
            "match.html: visualization choice is a labelled native select per plot slot")

    teams = pages["teams.html"]
    require("function shotOutcomeLegend(counts,forTeam)" in teams and
            "shotOutcomeLegend({goal:g" in teams and "class=\"shot-key\"" in teams,
            "teams.html: shot outcome legend demonstrates each plotted glyph")
    require('<span class="fs-label">Relationship</span>' in teams and
            "eligible teams · raw values · dashed guides are displayed-sample medians" in teams,
            "teams.html: league scatter states the relationship and measurement context")
    require("const xmin=x0>=0?Math.max(0,x0-px):x0-px" in teams and
            "const ymin=y0>=0?Math.max(0,y0-py):y0-py" in teams,
            "teams.html: nonnegative scatter metrics cannot gain negative padding")
    require("const labelled={}" in teams and "if(labelled[p.team])" in teams and
            "hover any dot for exact values" in teams,
            "teams.html: league scatter labels only selection and structural extremes")
    require("LM.x==='ppda'&&LM.y==='field_tilt'" in teams and
            "Quadrants are named only for this defensible pairing" in teams,
            "teams.html: style quadrants are conditional and not quality claims")
    require("function mapSample(items,limit)" in teams and
            "mapSample(ps,1200)" in teams and "mapSample(rows,1800)" in teams and
            "evenly sampled from the returned population" in teams,
            "teams.html: season event drill-downs cap SVG density and disclose sampling")
    require("function passOutcomeLegend(items,successColor,successLabel)" in teams and
            "Incomplete · dashed" in teams and
            "color===TPAL.fail?' stroke-dasharray" in teams,
            "teams.html: pass outcome counts and failure dash do not rely on colour")
    require("function mapBtn(label,on,code){return '<button type=\"button\" aria-pressed=\"'+on+'\"" in teams and
            "mapBtn(m.l,MP.kind===m.k" in teams and
            "mapBtn('Pattern',MP.mode==='pattern'" in teams and
            "aria-pressed=\"'+(!off[l.k])+'\"" in players and
            ":focus-visible{outline:2px solid var(--accent)" in theme_css,
            "player and team plot toggles expose pressed state and focus")
    require("clone=card.cloneNode(true)" in teams and
            "clone.classList.remove('narrow')" in teams and
            "window.FutScoutExports" in teams and shared_pdf,
            "teams.html: exports capture a full-width clone and compress PDFs")
    require(".narrow .tm-rank{grid-template-columns:minmax(0,1fr)}" in teams,
            "teams.html: rankings stack to one column when narrow")

    if failures:
        print(f"\n{len(failures)} dashboard contract check(s) failed.")
        return 1
    print("\nAll dashboard data contracts passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
