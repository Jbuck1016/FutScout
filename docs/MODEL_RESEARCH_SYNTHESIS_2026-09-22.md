# What we know about the FutScout match model — 22 September 2026

This is a research readout, not a model promotion or a claim that any candidate is a proven betting system. The private shadow artifact remains the 29-input field-tilt/box-entry Poisson model. Historical trials here use strictly pre-match rolling features, training on 2023/24 then testing on 2024/25 (1,752 matches), and training on 2023/24–2024/25 then testing on 2025/26 (1,752 matches). Lower result log loss is better. The Thursday live protocol is stricter: a whole slate must be frozen at publication time.

## New controlled tests

The script `pipeline/test_rich_calibration_interactions.py` replayed the same two chronological folds. It tried predeclared five-match Elo×territory and shots×territory interactions. For calibration, it fitted a goal-rate offset on the final 20% of **training dates**, then applied it to models refit on the complete pre-holdout training seasons; no test-season result informed an offset. League offsets were shrunk toward the global offset. Every variant used identical holdout fixtures and the same control probabilities for paired comparisons.

| Candidate | 2024/25 log loss | 2025/26 log loss | Interpretation |
| --- | ---: | ---: | --- |
| Compact shooting control | 0.98870 | 0.99273 | Reference |
| Territory: shooting + field tilt + box entries | 0.98724 | 0.99264 | Better twice, but 2025/26 gain is negligible |
| Territory + Elo×territory interactions | 0.98700 | 0.99223 | Better twice; exploratory and small |
| Territory + shots×territory interactions | 0.98737 | 0.99262 | No meaningful added lift |
| Territory + all four interactions | 0.98688 | 0.99224 | Similar to Elo-only interactions; extra complexity did not help in 2025/26 |
| Broad rich-attack candidate | 0.98418 | 0.99711 | Best in first fold, lost ground in second |
| Broad rich attack + global goal offset | 0.98514 | 1.00176 | Worse in both |
| Broad rich attack + shrunken league offsets | 0.98582 | 1.00256 | Worse in both |

The Elo×territory interaction's improvement over control was -0.00170 log loss in 2024/25 and -0.00050 in 2025/26. Paired calendar-week bootstrap 95% intervals were [-0.00544, +0.00227] and [-0.00380, +0.00284]. Both include zero. This is a useful research lead, **not** strong evidence of a durable win after many candidates were tried. It still loses to the control in the Premier League in both holdouts (2024/25: 1.0029 vs 0.9978; 2025/26: 1.0315 vs 1.0272).

The simple calibration hypothesis did not survive its test. In 2025/26, the rich model's league offsets slightly improved Premier League log loss (1.0400 to 1.0388) but worsened La Liga (0.9905 to 1.0014), and worsened overall result log loss (0.99711 to 1.00256). Goal MAE improved for some variants while win/draw/loss log loss worsened. Therefore a lower goals error alone is insufficient to justify a forecast change. The calibration slice implied a positive global home-goal adjustment in the first fold and a negative one in the second, another sign that a fixed offset does not travel reliably.

## What the broader evidence says

1. **The data engineering is real and relevant.** The three historical seasons now have the event, sequence, carry, and rolling v2 feature coverage required by these trials, with the documented Rennes–Metz source exception. The earlier missing-history explanation no longer accounts for the broad rich candidate's regression.
2. **Simple shooting is a strong control, not a philosophical endpoint.** Field tilt, box entries, compact xT difference, and box-entry sequences improved average results in both historical holdouts by small amounts. Broad xT and rich models improved 2024/25 but regressed 2025/26; xG per shot did not add stable incremental lift. Correlated tactical signals may describe *how* teams play without necessarily adding enough new information beyond Elo and shots to improve a small-sample pre-match forecast.
3. **The rich-model problem has a league shape.** The fixture-level 2025/26 replay shows broad rich attack losing most ground in the Premier League and La Liga, especially on actual home wins. That is an observed error pattern, not proof that any one coefficient, tactic, or data field caused it. Simple league/home offsets did not repair the overall issue.
4. **Historical tests are necessary, not sufficient.** The 2025/26 29-input territory model scored 0.99264 log loss on 1,752 fixtures, versus 0.99273 for compact shooting and 0.97744 for matched, margin-removed average closing market odds. The odds are an external benchmark, not an input or a fair identical-information Thursday comparison. The gap shows room to improve, not a guaranteed betting edge.
5. **Real frozen scoring is underway but incomplete.** The 17 September shadow review scored 46 frozen calls at 0.9679 mean log loss; four provider-known completed fixtures had no frozen call. That is too small and incomplete to select among tactical challengers, and those challengers did not have genuine same-timestamp calls. A good-looking individual weekend must not override the historical instability.

## What to improve next, in order

1. **Forecast integrity first:** make every eligible fixture appear on the immutable Thursday slate, with a separate latest version for updates. Track missing calls as a first-class failure. Same-fixture, same-cutoff comparisons are essential.
2. **Run a small, named shadow tournament:** current 29-input model, compact shooting, compact xT, box-entry sequences, and Elo×territory. Freeze each model's probabilities and expected goals at the same time, then score result log loss, Brier, calibration, goals MAE, and each league. No retrospective challenger calls masquerading as frozen forecasts.
3. **Investigate residual tactical signal:** test xT/territory/pressing after accounting for Elo and shooting, with predeclared feature families and regularization. Evaluate whether input values and model effects are stable by league, season, and early versus late season. Do not stack all columns simply because they exist.
4. **Revisit model form if warranted:** test a hierarchical or partially pooled league/home component, nonlinear interactions, and a direct result model against the Poisson baseline. These are hypotheses requiring untouched evaluation, not replacements by fiat. A separate goal-calibration objective must never quietly degrade result probabilities.
5. **Separate prediction from explanation:** keep rich tactical metrics in the match investigation and Writing Lab even when they do not qualify as predictive inputs. Show exact pre-match inputs and model-specific contributions; do not imply a post-match xT or shot-quality metric was known on Thursday.
6. **Promotion gate:** require repeated frozen weeks, material paired improvement, no unacceptable league regression, complete coverage, and honest calibration. The current evidence supports keeping the existing private shadow artifact while testing challengers, not activating or publishing a new winner.

## Limits of this readout

Two season-level holdouts contain many fixtures but only two independent changes of season. Candidate selection was exploratory across numerous feature sets, so ordinary paired intervals understate the multiple-comparison risk. Elo in historical holdouts updates as prior holdout matches finish; a single Thursday slate cannot use later weekend results. The offset test uses an inner chronological calibration slice from an earlier, smaller training fit, so its failure rejects this **particular simple offset method**, not every possible calibrated or hierarchical model. No mechanism or causal interpretation has been established from coefficients or fixture examples alone.

Reproducible primary evidence: `artifacts/model_reports/rich_calibration_interaction_trials.json`, `artifacts/model_reports/v2_feature_candidate_audit.json`, `artifacts/model_reports/historical_event_candidate_trials.json`, `artifacts/model_reports/historical_2526_fixture_diagnostic.json`, `artifacts/model_reports/bookmaker_benchmark.json`, and `artifacts/model_reports/shadow_weekend_review_20260917.json`.
