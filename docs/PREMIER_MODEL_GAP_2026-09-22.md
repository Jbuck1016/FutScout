# Why the compact control scored better in the Premier League

This diagnoses the **same 760 historical Premier League fixtures** in the 2024/25 and 2025/26 walk-forward holdouts. The reference is the frozen-slate primary *recipe* refitted on earlier seasons, not the currently deployed artifact. Negative log-loss differences below favor the compact Elo/rest/shooting control. This is research, not an activation or deployment decision.

| Holdout | Primary log loss | Compact control | Control minus primary |
| --- | ---: | ---: | ---: |
| 2024/25 (380 matches) | 1.00370 | 0.99777 | −0.00592 |
| 2025/26 (380 matches) | 1.03243 | 1.02717 | −0.00526 |
| Both seasons (760 matches) | 1.01806 | 1.01247 | −0.00559 |

The gap repeats in both seasons. A 5,000-draw calendar-week-block bootstrap on the pooled matches gives a descriptive 95% interval of **−0.01081 to −0.00049**. Each *individual* season's prior week-block interval included zero, and these same holdouts influenced candidate selection. Do not read the pooled interval as independent proof of a new league-specific winner.

The clearest concentration is upset exposure. The primary called the home side a fairly strong favorite (at least 55% home-win probability and the largest of the three outcomes) in 213 fixtures. Those teams won **60.1%** of the time; primary averaged **67.9%** home-win probability and control **67.3%**. The away side won 32 of those games. These 32 losses contribute **−0.00341** of the total **−0.00559** control edge (61% of the accounting gap). For the whole favorite cohort, primary assigned 14.0% average away-win probability versus 15.0% observed; control assigned 14.3%. Those differences are modest and do not alone identify a causal flaw in field tilt or box entries.

The 20 most control-favorable matches account for more than the total net gap because other matches offset them. Dropping only those 20 reverses the sign (+0.00038), but symmetrically dropping the 20 strongest matches for **each** model still favors control (−0.00471). Thus the finding is tail-sensitive but not purely a one-sided outlier illusion.

Across all outcomes, away wins account for −0.00301 of the −0.00559 pooled mean difference; home wins account for −0.00191 and draws −0.00068. These contributions add exactly. They describe *where* the scoring gap sits, not why the tactical features behave this way.

This does not look like a universal home-favorite calibration defect. On primary-defined strong home favorites, La Liga's observed home-win rate was 76.0% against 68.5% forecast, while the Premier League's was 60.1% against 67.9%. Existing historical trials of global and league goal-rate offsets worsened Premier League loss in both folds. Previously tested no-shots tactical candidates likewise did not consistently beat the compact control in the Premier League. Those exploratory results are not independent confirmation either.

**Decision:** keep the private shadow model unchanged. Predeclare a Premier League upset/calibration check for genuinely frozen upcoming slates, comparing primary, compact control, and the tactical challengers on identical fixtures. Investigate confidence and away-upset misses, but do not fit a Premier-specific correction on the same two historical holdouts and then call its improvement validation.

Reproduce the decomposition with `python pipeline/diagnose_premier_model_gap.py`; the result is `artifacts/model_reports/premier_model_gap_diagnostic_20260922.json`. `python pipeline/tools/check_premier_model_gap_diagnostic.py` covers additive reconciliation. Source fixture predictions are `artifacts/model_reports/shadow_challenger_walk_forward_20260922.csv`, hash-checked against its original comparison report.
