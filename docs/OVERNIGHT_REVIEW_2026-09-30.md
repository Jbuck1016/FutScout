# FutScout overnight review

Started 2026-10-01 05:03 UTC. Production baseline 2b46b4f89314838953bc739ff536762071f9ef3e. No live model, frozen forecasts, authentication, scraper, operational schedule or database definitions changed.

## Progress

- [x] Historical shot-estimate prior-date formula and team-observation reconciliation; descriptive prequential calibration measured. Further provenance limitations below.
- [x] Score-state/time-window match review implemented, tested and deployed.
- [x] Expanded raw-source identity sample and player population discrepancy traced; wording fix deployed.
- [x] Representative browser/export regression and fixes (explicit sample below); production smoke passed.
- [x] Bounded sequence-similarity benchmark and optimization proposal (deployment requires separate database-change approval).

## 1. Historical xG

Read-only queries used 10–12 second statement timeouts; no write functions invoked.

- Inspected deployed `ml_score_historical_shot_xg`. It aggregates daily shot bins and uses a window ending **one date before the target date**, fixed prior 2 goals / 20 shots, with penalties fixed at .76. Same-day outcomes and later dates do not enter an estimate.
- Independently recomputed every stored value: 45,766 shots in 2324; 43,665 in 2425; 44,049 in 2526. **133,480 checked, zero missing, zero mismatches.** Version: `asof_bin_v1_prior20_base010`.
- Reconciled non-penalty shot sums to schema-v2 team observations: 3,502 + 3,504 + 3,504 = **10,510 team-match rows**, zero mismatches, maximum difference 0.000000.
- Important join lesson: shot rows retain source names (Man City, Man Utd); observations use canonical names (Manchester City, Manchester United). An initial name-only diagnostic falsely flagged missing groups. Repeating through `ml_match_team_map.source_team → team` reconciled every total. No data correction was needed.
- Calibration is **prequential**, allowing earlier-season dates to inform later dates, not a model fixed before a full holdout season. Reported Brier and reliability are descriptive performance of those saved estimates, not newly fitted results or proof of predictive superiority.
- 25/26 non-penalty xG overestimates Serie A totals by approximately 7.2% (877.709 vs 819 goals); Bundesliga underestimates by approximately 3.0% (857.089 vs 884). Aggregate agreement does not guarantee every chance band is calibrated: 25/26 p=.4–.5 band predicts .419901 vs .370871 observed (666 shots), and p=.5–.6 predicts .556768 vs .518480 (974 shots). No recalibration applied.
- This excludes future **goal outcomes in the bin fit**, not all possible provenance leakage. Raw provider qualifiers such as BigChance were archived retrospectively; their original publication/revision timestamps are not established. Date-based exclusion is conservative within a day. Current live `mv_shot_xg` has a different full-pool refit and must not replace these historical features.

Evidence JSON files under `artifacts/model_reports/`: `overnight_historical_xg_recompute.json`, `overnight_historical_xg_observation_reconciliation.json`, `overnight_historical_xg_calibration.json`, `overnight_historical_xg_reliability.json`.

## Resume notes

Repo has extensive pre-existing dirty work; preserve it. Turn-scoped write permission was granted. No new background jobs launched. No deployment yet for this overnight task. Read relevant skill files before the next phase.

Sequence function is `public.similar_sequences(text,integer)` (not find_similar_sequences). Inspected definition: Euclidean distance over 14 standardized dimensions from `public.seq_fz`, excludes same game, sorts by distance, 8-second function timeout. Next inspect seq_fz view/materialization and indexes, choose actual sample IDs, then benchmark with bounded read-only EXPLAIN ANALYZE. No DDL allowed without approval.

## 5. Sequence-similarity benchmark completed

`seq_fz` is a materialized view, approximately 110,860 rows, with a unique seq_uid index and a team index. Coordinates/features are standardized within league; the search currently compares these league-relative shapes across leagues. It is not a raw-coordinate-only similarity metric.

Three actual seeds: 1983549-73 (Premier League), 1995397-92 (Bundesliga), 1980894-238 (Serie A). Each query used an 8-second timeout, read-only transaction, 12 neighbours, EXPLAIN ANALYZE BUFFERS. One execution per variant/seed; not a p95 or cold-cache benchmark.

