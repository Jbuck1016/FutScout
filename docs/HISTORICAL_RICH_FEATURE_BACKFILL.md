# Historical rich-feature backfill

## Why the coverage audit was sparse

The three top-five-league training seasons were scraped and their raw events
were verified. In September 2026, non-live events were moved from `events` to
`events_archive` to keep live analytics responsive. The v2 feature helper,
however, still read `events`, `sequences`, and `mv_shot_xg`. The latter two are
built for the live analytics scope. Thus the historical raw feed was present
but rich historical features were not fully engineered.

Database check on 2026-09-22 (completed fixtures, all competitions in each
season):

| Season | Fixtures | Games with archived events | Games with old sequences |
| --- | ---: | ---: | ---: |
| 2023/24 | 1,752 | 1,751 | 0 |
| 2024/25 | 1,752 | 1,752 | 0 |
| 2025/26 | 1,774 | 1,773 | 453 |

The five-league verified training set has 1,751 + 1,752 + 1,752 = **5,255**
matches. The known 2023/24 Rennes–Metz source exception retains its result
but is excluded from event-based features; see
`pipeline/historical_source_exceptions.json`. Non-league fixtures in the raw
`matches` count are not part of this training backfill.

## Implementation

- `pipeline/generated/historical_rich_sequence_backfill.sql` creates an
  archive-only sequence table and a narrowly scoped, resumable batch RPC.
  It clones the live sequence definition but reads `events_archive`, so a live
  rebuild cannot truncate historical sequences. Its `xt_sum` is **pass xT**;
  it should not be described as all-action xT. The archived clone adds the
  unique `ws_id` as a final event-ordering key: provider `event_id` can tie
  across teams at the same second, which otherwise merges possessions.
- `pipeline/generated/historical_v2_observation_backfill.sql` clones v2
  observation calculations against archived events, historical sequences,
  and the historical point-in-time shot scores.
- `pipeline/generated/historical_point_in_time_xg.sql` derives shot geometry
  with the same distance, angle, header, big-chance and penalty bins as the
  live shot model. It scores each match using bin outcomes from strictly
  *earlier dates*, with a fixed 0.10 base and 20-shot shrinkage prior. This
  is deliberately versioned separately from the live display xG model.
- `pipeline/generated/historical_event_candidate_metrics.sql` adds
  progressive passes, final-third entries, box-entry passes, net and positive
  pass xT, high ball recoveries, high defensive actions, non-penalty shots,
  box shots, big chances, and mean shot distance. These are candidate signals,
  not automatically model inputs.
- `pipeline/generated/historical_carry_candidate_metrics.sql` applies the
  same receipt-to-next-action carry definition as the live analytics view and
  adds carry xT, progressive carries, and carry box entries.
- `pipeline/generated/historical_sequence_quality_repair.sql` compares
  independently calculated pass xT and pass counts with possession totals,
  and rebuilds only specifically mismatched verified games in a checked
  transaction. It does not clear the whole historical table.
- `pipeline/backfill_historical_sequences.py` runs the three independent
  archive jobs with bounded 1–8-match transactions and JSON state files.
- `pipeline/run_historical_rich_followon.py` waits for the sequence job, then
  rebuilds v2 observations and rolling features for all three seasons and
  reruns the quality audits. It does not train or promote a model.

All new tables have RLS and no `anon` or `authenticated` access. The service
role alone can call the backfill RPCs. Background jobs are one-shot local
processes, not scheduled tasks.

## Validation gate before model experiments

1. Each archive job reports `complete`, with no stderr failures.
2. Source-backed coverage reaches 5,255 matches and 10,510 team sides,
   subject only to the documented source exception.
3. Historical sequence xT and the separately computed pass xT agree within
   0.01 per team-match; total passes agree exactly. The one-shot follow-on
   waits for both source jobs, performs targeted repair, and rechecks zero
   remaining discrepancies before rolling features are generated.
4. The three `model_data_quality_v2_*.json` audits are regenerated from the
   rebuilt observations and rolling features.
5. Candidate families must pass chronological out-of-season tests before any
   model training or shadow promotion; their presence is not evidence of lift.

The point-in-time shot table now has 45,766 / 43,665 / 44,049 scored shots for
2023/24, 2024/25 and 2025/26 respectively, with no null xG. Non-penalty
expected goals versus actual goals are 4,375.9 vs 4,459, 4,440.3 vs 4,397,
and 4,407.4 vs 4,285. These are aggregate sanity checks, not proof that the
shot model is calibrated in every league or period. Model experiments must
compare this version with a matching current-season definition; the live
display xG model should not be silently substituted into training features.

## Additional live-data finding

The same independent pass-xT check on the 2026/27 live sequence table found
8 discrepant team-sides among 1,274 compared. Four are from two `fd-*`
synthetic fixture IDs with especially large gaps; two real fixtures account
for the remaining four sides. This is a separate live analytics repair task,
not a reason to copy live sequences into historical training. No live tables
were rebuilt or modified during this historical backfill.
