# Pipeline incident audit — 12 October 2026

## Status

Preventive code repairs implemented and tested in the operational backend checkout.
Production data repair, a verified rebuild, and publication recovery are NOT complete.
The user performed the administrator-only nightly task repointing; its new action
and working directory were independently verified afterward. Do not call the pipeline healthy yet.
No production data, permissions, model lifecycle, frozen forecasts, or schedules were
changed during this pass. One task-action update was attempted and denied by Windows.
No force push, deploy, retraining, paid odds request, or broad scrape was performed.

## Confirmed findings

1. **Abandoned match misclassified as completed.** `fd-564698`, Rayo Vallecano–Athletic
   Club, 2026-10-10, has 230 events, last expanded minute 24, metric length 25. A fresh
   direct WhoScored request returned the same 230 events. Athletic Club's official
   statement confirms abandonment:
   https://www.athletic-club.eus/en/news/2026/10/10/the-athletic-club-squad-returns-to-bilbao/
   This is not evidence that more scraping will recover a full match. Preserve its
   raw events and do not count its provisional 0–0 as a final result. No archive
   manifest currently maps this canonical ID. The retained local original is
   `artifacts/pipeline_audit_20261012/1994172.before.json`.
2. **Verification remains blocked.** Rebuild
   `b7589094-d368-4fdd-8a55-eebbd6158b5a` failed on
   `truncated_fixture_in_metrics`; 53 checks, 1 error, 5 warnings. Five latest runs
   failed the same invariant. Some materialized metrics/profile/search layers were
   refreshed before final verification; summaries stayed held. This is mixed
   freshness, not a fully verified new publication. Do not disable the invariant.
3. **Duplicate scheduled fixture.** Levante–Athletic, 2026-10-21, exists as both
   `1994183` and `fd-564685`, both live, neither with event rows. La Liga reports
   381 rather than 380 fixtures. This blocked the 8 October Thursday forecast.
   Numeric/provider IDs must be reconciled with dependent references, not blindly
   deleted. Existing schedule matching is date-dependent and can create another
   identity when a kickoff moves. That failure mechanism is fixed in code; the
   exact historical creation sequence of these two rows was not proven.
4. **Two operational checkouts.** Nightly task `MLS-Euro Analytics Scrape` still
   executes `C:\Users\jbuck\arsenal-analytics\pipeline\weekly_scrape.bat`.
   Other pipeline tasks execute the backend checkout. Both contain unrelated dirty
   changes. Fixes in one checkout were not reliably reaching the nightly job.
5. **Scorecard publication failure.** 6 October scorecard computed successfully,
   then its push to main failed because the remote had moved ahead. Its local
   commit was `21b7f3c`. Do not force push or merge a dirty operational checkout.
6. **Collection is not verification.** Prior weekend check found 59 uploaded games
   with scores/events and team metrics, including the abandoned match: PL 9,
   La Liga 9, Ligue 1 9, Bundesliga 9, Serie A 8, MLS 15. These were database counts,
   not a proof that all were completed matches. Latest read-only audit also finds
   four completed Monday 12 October games without events, awaiting the nightly run:
   Coventry–Newcastle `fd-560597`, Levante–Sevilla `fd-564704`,
   Atalanta–Venezia `fd-558579`, Torino–Udinese `fd-558587`.
7. **Odds capture is doing real work.** Saved Thursday 8 October log records
   48 matched games and 985 persisted bookmaker rows, not merely a successful
   no-op. Current result-ledger artifact was generated 12 October 22:35Z.
   Full per-match odds timing/coverage reconciliation was not performed here.
8. **Misleading success paths.** A failed live league schedule returned zero work
   as success, and partial progress could exit zero. Existing repair pruning read
   only one API page and could miss stale events beyond row 1000.

## Implemented repairs

- `pipeline/feed_validation.py`: minimum 80-minute completed-feed guard, matching
  the pre-existing rescrape-worker threshold. This is a minimum sanity check, not
  proof of complete data. Abandoned/shortened matches require explicit handling.
- `scrape_and_load.py`: validate before the match/player/event write boundary.
- `scrape_league.py`: domestic round-robin rescheduled-pair identity preservation;
  ambiguous matches fail closed; cup/MLS pairings are not generalized this way.
  Schedule failure and partial ingestion now exit nonzero. Removed the false
  assertion that no new games necessarily means analytics are current.
