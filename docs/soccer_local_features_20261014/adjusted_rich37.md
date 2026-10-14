# adjusted_rich37

Residualize those eight lagged features against own Elo, prior opponents' pre-match Elo, past home share, league, shots and shots allowed; Ridge alpha=100 on training rows only.

Research only. Two independent PoissonRegressor(alpha=1) goal models; training-only median imputation, missing indicators, scaling and league encoding. Rates retain the baseline clipping [0.05, 6]. No hyperparameter search or promotion.

| Test season | Train / test matches | Log loss | Brier | RPS | Delta vs baseline [95% interval] |
|---|---:|---:|---:|---:|---|
| 2425 | 1751 / 1714 | 0.98634896 | 0.58795426 | 0.20092189 | -0.00172031 [-0.00372009, +0.00018206] |
| 2526 | 3465 / 1751 | 0.99295153 | 0.59170464 | 0.20220329 | +0.00060762 [-0.00179366, +0.00287780] |

Paired circular blocks of four observed calendar weeks, 2,000 replicates, seed 20261014. Intervals are exploratory, not adjusted for multiple comparisons. Both seasons were reused before this experiment. Per-league metrics, reliability bins with Wilson intervals, goal errors, scoreline loss and discrete 90% goal-interval coverage are in the saved report.

Final research refit: 5216 matches. SHA-256: `e3e123e61cea9088616830935df6cc11ba5732b626cc32f754392cc5e850cdad`.
Artifact: `artifacts\soccer_research_rich_20261014\adjusted_rich37.pkl`. Export manifest: `455ff2532da0c37ca155404032ed1338702459a5a60f605deb5dea1387512afd`.

Cold-start values remain missing and are imputed using training data. Raw cache publication timestamps are unavailable: this proves prior-match chronology, not that every annotation was available at a particular historical forecast cutoff. The xG is an internal bin estimate and the xT is a static pass-value proxy, not independently validated provider models.

Numeric inputs:

- `context.opponent_rest_days`
- `context.team_rest_days`
- `elo_away`
- `elo_diff`
- `elo_home`
- `opponent.box_entries_pass_10`
- `opponent.box_entries_pass_3`
- `opponent.box_entries_pass_5`
- `opponent.field_tilt_pct_10`
- `opponent.field_tilt_pct_3`
- `opponent.field_tilt_pct_5`
- `opponent.shots_10`
- `opponent.shots_3`
- `opponent.shots_5`
- `opponent.shots_against_10`
- `opponent.shots_against_3`
- `opponent.shots_against_5`
- `team.box_entries_pass_10`
- `team.box_entries_pass_3`
- `team.box_entries_pass_5`
- `team.field_tilt_pct_10`
- `team.field_tilt_pct_3`
- `team.field_tilt_pct_5`
- `team.shots_10`
- `team.shots_3`
- `team.shots_5`
- `team.shots_against_10`
- `team.shots_against_3`
- `team.shots_against_5`
- `team.local.adjusted_npxg_for_5`
- `team.local.adjusted_npxg_against_5`
- `team.local.adjusted_pass_xt_net_difference_5`
- `team.local.adjusted_true_open_play_box_entries_5`
- `opponent.local.adjusted_npxg_for_5`
- `opponent.local.adjusted_npxg_against_5`
- `opponent.local.adjusted_pass_xt_net_difference_5`
- `opponent.local.adjusted_true_open_play_box_entries_5`
