# Thursday freeze integrity and same-fixture research

## What the September audit found

The 2026-09-17 `thursday_frozen` file contains 46 calls, while later canonical results show four additional fixtures in its seven-day window. Its file was created on Friday 2026-09-18 at 20:45 UTC, it lacks a `generated_at` field, and it references a mutable fixture manifest whose present hash differs from the hash recorded in the snapshot. The original Thursday provider response and exact Thursday feature values were not saved. We therefore cannot establish, fixture by fixture, why each of the four calls was omitted or reconstruct a genuine pre-kickoff call for them.

The 2026-09-10 file has the same missing-provenance problem. Both remain in the historical performance report, but neither counts toward the complete, authenticated frozen-weekend promotion gate. They must not be relabeled or silently backfilled.

## New cutoff contract

- The provider fetch must return the full season schedule for each of the five leagues (380 games for Premier League, La Liga, and Serie A; 306 for Bundesliga and Ligue 1). A short or empty league response blocks the freeze.
- The exact provider response is copied to a date-stamped manifest. It must have been captured within 30 minutes of the actual Thursday UTC cutoff. Replaying last Thursday on Friday is rejected.
- All provider-known fixtures kicking off during the seven-day scoring window must be present once, with matching IDs, teams, leagues, and kickoff times. Missing canonical fixtures block the slate rather than producing a partial publish.
- Eligible completed matches and schema-v2 observations are read once before predictions. A missing current-season observation or mismatch with provider-reported completed games blocks the run. The exact materialized feature rows, source-row digest, and per-model counts of missing inputs before imputation are saved in the research bundle. The audit recomputes those counts from the saved rows.
- The shadow artifact and four private challengers score the same stored feature rows. Their snapshots include the same as-of, fixture-manifest hash, and feature-bundle hash. The audit checks every artifact digest, cutoff, row population, and source identity before scoring or shadow persistence.
- The later scorecard rechecks completed canonical fixtures against the originally frozen week. A fixture discovered later to have been omitted disqualifies that window from the complete-week count.

The old data source does not expose reliable *ingested-at* timestamps for every historical observation. The new Thursday capture proves which rows the model actually saw when it ran, and the audit excludes matches whose kickoff was after cutoff. It cannot prove when every underlying provider statistic was first published. Historical snapshots without a saved feature bundle cannot be upgraded to this standard.

## Challenger scope and scorecard

The existing 29-input model remains the primary private shadow model. Four local, unregistered research artifacts were trained from the 5,255 historical schema-v2 match rows: compact shooting/control, compact xT, box-entry sequences, and territory-by-Elo interactions. They are *not* validated for replacement merely by training. They receive their first fair same-fixture comparison at the next genuine Thursday slate containing matches.

`pipeline/refresh_prediction_ledger.ps1` refreshes the result ledger and the research-only paired scorecard. The scorecard reports result probability loss, Brier score, goal error, per-league metrics, and paired differences on exactly the same resolved fixtures. It does not register, promote, activate, or publish a challenger. The review gate requires at least 100 scored same-fixture calls, 20 per league, and three complete frozen windows; passing it only triggers human review, not automatic promotion.

## Operating checks

Run `python pipeline/tools/check_frozen_tournament_contract.py` for the synthetic five-model freeze/audit/score test, plus the existing model and scoring checks. A real new window is audited by `pipeline/audit_frozen_tournament.py`; its JSON report is saved under `artifacts/data_quality`. The scorecard is under `artifacts/model_reports/shadow_tournament_scorecard_2627.json`. During the international break, a Thursday with no provider fixtures is a no-op and produces no fabricated predictions.
