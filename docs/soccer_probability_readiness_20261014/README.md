# Soccer probability and label integration readiness

Status: **offline checks pass; live integration remains pending.** No promotion,
retraining, production writes, provider calls, credential reads, deployments,
scheduled-job changes, or operational/Claude checkout edits were performed.

This package follows the reviewed repairs at research commit `0593653` and
separates the probability/label corrections from all experimental model work.
It is a candidate integration patch, not evidence of a completed database round
trip or deployed fix.

## Deliverable and scope

The private package is under
`artifacts/soccer_research_readiness_20261014/minimal_package/`:

- `probability_labels_only.patch`: six files, based on committed backend
  `21b7f3ccc5970650b9204f138eb677c7a31dc799`.
- `package_manifest.json`: before/after hashes, exact function-change scope,
  test outcomes, clean-base apply and reverse-apply evidence.
- `clean_base_contract_checks.json` and three test logs: reproducible offline
  evidence independent of the research modules.
- `clean_base/`: ordinary exported base with only the minimal patch applied.
  This is an offline verification copy, not an operational checkout.

Patch SHA-256:
`9213de96cae51f873574bed2f899e99c97b586c67dbe9a5f389d10fc0ecb688d`.

| File | Intended change |
|---|---|
| `pipeline/score_probabilities.py` | New plain independent-Poisson helper; adaptive exact-score support with omitted joint tail at most 1e-12. |
| `pipeline/train_match_baselines.py` | Headline H/D/A uses the same distribution; rejects mismatched arrays. |
| `pipeline/model_artifact.py` | Saved grid shares the headline distribution; local rates/probabilities retain float precision; adds local contract tag; corrects box-pass label. |
| `pipeline/generate_match_predictions.py` | Strips the local contract tag from database rows. |
| `pipeline/simulate_league_table.py` | Expected-goal fallback uses the shared grid instead of an overflow score bucket. Existing explicit-score alignment remains unchanged. |
| `pipeline/tools/check_probability_integration.py` | Ten standalone offline regressions, actual installed SDK serialization through MockTransport. |

The patch's helper omits the experimental optional Dixon–Coles correction.
Default Poisson arrays were verified identical to the reviewed research helper.
It contains no player layer, advanced features, true-entry predicate, time
decay, model files, data, schema migration, dependency change, job or deployment
configuration. Do not cherry-pick whole research commits to integrate this fix.

All 49 other top-level functions across the four modified production files,
their module constants/classes/entry points, and unrelated imports are unchanged
by AST comparison. This includes fitting, feature construction, normalization
call paths, artifact loading and persistence horizon checks. Stub predictors
also verify existing model inputs, clipping to [0.05, 6], and unrounded outputs
without fitting any data. Predictions can change because the former truncated
grids were inconsistent; no claim of improved predictive accuracy follows.

The legacy `box_entries_pass_*` values remain exactly as trained. The corrected
label is **Completed box passes**, described as completed passes ending in the
box, including passes starting there. The historical metric includes all phases;
it is not a true-entry count or an open-play-only feature.

## Verified offline

The standalone ten-test suite passed both in the isolated research checkout and
on the clean committed-base export with only the six-file patch. Existing
league-table simulator and private model-review dashboard checks also passed
on that export. Applying the reverse patch restored every exported original
file hash and removed both added files. The forward patch was then reapplied
to leave an inspectable verification copy.

Tests use installed `postgrest 2.28.3`, `supabase 2.28.3`, `httpx 0.28.1`,
`numpy 2.1.3`, `scipy 1.15.3`, and `scikit-learn 1.6.1`. Socket/real HTTP
transport, dotenv loading, Supabase client creation, and the application DB
client are blocked during the new test suite. HTTP requests go only through
`httpx.MockTransport`; the fake host is `offline.invalid`, with no auth headers.

Coverage includes:

- Real SDK upsert JSON fields, composite conflict key, merge preference,
  metadata exclusion, and strict `(as_of, evaluation_through]` boundaries.
