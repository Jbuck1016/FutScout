# Model card: decay365_baseline29

Baseline with a fixed 365-day exponential half-life on training-match weights; no half-life search.

**Status: offline research only. No model promoted, registered, merged or deployed.**

## Intended use and population

Pre-match home/draw/away and scoreline forecasts for the five covered European domestic leagues. One row per match, with home/away goals as training targets. This is a reconstruction using prior completed match dates, not a genuinely frozen Thursday slate; publication delays and provider revisions cannot be reconstructed from this export.

Final fit: 5,255 matches, 2023-08-11 through 2026-05-24. Earlier seasons train each fold; all candidates use the identical 1,752 fixtures per evaluation season. These seasons were already reused by earlier research and are development evaluations.

## Training and feature contract

Two scikit-learn PoissonRegressor(alpha=1, max_iter=2000) pipelines. Numeric medians, missingness indicators, standardization and league one-hot encoding fit on training rows only. Rest is clipped to 0–30 days; predicted goal rates are clipped to 0.05–6.0. Elo starts at 1500 with K=20 and home adjustment 55, updating after prior matches. Five-match schedule context excludes the target date and uses opponents’ ratings before those historical matches. Rolling snapshot features may use fewer than five games at cold starts; missing values remain missing until training-only imputation.

The field named box_entries_pass means completed open-play passes ending in the box, including within-box passes. Field tilt is share of final-third touch proxies; PPDA uses this repository’s broad defensive-action set. Metric names must not be treated as provider-standard definitions.

## Results

| Evaluation season | Log loss | Brier (sum over 3 classes) | RPS | Top-label ECE | Δ log loss vs baseline [95% interval] |
|---|---:|---:|---:|---:|---|
| 2425 | 0.986927 | 0.588040 | 0.201104 | 0.019882 | -0.000311 [-0.000657, +0.000035] |
| 2526 | 0.993646 | 0.592109 | 0.202396 | 0.010893 | +0.001004 [+0.000190, +0.001817] |

Lower proper scores are better. Paired uncertainty uses 2,000 circular moving-block draws of four observed calendar weeks. Intervals are exploratory and not adjusted for trying multiple candidates. Full JSON includes per-league scores, classwise reliability bins with counts and descriptive Wilson intervals, scoreline log loss, goal MAE, and 90% discrete goal interval coverage/width. Sparse bins and only two season transitions limit inference.

## Decision and deployment limits

Retain the existing model. No new challenger improves both seasons. All new feature/decay/DC variants worsen 2025/26. Do not select a winner from one favorable metric, league or fold. DC rho changes sign across folds and reaches its positive bound in the second fold, so this result does not establish that all Dixon–Coles formulations fail.

The research artifact requires the offline research inference helper and its feature contract; it is deliberately not a drop-in production model_artifact bundle. Advanced adjustments need an auditable live schedule/history feature builder and identical cutoff before any shadow rollout. Genuine forecasts must be frozen prospectively.

No odds entered training, adjustment, calibration or selection. Closing odds from earlier reports are not a fair same-time Thursday comparison. No profit claim follows from these scores.

## Artifact and reproducibility

- Local artifact: `artifacts/soccer_research_20261014/decay365_baseline29.pkl`
- SHA256: `1edb1485465ed7405add197f8850335623616fd00b1ea2ead69606924b586c63`
- Snapshot SHA256: `29d0a2ad6db8a84c24eb1cb3f17e733cb53778f4f46a9a88b590696c43282978`
- Full-data rho: `0.0`
- Reload check: 143 historical rows, passed.
- Environment and code hashes: local `report.json` and `validation.json`.

## Numeric feature list

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