| Seed | Current ms | Double-cast rewrite ms | Exact formula, top-N first ms | Neighbour/distance differences |
|---|---:|---:|---:|---:|
| 1983549-73 | 1552.875 | 2449.241 | 1283.503 | 0 |
| 1995397-92 | 1481.496 | 2440.729 | 1253.675 | 0 |
| 1980894-238 | 1536.016 | 2477.640 | 1292.526 | 0 |

Recommendation: keep the exact distance expression, perform ORDER BY distance LIMIT p_n in the inner query, then apply row_number only to those nearest rows. This avoids ranking the full candidate pool. Observed improvement approximately 15–17%; current function spills approximately 11,055–11,059 temporary written blocks. Reject the double-cast rewrite, which is slower here despite avoiding spills. Do not increase timeout as the primary optimization. Before migration approval, add explicit tie-order semantics and test seeds with tied distances; current API has no deterministic tie break. Applying the function replacement is database DDL and was **not authorized by this overnight scope**, so no production replacement was made. Evidence: artifacts/model_reports/overnight_sequence_benchmark.json.

Next heartbeat: implement item 2 score-state review, then expand source sampling/player discrepancy and browser tests. Items 1 and 5 do not need repeating. No long-running job is left active.

## 2. Score-state review implemented (second heartbeat)

`pipeline/match_review_states.py` validates raw final score, period end markers, unique event IDs, shot joins and source checksum (in builder). Uses period-first chronology and first-half added time before second-half kickoff; excludes halftime, includes stoppages (clock exposure, not ball-in-play). Goals belong to the pre-goal state; own goals credit the opposing side. Same-second events preserve provider ordering, with a shot/goal ambiguity warning. No arbitrary inferred extra-time support: this worked review covers first/second half only.

Full match exposure 98m19s; level 30m32s: Brighton 4 shots/.203 xG, Arsenal 1/.025. Brighton leading/Arsenal trailing 67m47s: 13/1.512 versus 10/1.067. No Arsenal-leading exposure, shown as unavailable rather than a zero rate. Full/half/first30/last30 elapsed windows are available. Rates use each selected common interval. Frozen forecast unchanged. Corrected existing xG timeline from overlapping display-clock minutes to elapsed period-aware minutes, retaining all added time.

`python pipeline/tools/check_match_review_states.py` passed synthetic own-goal, ordering, added-time, zero-exposure, half-open boundary and missing/end-score failure cases. `python pipeline/build_match_review.py` passed actual archive checksum and all28shot/3goal reconciliation. Both JS files pass `node --check`. Local browser verified full/level/leading/empty cases. Actual PNG downloaded and visually inspected, including selected context and provenance footer; theme/mobile/PDF tests remain underway. New UI uses existing editorial typography/colours per frontend-design skill, not a new visual system.

## 3. Additional source identity and population counts

`python pipeline/audit_overnight_identity.py`: 5,996 additional events across four fixtures passed exact event-ID population, team/player/event IDs (database string IDs normalized to strings), player names, source checksum, fixture date/names/score. Samples: fd-558608 Sassuolo–Juventus (1,573), fd-559692 Paris FC–Lyon (1,584), fd-564697 Getafe–Malaga (1,429), fd-565811 Frankfurt–Freiburg (1,410). With the prior Brighton sample: 7,491 events in five fixtures, one per modeled league, NOT comprehensive historical coverage. Raw source verification, not independent real-world confirmation. Evidence: `overnight_identity_db_samples.json` (local saved input), `overnight_identity_audit.json` (aggregate result). No identities rewritten.

The 2,916/2,915 discrepancy is a **definition/label error**, not a missing played match established by this check. Inspected `mv_site_summary`, `mv_player_league`, `mv_player_season`, `mv_player_minutes` definitions. First metric counts all event-player IDs without is_touch filtering. Second counts minutes-view players, explicitly excluding unused Subs. Third is minutes-population EXCEPT events, not unused substitutes. Bounded materialized-view comparison found one extra event player: **376150 Luis Barraza**, MLS, one event; game1953005, event2975677699, typeCard, is_touch=false, minute99, Inter Miami. Lineup positionSub, zero mv_player_minutes rows. Corrected guide wording, preserving underlying data/legacy API keys. Full live-event population queries twice hit8s timeout; switched to the materialized population (2,916 vs2,915), then the bounded ID lookup. No timeout escalation/unbounded scan. Current stored summary refreshed2026-09-30T03:57:04Z. Local MLS raw path was not available, so the Barraza explanation is DB lineage/ID evidence, not raw-archive verification.

