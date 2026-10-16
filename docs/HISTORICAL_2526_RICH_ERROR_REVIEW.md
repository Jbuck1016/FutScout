# Why the richer candidates regressed in 2025/26

This is a fixture-level replay of the **2025/26 chronological holdout**, trained on 2023/24 and 2024/25. It reproduces the aggregate scores in `v2_feature_candidate_audit.json` and attributes each candidate's change in result log loss to the 1,752 held-out fixtures. Positive deltas are worse than the compact shooting control. The replay uses only pre-match rolling inputs; it does not change the shadow model.

## The cross-season problem is not one bad match

| League | Fixtures | Broad xT minus control | Broad rich attack minus control | Compact 5-match xT difference minus control |
| --- | ---: | ---: | ---: | ---: |
| Premier League | 380 | +0.0056 | +0.0128 | +0.0014 |
| La Liga | 380 | +0.0061 | +0.0123 | +0.0011 |
| Ligue 1 | 306 | -0.0085 | -0.0014 | -0.0024 |
| Bundesliga | 306 | +0.0017 | +0.0031 | -0.0008 |
| Serie A | 380 | +0.0010 | -0.0062 | -0.0008 |

The broad xT candidate improved 183 of 306 Ligue 1 fixtures, but worsened 201 of 380 Premier League and 199 of 380 La Liga fixtures. Broad rich attack worsened 212 Premier League and 206 La Liga fixtures, so this is a distributed loss, not solely one outlier. Their gains elsewhere do not transport consistently across leagues or from the 2024/25 holdout to 2025/26.

The broad rich candidate's extra Premier League loss is concentrated in **home wins**: summed fixture log-loss delta +8.92 on 162 home wins, versus -1.02 on draws and -3.03 on away wins. La Liga shows the same pattern (+7.91 home wins, -1.53 draws, -1.72 away wins). Its mean home-win probability was 0.413 in the Premier League versus 0.434 for control (actual rate 0.426), and 0.420 in La Liga versus 0.437 for control (actual rate 0.489). These are descriptive, league-level averages; they do not prove the rich inputs *caused* the underprediction. A league/home calibration or interaction test is warranted.

Examples of large broad-rich losses include Bournemouth 3–2 Liverpool (24 January 2026): the actual home-win probability fell from 0.25 under control to 0.17 under rich attack. For Real Sociedad 0–1 Getafe (22 April 2026), the actual away-win probability fell from 0.27 to 0.16. Conversely, rich attack improved other fixtures, and its Serie A aggregate was better. This is precisely why cherry-picked examples must not decide model selection.

## What this does and does not say

- xT, field tilt, and box entries contain useful signal. Broad xT won the 2024/25 holdout, and the compact tactical candidates were near parity in 2025/26. The evidence does **not** show shots are inherently superior.
- Adding many correlated tactical columns can change the goal equations and their calibration by league. Here the broad rich candidate shifted home-win probabilities downward in two leagues where it lost ground. We have not yet isolated whether the cause is collinearity, a league-specific relationship, a home-goal calibration issue, or a data-distribution shift.
- The compact xT candidate's latest-year change is tiny (+0.0014 Premier League, +0.0011 La Liga; small gains in three other leagues). The paired week-block bootstrap from the candidate audit does not establish a stable overall win. Do not promote it on this replay alone.

## Real frozen calls are a different test

The 17 September 2026 frozen shadow-weekend review scored 46 matches and lists four completed fixtures without a frozen call. Its Premier League and La Liga subsets contain only 9 and 11 scored matches, respectively. Only the registered shadow model had genuine frozen calls; tactical challengers did not. Therefore that review can identify current misses but **cannot** establish a live head-to-head winner between candidates. A valid next step is to freeze same-fixture probabilities for control, territory, compact xT, and rich challengers at the same Thursday timestamp, then score them only after outcomes resolve.

## Next controlled tests

1. On the same 2024/25 and 2025/26 chronological folds, test home-goal intercept recalibration and league-specific offsets **without** using holdout results to fit those offsets. Check log loss, goal MAE, calibration, and league deltas together.
2. Ablate correlated feature families, not arbitrary individual columns, and test tactical-by-shot and tactical-by-Elo interactions. Retain the no-shots candidate as a diagnostic challenger.
3. Repeat with a third genuinely unseen season or frozen weekly slates before choosing a new shadow winner. Enforce point-in-time feature availability and report coverage per league.

Reproducible outputs: `pipeline/diagnose_rich_holdout_fixtures.py`, `artifacts/model_reports/historical_2526_fixture_diagnostic.json`, and the companion CSV containing fixture-level probabilities, goal expectations, inputs, and log-loss deltas. Source candidate contract: `artifacts/model_reports/v2_feature_candidate_audit.json`; genuine frozen-call source: `artifacts/model_reports/shadow_weekend_review_20260917.json`.
