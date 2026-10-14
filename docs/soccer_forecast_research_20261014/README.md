# Soccer forecast research checkpoint — 14 October 2026

Follow-up: the complete local cache has now been reconstructed and seven additional advanced-feature candidates evaluated. The [new report](../soccer_local_features_20261014/README.md) resolves the xG/xT export gap and identifies three invalid event feeds plus a legacy phase-definition mismatch. The original numeric results below remain preserved; they do not certify source quality.

The isolated branch fixes inconsistent score probabilities and reproduces the current model exactly. Six historical comparisons are complete; the new feature, decay and low-score candidates do not earn promotion.

## Location and scope

- Branch: `research/soccer-forecast-20261014`, starting from backend commit `21b7f3c`.
- Worktree: `C:\Users\jbuck\Documents\Codex\2026-10-13\task-2\soccer-forecast`.
- Operational, backend and Claude design worktrees were only read; no source checkout changes, jobs, directory renames, database writes, provider-key calls, merge, push or deployment.
- Public web reads checked method references and data-use restrictions. No provider data was downloaded.

## Verified repairs

Headline H/D/A, saved scorelines and rate-based simulation now share one Poisson score calculation. The grid expands until omitted joint mass is at most 1e-12; no tail is collapsed into an artificial maximum-score bucket. New saved probabilities retain full precision and carry a local score-contract marker. The marker is excluded from database columns, avoiding an unrequested schema change. Existing frozen files are untouched.

The box-pass explanation now correctly includes within-box completions. The legacy feature values are preserved; a separately named, tested outside-to-inside predicate is available for a future versioned raw-event rebuild.

## Reproduction and validation

- Data: 5,255 matches (1,751 / 1,752 / 1,752), five leagues, 2023-08-11 through 2026-05-24; saved historical data-quality gates pass.
- Original 0–12 calculation reproduced both archived baseline log losses exactly: 0.9872384997052166 and 0.9926423175874235.
- Full-data baseline goal rates match the saved primary model exactly on 143 spread-out rows (maximum difference 0).
- Independently reconciled 21,024 prediction rows, equal evaluation populations, proper scores, six artifact hashes and reloads.
- Regression checks: shared result/scoreline/simulation mass, independent Skellam agreement, tails, zero/extreme/invalid rates, DC marginals, old explicit distributions, chronology, missingness, box-entry definition and serialization.
- Existing model-artifact and league-table checks also pass.

## Candidate comparisons

| Candidate | 2024/25 log loss | 2025/26 log loss |
|---|---:|---:|
| [baseline29](baseline29.md) | 0.987239 | 0.992643 |
| [compact17](compact17.md) | 0.988696 | 0.992727 |
| [raw_advanced35](raw_advanced35.md) | 0.986891 | 0.993710 |
| [adjusted_advanced35](adjusted_advanced35.md) | 0.987501 | 0.993340 |
| [decay365_baseline29](decay365_baseline29.md) | 0.986927 | 0.993646 |
| [dc_baseline29](dc_baseline29.md) | 0.986387 | 0.993549 |

These are exploratory evaluations on previously reused seasons. The tiny baseline score change after the repair is due to removal of 0–12 truncation, not retraining improvement. The 2025/26 maximum H/D/A change from 0–12 is 0.00003146. The larger 0–8 versus 0–12 defect exceeds one percentage point for some rates within the supported range.

The new advanced candidates use reliable lagged PPDA, progression and defensive-height fields. Adjustment reduces their 2025/26 regression but does not beat the baseline. The 365-day decay and bounded DC correction also regress. More complexity is deferred until a new hypothesis has independent data and a clean prospective test.

## Prospective gate and remaining gaps

A protocol was saved before this run: reserve forecasts from 15 October 2026 onward; require at least 500 matched forecasts across 12 genuine frozen weeks before a planned review. This is a reserved evaluation design, not an installed collection job or already completed holdout. The present run never scores 2026/27 outcomes. Same eligible fixtures, same publication cutoff, model/data hashes and pre-kickoff market snapshots are required. Do not reconstruct missed slates after results.

Read [the feature and rights gap report](FEATURE_GAPS.md) before extending data or integrating a candidate. Historical xG/xT evidence exists in prior reports, but a complete versioned offline feature/observation export is missing. A WhoScored commercial/training rights grant was not found in inspected files. No new data service was purchased.

## Local outputs and commands

`artifacts/soccer_research_20261014/` contains protocol.json, report.json, validation.json, historical_predictions.csv and six .pkl research artifacts. These local private outputs are git-ignored. Model cards and implementation are committed separately.

```powershell
python pipeline/tools/check_soccer_forecast_research.py
python pipeline/tools/check_model_artifact.py
python pipeline/tools/check_league_table_simulator.py
python pipeline/tools/validate_soccer_research_run.py --source C:\Users\jbuck\arsenal-analytics-backend --output artifacts/soccer_research_20261014
# Re-run into a NEW directory; existing run outputs are never overwritten:
python pipeline/research_soccer_forecasts.py --source C:\Users\jbuck\arsenal-analytics-backend --output artifacts/soccer_research_new
```
