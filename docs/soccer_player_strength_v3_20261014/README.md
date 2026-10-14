# Independent-review repairs: player layer v3

All three confirmed findings against commit `8f3b410` are repaired in the isolated research branch. The v3 export and four fixed comparisons are complete. No model is promoted; no merge, deployment, database access, provider call or operational checkout change occurred.

The review is `C:/Users/jbuck/Documents/Codex/2026-10-13/task-4/SOCCER-INDEPENDENT-REVIEW-8f3b410.md`. Its probability/label correctness verdict was scoped PASS, while player allocation and scenario behavior required changes.

## Exact repairs

1. Preserve equivalent-90 exposure. The weighted mixture averages observed minutes without scaling depleted teams upward to 990. Named allocations are finite and at most 90. Role sums are reduced only when necessary to fit 90 goalkeeper and 900 outfield minutes. Missing exposure is recorded in separate goalkeeper/outfield unknown-replacement pools, which complete the 990 total. No extra minutes are silently assigned to a remaining player. The recent reference uses the same feasible allocation rules.
2. Maintain a prior-only membership ledger. After all predictions on each calendar date, record each player's last observed club, source game and date. An old-club expected allocation is removed once a strictly earlier appearance establishes another club. Conflicting same-date clubs remain ambiguous and ineligible. Removed minutes move to the appropriate unknown pool. The historical reference retains past participation so a known departure can still create a strength change. This is observed-appearance evidence, not a claim of complete registration or transaction history.
3. Validate scenario budgets. Reject NaN/infinite/negative replacement or player minutes, named allocations above 90, invalid totals, impossible role budgets and unclassified named roles. Replacement role pools reconcile explicitly; named players require prior membership evidence for the requested club and exact saved cutoff. Unknown replacements have zero excess rating. The scenario API requires a v3 plan, rejecting old infeasible plans.

The allocation module was additionally hardened to reject invalid shares at its own boundary. An exact replay with the final source reproduced every saved v3 feature and plan; the export preserves its original code snapshot and the replay records both hashes. This final guard does not change any valid exported data.

## Full-population verification

- All **10,510 expected plans** and references pass finite individual, team and role budget checks. Maximum expected individual exposure is **90.0**; over-90 allocations: **0**.
- Expected allocations to a player whose latest prior club is different: **0**. The membership rule removes allocations in **670 plans**. **3,090 plans** contain an explicit replacement deficit, including cold starts.
- The Rennes reproduction (`1911289`) now gives Anthony Rouault 90 minutes and Brice Samba 89.7504, versus 100.9071 and 100.6574. Bournemouth (`1903294`) no longer expects Antoine Semenyo after the already-observed Manchester City appearance on 17 Jan 2026; his 89.2902 old-club minutes become replacement exposure.
- Source observations remain 10,502 complete sides, eight missing sides, 162,592 appearances and 4,333 players. Reused observation bytes are hash-verified; no redundant provider/source collection occurred. Readiness is 10,046 of 10,510 team targets; the existing event-quality comparison population stays 5,216 fixtures.
- Twelve player regression/property tests pass, including 300 random mixture cases, depletion, individual bounds, role budgets, NaN/infinity, transfer chronology, ambiguous same-date clubs, unchanged same-date forecasts, target-data mutation isolation, stale/missing fallback and hypothetical replacement accounting.
- Independently reloaded eight fold models and reconciled all **13,860 held-out prediction rows**, fallback masks and proper scores. Four final model hashes were checked. **54 earlier evidence files** are byte-identical, including v2 exports, models, predictions and earlier advanced/baseline outputs.

## Corrected exploratory comparisons

Lower H/D/A log loss is better. Same chronological training/test sizes: 1,751/1,714 for 2024/25, and 3,465/1,751 for 2025/26. Same candidate set, alpha, imputation, rating prior, usage weights and bootstrap protocol; no test-driven retuning. Every non-baseline candidate still falls back on 82 and 57 evaluated fixtures respectively.

| Candidate | 2024/25 v2 | 2024/25 repaired v3 | 2025/26 v2 | 2025/26 repaired v3 |
|---|---:|---:|---:|---:|
| [baseline29](baseline29.md) | 0.988069270 | 0.988069270 | 0.992343917 | 0.992343917 |
| [usage33](usage33.md) | 0.987902289 | 0.987871670 | 0.992826637 | 0.992939172 |
| [ratings31](ratings31.md) | 0.990747615 | 0.990544239 | 0.992815570 | 0.992109817 |
| [ratings_usage35](ratings_usage35.md) | 0.990549668 | 0.990259297 | 0.993271732 | 0.992590432 |