- `audit_live_ingestion.py`: bounded current-season metric-length checks flag
  short feeds even where event rows exist. Saved audit correctly exits 1.
- `rescrape_queue.py`: paginate stored event IDs before computing stale IDs.
- `publish_dashboard_data.py`: fresh remote-main checkout, explicit two-file
  allowlist, no mutation of the operational index/branch, no force push. A concurrent
  remote race rejects publication rather than overwriting remote work.
- `refresh_shadow_scorecard.ps1` and `run_shadow_weekly.ps1`: use this publisher.
  Existing unrelated changes in the weekly script were preserved.
- `repair_nightly_task_path.ps1`: dry-run default; change only task action and
  working directory, preserve timing/principal, retain prior task XML, refuse if
  running, verify after update.

## Tests actually run

All passed offline:

```
python pipeline/tools/check_pipeline_repairs_20261012.py
python pipeline/tools/check_live_audit_rescrape_guard.py
python pipeline/tools/check_rescrape_queue_mapping.py
python pipeline/tools/check_audit_fixture_and_phase_guards.py
```

New tests cover short/empty/malformed feeds; zero match writes on rejection;
rescheduled domestic identity vs repeated MLS pairing; publication from a stale
checkout after unrelated remote changes; local dirty/untracked preservation;
unapproved file rejection; unchanged rerun; stale event detection beyond row 2000.
Python compilation passed for changed modules. PowerShell parser passed the two
job wrappers and the task-repair script. Task-repair dry run passed.

Live read-only check:
`python pipeline/audit_live_ingestion.py --strict --output artifacts/pipeline_audit_20261012/live_ingestion.json`
Correctly failed: duplicate, abandoned short feed, four Monday missing event feeds.
No end-to-end production publication or clean rebuild has been claimed.

## Remaining rollout gates and exact next actions

### Administrator action

In elevated PowerShell:

```
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\jbuck\arsenal-analytics-backend\pipeline\repair_nightly_task_path.ps1" -Execute
```

Windows denied the attempted task update in this session. The original task XML
was retained at `artifacts/pipeline_audit_20261012/nightly-task-before.xml`.
No replacement job was launched to work around this denial.

Follow-up verification after the user ran the repair: task is Ready; action is
`C:\Users\jbuck\arsenal-analytics-backend\pipeline\weekly_scrape.bat`; working
directory is the backend checkout. Next run is 12 October 2026 at 23:30 local.
LastTaskResult 1 belongs to the previous 11 October run, not the repaired task.
Read-only production recheck still shows the same abandoned-match classification,
duplicate fixture rows, and last failed rebuild. Repointing alone does not repair those.

### Production fixture repair requires a coordinated, separately verified change

- Introduce explicit abandoned/suspended/completed fixture state (or an equivalent
  existing governed exclusion mechanism), retain all source events, and exclude
  non-final results from settlement, full-match metrics, model observations and
  scored forecasts. Record the official source and the provisional score as
  evidence, not a final result. Do not simply lower the minute threshold.
- Do NOT merely set `matches.is_live_scope=false`: its trigger recomputes scope
  on league/season updates, so the next schedule upsert can silently reactivate it.
- Capture both duplicate fixture rows and all dependent references; choose the
  surviving identity based on those references; reconcile rather than blindly
  deleting one. Update both provider importers so it cannot reappear.
- Test these semantics in an isolated database fixture before production changes,
  provide exact SQL/data changes and rollback for approval, then run one governed
  rebuild after all current event ingestion is complete. Do not repeatedly retry
  the same failed rebuild or publish summaries before verification passes.
- Rerun the scorecard with existing authentic snapshots only. Do not manufacture
  a retrospective Thursday slate for the missed 8 October run.

## Rollback and limitations

Code changes are local and not committed/deployed; the backend checkout was already
dirty. Revert only the scoped hunks above, not whole files or the worktree. New
helper files can be removed once wrappers are restored. Task rollback restores only
its prior action/working directory from the saved definition. Database rollback
will need row snapshots and verified dependency mappings before any data correction.

The live database's exposed permissions/security posture was not altered or audited
again here. Website design work, model promotion and training are outside this repair.
