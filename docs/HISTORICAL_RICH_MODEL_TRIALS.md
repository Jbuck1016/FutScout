# Historical rich-feature trials — 22 September 2026

These are **private research comparisons**, not changes to the registered or
live shadow model. Every input is from matches before the fixture being
predicted. Models train on 2023/24 and test on 2024/25, then train on
2023/24–2024/25 and test on 2025/26. Each test season has 1,752 fixtures.
Lower match-result log loss is better; the same trials also record Brier,
calibration error, goals MAE, and league breakdowns.

The 5,255-match archive now has complete two-sided historical event, sequence,
carry, observation, and rolling feature coverage, with the documented
2023/24 Rennes–Metz source exception excluded. The three rebuilt v2 quality
gates report zero duplicate feature rows and zero detected leakage violations.

## What the trials say

| Challenger versus 17-field shooting control | 2024/25 log loss | 2025/26 log loss | Reading |
|---|---:|---:|---|
| Shooting control | 0.9887 | 0.9927 | Reference, not a claim about the deployed artifact |
| + field tilt and completed box entries | 0.9872 | 0.9926 | Better twice, but the latter edge is tiny |
| + five-match xT difference | 0.9873 | 0.9925 | Better twice, still tiny |
| + five-match box-entry sequences | 0.9873 | 0.9924 | Better twice, still tiny |
| + all xT rolling fields | 0.9845 | 0.9943 | Strong first holdout, regressed second |
| + broad rich-attack fields | 0.9842 | 0.9971 | Strong first holdout, larger second-season regression |
| Compact tactical model, **without shots** | 0.9898 | 0.9944 | Did not beat shooting control |

The separately engineered event/carry observations were converted to strict
earlier-date 5- and 10-match rolling inputs. In the same two folds, adding
progressive passing to the shooting control scored **0.9852 / 0.9943**;
adding high recoveries and defensive actions scored **0.9881 / 0.9927**;
adding carry volume/xT scored **0.9922 / 0.9933**. A shot-quality group that
includes historical non-penalty xG per shot, box-shot share, big-chance rate,
and shot distance scored **0.9875 / 0.9949**: promising once, then regressing.
Non-penalty xG per shot alone scored **0.9884 / 0.9928**, almost identical to
the control in the first holdout and slightly worse in the second. It remains
a useful descriptive metric, but this test does not support giving it model
weight yet.
The pressing improvement
is only about 0.0006 and 0.00003 log loss; paired fixture bootstrap intervals
include zero in both holdouts. This is a lead for continued testing, not proof.

Week-blocked paired bootstrap intervals include zero for both seasons' compact
field-tilt and five-match xT gains. The five-match box-entry sequence gain
excludes zero in 2024/25 but not in 2025/26. These are exploratory intervals
after testing many candidates, so they should **not** be read as a validated
selection or promotion test.

The broad xT regression is not uniform. In 2025/26 it worsened Premier League
and La Liga log loss, while Ligue 1 still improved. The pattern could reflect
feature overlap, non-stationarity, or model overfitting. This trial does not
establish which explanation is causal. Importantly, **the richer features are
present and tested**; poor generalization is no longer attributable to the
previous historical coverage gap alone.

## Guardrails and next tests

1. Keep the current shadow artifact unchanged. Do not hide shots or declare a
   rich-feature winner based on these small differences.
2. Review fixture-level errors and league slices for the compact
   xT/territory/sequence trials, especially Premier League and La Liga
   2025/26. The week-blocked uncertainty check is in the v2 report; it did not
   establish a robust two-season winner. This matters more than another large
   column set.
3. Check whether the richer signals add residual lift beyond pre-match Elo and
   shooting, and whether coefficients remain directionally stable by season.
4. Compare the same contenders on actual **frozen Thursday** predictions.
   These historical holdouts evaluate each match at its pre-match cutoff, not
   a whole weekend frozen on Thursday, so they cannot replace live scoring.
5. Consider a new challenger only after repeated, material gains in log loss
   and calibration without an unacceptable league-level regression.

Reproducible commands and detailed reports:

- `python pipeline/evaluate_v2_feature_candidates.py` →
  `artifacts/model_reports/v2_feature_candidate_audit.json`
- `python pipeline/evaluate_historical_event_candidates.py` →
  `artifacts/model_reports/historical_event_candidate_trials.json`
- `python pipeline/tools/check_historical_event_candidate_trials.py` checks
  that same-date match observations cannot enter each other's rolling inputs.