- Existing registry-status, artifact-digest and empty-slate guards preventing
  any mock POST; nonfinite JSON rejected by the installed serializer.
- JSON preservation of explicit grid floats, extended tails and independent
  Skellam H/D/A comparison including high/low rate limits.
- Decimal precision, half-up ties, precision overflow and declared numeric
  checks; these are Python emulations of local SQL, not SQL-engine tests.
- The real pure simulation adapter consuming explicit grids after scalar
  coercion, retaining conditional score ratios and legacy explicit support.
- Corrected label and exclusion of score grids from private dashboard output.

Reproduce without credentials from this isolated checkout:

```powershell
python -B pipeline/tools/check_probability_integration.py --report artifacts/soccer_research_readiness_repeat/contract_checks.json
python -B pipeline/tools/package_probability_readiness.py --output artifacts/soccer_research_readiness_repeat/minimal_package
```

Use a fresh output directory: the builder refuses to reuse a `clean_base`.
It reads Git objects locally and never contacts a remote. Do not run forecast or
simulation CLI entry points as an offline test: their current implementations
create database clients even when `--execute` is absent.

## Precision contract and consumers

Checked-in declaration:
`supabase/migrations/20260901230956_model_data_foundations.sql`.
This does **not** establish the actual deployed schema.

| Value | Local schema / handling | Acceptance |
|---|---|---|
| Expected goals | `numeric(7,4)` | Stored-rate rounding error at most 5.0001e-5. |
| H/D/A | Three `numeric(8,7)` columns | Scalar-vs-original-grid error at most 5.0002e-8 per class. |
| H/D/A sum | SQL check tolerance 1e-6 | Rounding bound 1.50001e-7; do not require bitwise sum equal to one. |
| Score grid | `jsonb` object | Preserve explicit cells; compare parsed masses at 2e-12 for unrounded local forecasts. |
| Simulation | Explicit grid with existing headline alignment | Matches normalized stored headlines within 2e-12; within-class score ratios retained. |
| Contract tag | Local JSON only | Must be excluded from database rows until a schema change is separately designed. |

The previous offline audit over 1,752 already evaluated historical baseline rate
pairs found maximum scalar rounding error 4.999e-8. Recreating a grid from stored
four-decimal rates changed H/D/A by up to 2.296e-5. **Use the saved explicit grid
for stored forecasts.** This readiness work did not fit or rescore a model, read
future outcomes, or extend reused-season model selection.

| Consumer | Contract and integration implication |
|---|---|
| Local forecast JSON | Full remaining schedule, full float rates/grid and local contract tag; larger file. Preserve existing frozen files. |
| `persist_predictions` | One upsert for the weekly slate, default 7 days and CLI permits 1–14; no byte-based batching. |
| `run_league_simulation.build_snapshot_with_results` | Converts grid object to explicit score list. Existing exact fixture-ID coverage checks still apply. |
| `simulate_league_table.prepare_fixtures` | Variable-length support works; uses explicit score probabilities when supplied. Grid order is not a contract. |
| `score_prediction_ledger.py` | Selects full grids in pages of 1,000; response size is a live compatibility risk. |
| `score_prediction_snapshot.py` | Uses scalar forecasts/rates for evaluation; inherits database precision when given stored rows. |
| `build_model_review_dashboard.py` | Whitelists scalar/explanation output and omits grids; its safety check passed. |
| Other external clients | Not discoverable from this repository audit; must be inventoried before integration. |

## Payload measurements

`artifacts/soccer_research_readiness_20261014/sdk_payload_profile.json` captures
installed-client request bytes from a memory-only rebuild of the existing
17 September frozen snapshot. It uses only recorded rates and fixtures, not
outcomes. Rates in that file may already be rounded, so this sizes payloads
rather than reconstructing the originally fitted rates. Model-run ID
`123456789` is synthetic; no registry row was created.

