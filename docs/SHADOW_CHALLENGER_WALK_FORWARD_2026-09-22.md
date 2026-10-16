# Historical same-fixture model comparison — 22 September 2026

This is a **research comparison, not a promotion decision**. All five model recipes were refitted only on seasons before each evaluation season, then scored on the same 1,752 fixtures in 2024/25 and the same 1,752 fixtures in 2025/26. The original shadow artifact was not retrained, replaced, or activated. The `primary` row means its exact 29-input *recipe* refitted within each fold.

| Recipe | 2024/25 log loss | 2025/26 log loss | Pooled log loss | Pooled Brier |
| --- | ---: | ---: | ---: | ---: |
| Primary field tilt + box entries | 0.98724 | 0.99264 | 0.98994 | 0.58986 |
| Compact Elo/rest/shooting control | 0.98870 | 0.99273 | 0.99071 | 0.59057 |
| Compact xT | 0.98731 | 0.99252 | 0.98991 | 0.59003 |
| Box-entry sequences | 0.98726 | 0.99240 | 0.98983 | 0.58985 |
| Territory × Elo interactions | 0.98700 | 0.99223 | 0.98962 | 0.58985 |

Lower loss is better. The interaction recipe has the lowest pooled loss, but its paired difference against primary is only **−0.00033 log-loss units per match**; a calendar-week-block bootstrap 95% interval is **−0.00129 to +0.00066**. This interval includes zero. It beats primary by a small amount in each fold, but the result is not evidence of a durable win. The compact xT and box-sequence variants also barely separate from primary.

The league picture is not uniform. Across both holdouts, compact control beats primary in the Premier League (1.0125 versus 1.0181 log loss), while primary beats compact control in La Liga, Serie A, Bundesliga, and Ligue 1. Premier League within-season paired intervals still include zero. This is a lead for diagnosis, not a license to switch models by league.

The historical join yielded 1,751 training rows for 2023/24 and 1,752 each for 2024/25 and 2025/26, with unique game IDs. The fixture-level export has 3,504 unique test games and valid probability triples for each model. Independently recomputing log loss from that export reproduces all five pooled values. Only 13 and 9 test fixtures, respectively, had at least one missing model input before imputation; this is not evidence that xT is broadly absent from these historical feature snapshots.

Important limits:

- The exact candidate contracts had already been influenced by earlier experiments using these same two holdout seasons. Chronological refitting prevents *outcome training leakage*, but these are **not untouched model-selection holdouts**. The next genuine frozen live cohort is the independent test.
- Historical feature rows are pre-match rolling snapshots rather than archived Thursday inputs. The test can use results and team form revealed between Thursday and a later kickoff. It therefore does not establish Thursday-slate accuracy.
- Historical data has match dates but not assured kickoff instants in this joined frame. The comparison batches Elo updates by date so one same-day result cannot influence another fixture's pre-match rating. That is conservative but slightly different from the live kickoff-aware calculation.
- The compact xT and box-sequence candidates retain the shooting/control foundation; they are **not** genuine no-shots alternatives. A no-shots comparison remains separate research.

Reproduce with `python pipeline/evaluate_shadow_challenger_walk_forward.py`. The inspectable outputs are `artifacts/model_reports/shadow_challenger_walk_forward_20260922.json` and its same-name `.csv` fixture predictions. `python pipeline/tools/check_shadow_challenger_walk_forward.py` tests same-day Elo and feature-availability accounting. Neither command writes to Supabase or changes a model lifecycle state.