## Current resume point

Items1,2,3,5 investigated; item4 mobile/dark/PDF/bespoke export verification and selective remote integration remain. New files: match_review_states.py, check_match_review_states.py, match-review-states.js, audit_overnight_identity.py; changes to builder/review data/JS/HTML and guide. Preserve unrelated edits. Test server started in this heartbeat on127.0.0.1:8765 (exec session10846); check command line before starting another. No deployment yet. Browser tab6 local review is temporary. Actual PNG: C:\Users\jbuck\Downloads\brighton-arsenal-match-review-what-changed-after-the-lead.png.

## 4. Browser and download regression sample

- Local worked review desktop/light: all-state/level/home-leading/away-leading-empty filters, actual panel PNG, inspected downloaded pixels. Selection/provenance footer retained.
- Local worked review390x844/dark: second-half+added-time long option, leading/empty result; table/control wrapping and contrast visually checked. Actual PDF downloaded, one-page A4landscape, rendered with pdftoppm and inspected. No clipped text in this sample. Poppler warned about unavailable Symbol/ArialUnicode display fonts; raster content rendered correctly.
- Production players332325 (Declan Rice): Passing category and category pizza exercised. Verified defect: blanket per90 suffix on pass percentages (also applies to durations/per-shot ratios). Local fix only emits per90 for defined _90 metric keys. `check_player_metric_units.js` passed rates vs percentages/durations/ratios; inline scripts parse.
- Actual local pizza PNG downloaded and inspected: revealed omitted player identity and low-contrast blue side values on dark background. Added explicit player/team/league/role header inside exported card and switched numeric text to theme foreground (family colour remains in wedge/dot). Final re-export validation pending at this checkpoint.
- Final pizza re-export `player-fingerprints-passing-profile (3).png` visually verified: player/cohort header included, white dark-theme numbers, correct percentages vs per90. Model artifact/forecast-ledger/provenance classification regressions also passed; joblib emitted a harmless missing-WMIC physical-core warning and used logical cores.
- Scope is representative, NOT every chart/view/browser combination: no claim that rank/scatter/writing-lab bespoke exports all passed this overnight run. Prior synthetic long-table/canvas multipage checks are in SIX_REVIEW_FIXES. No shared exporter code changed this run.

## Approval boundary

Only remaining proposed database change is replacing similar_sequences with exact-expression topN-before-window version, after tied-distance order verification; requires explicit approval for that named function replacement. No rebuild, refresh, new index, model adjustment or schedule change is included. xG recalibration is a research suggestion only, not performed or necessary to deploy these UI fixes.

## Final delivery

Application/evidence commit **be04f7f6ade51d7338f0070855a835f40aaa0002**, parent verified production baseline2b46b4f89314838953bc739ff536762071f9ef3e. Built a selective GitHub tree with18 scoped files, not the dirty local checkout. Remote reviewed file differences match this work; existing review payload compared identical after removing the added score_states field. No raw event sample dump published.

Vercel **READY / production**, deployment **dpl_EXcQz9sr28pnzsEmMinBGALouSBr**, URL https://arsenal-analytics-ai7d5o217-jbuck1016s-projects.vercel.app ; live https://futscout.xyz/match-review.html?game=fd-560586&v=be04f7f . Static HTML/JS Git integration. Production browser confirmed all five windows, level-state30m32s/4vs1shots, and no captured console errors on review. Production guide confirmed corrected2916/2915 populations and Barraza explanation. Runtime log/drain audit was not performed; do not interpret page-console results as complete infrastructure observability.

All five requested workstreams are complete at the stated audit/sample scope. DB optimization is proposal-only, approval required; no other workstream waits on that approval. No live model, frozen predictions, auth, scraper, schedules, DB definitions/rebuilds or paid API credits changed. Local QA server is to be stopped before turn end; heartbeat to be deleted after final verification. Historical/model methodology followed sports-analytics guidance; frontend-design preserved the existing editorial design, PDF skill guided actual rendered export inspection, and deployment skill guided selective integration/READY verification.

Final cleanup confirmed: local QA server10846 stopped; temporary browser tabs closed and viewport reset. Production player pizza also confirmed player/cohort header and89.9% without per90. Overnight heartbeat deleted successfully. Earlier resume/checkpoint notes are historical, not outstanding work.
