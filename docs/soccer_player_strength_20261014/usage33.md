# usage33

Add prior-usage lineup churn and expected-player rating coverage for each side.

Research only. Individual inputs are shrunk retrospective provider performance ratings, not independently estimated causal player impact. The conditional link to home/away goal rates is learned from historical training seasons by two PoissonRegressor(alpha=1) models. League encoding, numeric scaling, median imputation and missing indicators are fitted on training rows only.

| Test season | Train/test | Log loss | Brier | RPS | Delta log loss [95% interval] | Fallback matches |
|---|---:|---:|---:|---:|---|---:|
| 2425 | 1751/1714 | 0.98790229 | 0.58892485 | 0.20134903 | -0.00016698 [-0.00101494, +0.00084876] | 82 |
| 2526 | 3465/1751 | 0.99282664 | 0.59158767 | 0.20220726 | +0.00048272 [-0.00053494, +0.00173707] | 57 |

Paired four-observed-week circular block bootstrap, 2,000 replicates, seed 20261014. Reused seasons, exploratory intervals without multiplicity adjustment. No tuning followed these scores. Per-league results, reliability/Wilson bins, goal errors, scoreline scores, discrete goal-interval coverage and learned coefficients are in report.json.

Every non-baseline candidate falls back to the separately fitted baseline if either team lacks reliable prior usage. The prediction gate uses no target-game participant data. Stable lineup ratings enter as a zero change from the recent team reference; no absolute player-strength sum is added on top of Elo. Historical lineup expectations remain an assumption, not a confirmed lineup.

Final refit: 5216 matches through 2026-05-24; SHA-256 `f38473d2264494e8d60774e053b529aa29de619b6f4ff8ee4ad0a4f7e8d4926c`.
Player export manifest: `91ee7a21d7cf86fa3421d1e3f4fa9fb2e59bf0b7c52432f21e7c11faab3aa82c`.
Final artifact `artifacts\soccer_research_player_models_20261014\usage33.pkl`; chronological fold artifacts are saved separately under `fold_models/`.

Decision: no promotion. See the [player-layer report](README.md) for negative coefficient/scenario diagnostics and exact missing source information.

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
- `team.player.usage_churn`
- `team.player.rating_coverage`
- `opponent.player.usage_churn`
- `opponent.player.rating_coverage`
