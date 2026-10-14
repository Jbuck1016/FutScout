# Feature definitions, availability and rights — 14 October 2026

Follow-up supersedes the xG/xT availability and legacy phase assumptions below: [local reconstruction, seven comparisons and exact remaining gaps](../soccer_local_features_20261014/README.md). The v1 snapshot box-pass values reconcile to all-phase completed passes; the SQL open-play predicate did not prove the stored flags were correct. The earlier findings below are retained as checkpoint history.

This audit concerns the existing private local soccer data and offline research. It does not certify provider licensing or the current production database. No external provider-key calls, purchases, export uploads or database changes were made.

## Metric contract

| Feature | Audited meaning | Action in this branch |
|---|---|---|
| Elo | Initial 1500, K=20, +55 home advantage; goal-margin-scaled changes after games | Reproduced exactly; historical reconstruction is not a frozen Thursday slate |
| Rest | Calendar days since the last covered same-league match, clipped 0–30 for the model | Preserved; cup/international workload is absent |
| Shots / allowed | Event shot flags aggregated per team-match; rolling 3/5/10 means of prior matches | Preserved |
| Field tilt | 100 × own final-third touch proxies / both teams' final-third touch proxies; not possession time or passes | Preserved; zero denominator is missing |
| `box_entries_pass` | Successful open-play passes ending at x≥83, 21≤y≤79; no requirement that the pass started outside | Explanation corrected to completed box passes; data and field name not silently redefined |
| True pass entry | Same completion/end-location rules plus known origin outside the box | Separate tested predicate added; no historical values fabricated or backfilled |
| PPDA | Opponent passes with x<60 divided by own actions at x>40 of types Tackle, Interception, BallRecovery, BlockedPass, Challenge; not a universal provider PPDA contract | Available five-match means tested; log1p for residual adjustment. Historical mean of ratios is not ratio of summed numerators/denominators |
| Progressive passes | Successful passes meeting the repository's x-gain thresholds: 30 in own half, 15 crossing halfway, 10 entirely in opposing half | Available five-match means tested; log1p for residual adjustment |
| Defensive height | Mean x of the same broad defensive-action set, on 0–100 coordinates | Available five-match means tested; not a tracking-derived defensive-line position |
| Opponent adjustment | Training-only ridge residual of a lagged five-match metric conditional on prior opponents' pre-game Elo, own Elo, league, past home-match share and lagged shooting | Implemented and tested; explicitly not an event-level adjustment or causal estimate |

Primary local definitions: `supabase/migrations/20260903193000_ml_historical_features_v1.sql`, especially event aggregation and strictly prior-date rolling windows; `pipeline/generated/ml_feature_schema_v2_observation_functions.sql`; `pipeline/train_match_baselines.py`.

All three tested advanced metrics have the same availability pattern: home-side nonmissing rows 1703/1751, 1745/1752, 1749/1752; away-side 1703/1751, 1745/1752, 1746/1752. Missingness remains missing, with medians and indicators fitted on training data. Cold starts and promoted teams retain limited same-league history; the data do not supply their lower-league strength.

## Gaps that need real evidence or data

| Gap | Evidence found | Next concrete input or work |
|---|---|---|
| Historical xG | Prior September/October audits and point-in-time historical xG SQL exist. An October reconciliation reports 45,766 / 43,665 / 44,049 shots with no recomputation mismatch. This is saved audit evidence, not a fresh verification | Export complete versioned v2 observations/features and per-row lineage locally, including shot-model version and training cutoff. Reconcile IDs/coverage with this snapshot before a new experiment |
| xG model semantics | Initial migration fits empirical distance/angle/header/big-chance bins with shrinkage; later local SQL estimates historical bins from strictly earlier match dates with a fixed prior | Do not substitute the all-data live xG model in historical evaluation. Preserve the prior-date fit and verify availability of big-chance annotations; this is not an externally validated provider xG |
| xT | Existing static 12×8 lookup grid and sequence-based aggregation; prior v2 coverage/experiments exist | Need complete local rows, sequence reconstruction version and grid provenance/validation. Do not describe the hard-coded grid as a newly trained threat model |
| Corrected pass entries | Current aggregate includes within-box completions | Need raw origin/end coordinates for all historical events, new schema/version, full rebuild and retraining. Do not alter the meaning under the old feature name |
| PPDA aggregation | Rolling snapshot lacks component numerators and denominators | Retain per-match pass/action counts in the next export to permit opportunity-weighted aggregation |
| Injuries, lineups, workload | No comprehensive timestamped local history in this training snapshot | Require actual publication timestamps and coverage before claiming pre-match availability. Same-day final lineups cannot enter a Thursday forecast |
| Untouched evaluation | 2024/25 and 2025/26 already reused many times | Reserve genuinely future forecasts; no historical season is relabeled untouched. The new protocol is not a job installation |
| Market comparison | Earlier report used closing odds and admitted information-set differences | Capture prices that were available at the exact forecast cutoff, track margin/coverage and matched fixtures. No historical closing odds used in this run |
| Production readiness | 12 October audit documents an abandoned fixture, duplicate identity and failed verified rebuild | This offline run does not repair or certify the live feed. Resolve those incidents in a separate governed change before live integration |

## Rights and source restrictions

- Existing source: project-built local WhoScored/Opta-derived snapshots, already present on the PC. The inspected repository/audit files did not establish a written API, training or redistribution grant. Work here is confined to the user's existing private offline dataset; no clearance for new collection, commercial use or model/data redistribution is inferred. Provider rights evidence remains pending.
- [Football-data.co.uk data page](https://www.football-data.co.uk/data.php), checked 14 October 2026, restricts commercial/data-training use with automated tools. No files from that source were loaded, scraped, joined or used as training/calibration inputs in this run. Earlier benchmark numbers are not treated as licensed new training data.
- Wyscout subscription access is not evidence of API, export, redistribution or model-training rights. No Wyscout calls or assumptions were made.
- No FBref advanced feed was assumed available and no new paid source was proposed or purchased.
- WhoScored's terms URL could not be retrieved with the web tool; that is an unresolved rights check, not permission and not a tool approval denial.

## Method references

- [Dixon and Coles (1997), original paper](https://www.jstor.org/stable/2986290): motivation for low-score dependence; historical betting claims are not evidence about this model.
- [scikit-learn PoissonRegressor](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.PoissonRegressor.html): implemented estimator, L2 penalty and sample weights. This run used installed scikit-learn 1.6.1, recorded in the artifact manifest.
- Existing local synthesis `docs/MODEL_RESEARCH_SYNTHESIS_2026-09-22.md` in the backend checkout documents prior feature experiments, repeated test-season use, closing-market comparison limits and sparse genuine frozen evidence. It was read, not changed.

The open gaps above did not prevent the completed offline baseline reproduction, probability repair or available-feature experiments. Full historical xG/xT retraining and prospective promotion remain pending; neither was denied or attempted against a provider.

## Integration notes

The adaptive score distribution has more cells than the former 0–8 distribution. Payloads and all-remaining-fixture snapshots will therefore grow. The existing seven-day database persistence horizon is retained. Check full-schedule snapshot size and runtime before rollout. The simulator now imports the shared numpy/scipy helper; these dependencies are already in pipeline/requirements.txt, but a formerly standard-library-only simulator installation must install them.

This branch starts from committed backend code. The operational backend has additional uncommitted fixes. Integrate the scoped probability/label changes by reviewing hunks against that work; do not replace entire operational files. No existing frozen JSON, model registry entry or scheduled job has been changed. The persistence regression uses a mocked database only.
