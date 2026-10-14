# true_entries29

Replace six legacy box-pass inputs with genuinely open-play outside-to-inside entries. This changes both the phase contract and the origin test.

Research only. Two independent PoissonRegressor(alpha=1) goal models; training-only median imputation, missing indicators, scaling and league encoding. Rates retain the baseline clipping [0.05, 6]. No hyperparameter search or promotion.

| Test season | Train / test matches | Log loss | Brier | RPS | Delta vs baseline [95% interval] |
|---|---:|---:|---:|---:|---|
| 2425 | 1751 / 1714 | 0.98776421 | 0.58873753 | 0.20125564 | -0.00030506 [-0.00157713, +0.00117680] |
| 2526 | 3465 / 1751 | 0.99309076 | 0.59177964 | 0.20230561 | +0.00074684 [-0.00051620, +0.00209990] |

Paired circular blocks of four observed calendar weeks, 2,000 replicates, seed 20261014. Intervals are exploratory, not adjusted for multiple comparisons. Both seasons were reused before this experiment. Per-league metrics, reliability bins with Wilson intervals, goal errors, scoreline loss and discrete 90% goal-interval coverage are in the saved report.

Final research refit: 5216 matches. SHA-256: `639ea25d757db6274435a8d0c9262f3e5b7a29d0ee9eee8b461984141b95779d`.
Artifact: `artifacts\soccer_research_rich_20261014\true_entries29.pkl`. Export manifest: `455ff2532da0c37ca155404032ed1338702459a5a60f605deb5dea1387512afd`.

Cold-start values remain missing and are imputed using training data. Raw cache publication timestamps are unavailable: this proves prior-match chronology, not that every annotation was available at a particular historical forecast cutoff. The xG is an internal bin estimate and the xT is a static pass-value proxy, not independently validated provider models.

Numeric inputs:

- `context.opponent_rest_days`
- `context.team_rest_days`
- `elo_away`
- `elo_diff`
- `elo_home`
- `opponent.field_tilt_pct_10`
- `opponent.field_tilt_pct_3`
- `opponent.field_tilt_pct_5`
- `opponent.shots_10`
- `opponent.shots_3`
- `opponent.shots_5`
- `opponent.shots_against_10`
- `opponent.shots_against_3`
- `opponent.shots_against_5`
- `team.field_tilt_pct_10`
- `team.field_tilt_pct_3`
- `team.field_tilt_pct_5`
- `team.shots_10`
- `team.shots_3`
- `team.shots_5`
- `team.shots_against_10`
- `team.shots_against_3`
- `team.shots_against_5`
- `team.local.true_open_play_box_entries_3`
- `team.local.true_open_play_box_entries_5`
- `team.local.true_open_play_box_entries_10`
- `opponent.local.true_open_play_box_entries_3`
- `opponent.local.true_open_play_box_entries_5`
- `opponent.local.true_open_play_box_entries_10`
