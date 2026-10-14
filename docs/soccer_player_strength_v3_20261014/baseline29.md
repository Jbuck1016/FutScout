# baseline29: repaired player features v3

Research only. Same two Poisson(alpha=1) estimators, candidate inputs, folds and train-only preprocessing as v2. Repairs change exposure allocation and eligibility, not tuned hyperparameters. Individual ratings remain shrunk historical provider performance proxies, not causal player impact.

| Test season | Train/test | Log loss | Brier | RPS | Delta vs control [95% interval] | Fallback |
|---|---:|---:|---:|---:|---|---:|
| 2425 | 1751/1714 | 0.988069270 | 0.589047338 | 0.201393991 | +0.000000000 [+0.000000000, +0.000000000] | 0 |
| 2526 | 3465/1751 | 0.992343917 | 0.591238652 | 0.202065586 | +0.000000000 [+0.000000000, +0.000000000] | 0 |

Intervals: paired four-observed-week circular blocks, 2,000 replicates, seed 20261014; reused seasons and no multiplicity adjustment. No candidate improves both seasons. All calibration bins, goal intervals, per-league scores and learned coefficients remain in report.json.

Expected named players have finite exposure in [0,90], goalkeeper/outfield budgets are 90/900, and deficits are explicit unknown replacement minutes. Latest strictly earlier observed club controls expectation; departed players remain only in the historical reference. Same-date observations update after all forecasts. Missing/stale/low-coverage cases use the exact baseline forecast.

Final research refit: 5216 matches through 2026-05-24. Artifact SHA-256 `6296acfdb9e5913f6b70aec736bad37db5f507f7e9f76d4e9bb8d786c735d87d`.
Player manifest SHA-256 `f8abdbdb24b0e926acec8d14c43bf3c0f5d6c4fcb9dac86dac5546712fdd6b1f`. Final artifact: `artifacts\soccer_research_player_models_20261014_v3\baseline29.pkl`.

Eight chronological fold artifacts are saved separately. Source publication vintages, transfer-registration timestamps and injury/lineup probabilities remain unavailable. See [repair report](README.md) for complete checks and the remaining wrong-direction hypothetical absence effect.

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