| Measurement | Existing grid | Adaptive grid |
|---|---:|---:|
| Weekly slate fixtures | 46 | 46 |
| Actual SDK mock POST body | 116,829 bytes | 478,886 bytes |
| Simulated first 1,000-row JSON response | 2,539,833 bytes | 10,659,854 bytes |
| Simulated remaining 549-row response | 1,394,233 bytes | 5,873,241 bytes |
| Largest single grid in inspected file | 2,261 bytes / 81 cells | 24,884 bytes / 841 cells |

At the maximum production-clipped pair (6, 6), the helper returns 961 score
cells, occupying 28,456 compact-JSON bytes in this installed serializer.
The earlier snapshot audit measured a 26,207,914-byte indented full-schedule
memory copy versus 9,608,649 bytes in the existing file, and about 109 MB peak
traced allocations for preparing all 1,549 fixtures. Those are local Python
measurements, not database storage or full 10,000-season runtime results.

No byte/cell cap is declared for the JSONB object in the inspected migration.
Gateway request/response limits, deployed page limits, timeouts, PostgreSQL
TOAST/storage costs and production concurrency remain unknown. The gzip sizes
in the machine report are hypothetical; the client did not enable request
compression. Do not treat row-count pagination as a body-size guarantee.

## Integration plan and remaining live checks

Pending by the explicit offline-only scope; no live operation was attempted or
denied. The operational and Claude branches remain unmodified.

1. After the redesign work is reconciled, have the integrating agent compare the
   current target with the exact base/hashes in the manifest and review each
   hunk. Prepare one scoped commit, for example **Fix forecast score-grid
   consistency and box-pass labels**, containing only the six listed files.
   Apply-check success against the old base does not establish compatibility
   with later or uncommitted work. Re-run the three package checks there.
2. In a separately authorized isolated database/staging target, inspect actual
   numeric types, JSONB column, sum constraint, composite unique key, RLS/grants
   and PostgREST schema cache. Verify installed deployment dependencies. Keep
   provider access disabled; no new source data is necessary for these checks.
3. Record source-code commit, contract version and artifact digest for new
   forecast output. The local tag is not stored in the present DB schema;
   artifact digest alone does not identify changed scoring code. Resolve this
   lineage in the existing registry/release process before publishing forecasts,
   preserving coefficients and feature inputs. No registry promotion is part of
   this patch or the current authorization.
4. Use new staging identities and a future as-of; round-trip a bounded synthetic
   fixture slate through the actual client/server, inspect persisted scalars and
   grids against the tolerances above, fetch it through ledger and simulation
   readers, and verify repeat-write idempotency there. The mocked tests verify
   the request's conflict key, not server-side uniqueness or FK/RLS behavior.
   Never reuse existing production frozen keys to test this: current upsert
   semantics can overwrite rows with the same composite identity.
5. Measure representative 7- and 14-day writes and full requested 1,000-row
   responses through the real deployment gateway. Confirm complete row counts,
   successful parsing, acceptable runtime/memory and actual configured limits;
   do not invent a universal size limit. If limits are exceeded, design a
   separately reviewed byte-aware batching/select reduction before release.
6. Run the real end-to-end season simulation on a preserved snapshot in staging
   at its configured simulation count. Check fixture coverage, league rules,
   expected-point sanity and scalar/grid consistency. Record performance and
   publication-consumer compatibility before any production rollout.

These checks must be completed before claiming live readiness. None requires
another candidate fit or reused-season model selection. The reserved future
holdout, frozen evidence and market decision-time rules remain intact.

## Rollback

Record the exact pre-integration commit, runtime dependency versions, forecast
artifact digest, output locations, and immutable forecast/registry identities
before a separately authorized rollout. Keep the change in one scoped commit.
If live checks fail, stop generating new forecasts with that code and revert
that commit after checking for subsequent dependent edits; re-run the existing
checks and restore the previous runtime configuration if it was changed.

Do not replace, rewrite or delete either old frozen forecasts or newly created
evidence. Preserve their identities and mark rejected new staging outputs in
the authorized registry workflow. The fitting artifacts and coefficients do
not change in this package. Both readers already accept explicit score lists,
so archived grids should remain readable after code rollback. The checked
reverse patch proves source-file restoration against the exported base only;
it is not a database or deployment rollback test.