Ratings31 now slightly improves the 2025/26 point estimate (delta -0.000234101, interval [-0.000864313, +0.000220922]), while still worsening 2024/25 (+0.002474969, interval [+0.000271338, +0.004412987]). No candidate improves both seasons. These remain reused historical evaluations, not an untouched test or promotion evidence.

The hypothetical absence problem also remains. In the same Arsenal-Nottingham Forest example, substituting role-replacement exposure for Rice raises predicted home-win probability from 64.6026% to 66.3295%. The own home-player coefficient remains negative (-0.25732 in the 2025/26 ratings31 fit). This is not an injury claim; it demonstrates that a corrected feasible input still does not establish causal player value. Do not deploy this proxy for absence adjustments.

## Offline persistence precision

The unchanged SQL schema stores goal rates as `numeric(7,4)`, headline H/D/A probabilities as `numeric(8,7)`, and score grids as JSONB. Full Python precision does not survive those scalar database columns. No migration or database round trip was attempted.

The documented tolerance contract is: local headline/grid agreement within 2e-12; stored headline versus full JSONB grid mass within 5.0002e-8 per outcome; rounded headline sum within 1.50001e-7 (the SQL constraint allows 1e-6). Decimal half-up emulation over 1,752 actual historical rate pairs gives maximum headline error 4.998925554e-08 and sum error 1.000000001e-07. Rebuilding a grid from four-decimal stored rates changes H/D/A by as much as 2.295627986e-05, so stored explicit score grids must be used when reproducing persisted forecasts. The simulator's existing normalized-headline alignment is retained and was exercised with emulated rounded columns.

These are offline numeric emulations, not certification of JSONB/PostgREST storage behavior. A real authorized database round trip remains pending before integration; no exact post-write equality is claimed.

## Offline payload and consumer capacity

Score dictionaries grow approximately 4.5x: this run's default JSON serialization measures 4,213,377 to 19,059,685 bytes (4.52x); the independent review's compact serialization measured 4.54x. Median support is 324 cells; maximum 729 on the historical rate sample. Serialization choice changes byte totals, not the growth concern.

The actual existing 17 Sep frozen snapshot has **1,549 remaining fixtures**. Replacing grids in memory expands the whole indented JSON from **9,608,649 to 26,207,914 bytes** (2.73x), or 7,550,739 bytes gzip. The original file is byte-identical afterward. No 2026/27 results were read or scored.

Its seven-day horizon contains **46 fixtures**; serialized row bodies are **510,359 bytes**, excluding model-run-ID overhead. The local path currently submits that slate in one upsert; no byte-budget batching is configured. The ledger fetches up to 1,000 rows with their grids per page. The inspected SQL has no JSONB cell/byte limit, and the static model-review dashboard omits score grids, but service response/request limits are not established by those facts.

Local grid construction took 0.292s, JSON serialization 0.327s, parsing 0.541s with 62,130,923 traced peak bytes, and actual simulator fixture preparation 3.187s with 108,977,280 traced peak bytes. Parsing/preparation timings include tracing overhead; this is one desktop run, not deployed end-to-end latency or a 10,000-simulation benchmark. DB storage/TOAST, transport compression and gateway capacity remain unverified. No capacity setting was silently changed.

## Deliverables and pending integration checks

- `artifacts/soccer_research_players_20261014_v3/`: new versioned feasible plans, replacement pools, membership evidence and feature rows.
- `artifacts/soccer_research_player_models_20261014_v3/`: protocol, eight fold models, four final models, predictions, metrics/calibration/uncertainty and validation.
- `artifacts/soccer_research_repair_20261014/`: old evidence hashes, exact replay/preservation proof, numeric/payload audit and updated probability/metric review patch.
- `pipeline/tools/verify_player_repair_evidence.py`, `validate_local_player_strength.py` and `audit_score_persistence_offline.py`: repeatable offline checks. Current scenario and experiment tools require v3; the v2 source/code snapshots and Git revision remain available for old evidence.

Remaining limitations are the existing missing source/usage records, historical publication vintages, injury/lineup and transaction timestamps, and unvalidated causal player impact. Future frozen evaluation remains reserved and unchanged. Before any integration, review only scoped hunks against the operational worktree, verify an authorized DB precision round trip and deployed payload limits, and keep research model selection separate from the already reviewed numerical probability repair. No action was denied or left with an uncertain write outcome.
