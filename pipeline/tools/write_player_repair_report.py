"""Document v3 repairs and fixed exploratory reruns without replacing v2 evidence."""
import argparse
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(output,old_output,repair,destination):
    report=read(output/'report.json'); old=read(old_output/'report.json')
    validation=read(output/'validation.json'); capacity=read(repair/'persistence_payload_audit.json')
    preserved=read(repair/'evidence_preservation_and_rebuild.json')
    destination.mkdir(parents=True,exist_ok=True)
    table=['| Candidate | 2024/25 v2 | 2024/25 repaired v3 | 2025/26 v2 | 2025/26 repaired v3 |',
           '|---|---:|---:|---:|---:|']
    for name,meta in report['models'].items():
        a=report['folds']['2425']['candidates'][name]; b=report['folds']['2526']['candidates'][name]
        table.append(f"| [{name}]({name}.md) | {old['folds']['2425']['candidates'][name]['log_loss']:.9f} | {a['log_loss']:.9f} | {old['folds']['2526']['candidates'][name]['log_loss']:.9f} | {b['log_loss']:.9f} |")
        lines=[f'# {name}: repaired player features v3','',
               'Research only. Same two Poisson(alpha=1) estimators, candidate inputs, folds and train-only preprocessing as v2. Repairs change exposure allocation and eligibility, not tuned hyperparameters. Individual ratings remain shrunk historical provider performance proxies, not causal player impact.', '',
               '| Test season | Train/test | Log loss | Brier | RPS | Delta vs control [95% interval] | Fallback |',
               '|---|---:|---:|---:|---:|---|---:|']
        for season,metrics in (('2425',a),('2526',b)):
            f=report['folds'][season]; p=metrics['paired_vs_baseline']; lo,hi=p['ci95']
            lines.append(f"| {season} | {f['train_matches']}/{f['test_matches']} | {metrics['log_loss']:.9f} | {metrics['brier']:.9f} | {metrics['ranked_probability_score']:.9f} | {p['delta_log_loss']:+.9f} [{lo:+.9f}, {hi:+.9f}] | {metrics['fallback_matches']} |")
        lines += ['', 'Intervals: paired four-observed-week circular blocks, 2,000 replicates, seed 20261014; reused seasons and no multiplicity adjustment. No candidate improves both seasons. All calibration bins, goal intervals, per-league scores and learned coefficients remain in report.json.', '',
                  'Expected named players have finite exposure in [0,90], goalkeeper/outfield budgets are 90/900, and deficits are explicit unknown replacement minutes. Latest strictly earlier observed club controls expectation; departed players remain only in the historical reference. Same-date observations update after all forecasts. Missing/stale/low-coverage cases use the exact baseline forecast.', '',
                  f"Final research refit: {meta['training_matches']} matches through {meta['trained_through']}. Artifact SHA-256 `{meta['sha256']}`.",
                  f"Player manifest SHA-256 `{validation['player_manifest_sha256']}`. Final artifact: `{meta['path']}`.", '',
                  'Eight chronological fold artifacts are saved separately. Source publication vintages, transfer-registration timestamps and injury/lineup probabilities remain unavailable. See [repair report](README.md) for complete checks and the remaining wrong-direction hypothetical absence effect.', '',
                  'Numeric inputs:', '']
        lines += [f'- `{c}`' for c in meta['columns']]
        (destination/f'{name}.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    snapshot=capacity['frozen_snapshot_profile']
    text=f'''# Independent-review repairs: player layer v3

All three confirmed findings against commit `8f3b410` are repaired in the isolated research branch. The v3 export and four fixed comparisons are complete. No model is promoted; no merge, deployment, database access, provider call or operational checkout change occurred.

The review is `C:/Users/jbuck/Documents/Codex/2026-10-13/task-4/SOCCER-INDEPENDENT-REVIEW-8f3b410.md`. Its probability/label correctness verdict was scoped PASS, while player allocation and scenario behavior required changes.

## Exact repairs

1. Preserve equivalent-90 exposure. The weighted mixture averages observed minutes without scaling depleted teams upward to 990. Named allocations are finite and at most 90. Role sums are reduced only when necessary to fit 90 goalkeeper and 900 outfield minutes. Missing exposure is recorded in separate goalkeeper/outfield unknown-replacement pools, which complete the 990 total. No extra minutes are silently assigned to a remaining player. The recent reference uses the same feasible allocation rules.
2. Maintain a prior-only membership ledger. After all predictions on each calendar date, record each player's last observed club, source game and date. An old-club expected allocation is removed once a strictly earlier appearance establishes another club. Conflicting same-date clubs remain ambiguous and ineligible. Removed minutes move to the appropriate unknown pool. The historical reference retains past participation so a known departure can still create a strength change. This is observed-appearance evidence, not a claim of complete registration or transaction history.
3. Validate scenario budgets. Reject NaN/infinite/negative replacement or player minutes, named allocations above 90, invalid totals, impossible role budgets and unclassified named roles. Replacement role pools reconcile explicitly; named players require prior membership evidence for the requested club and exact saved cutoff. Unknown replacements have zero excess rating. The scenario API requires a v3 plan, rejecting old infeasible plans.

The allocation module was additionally hardened to reject invalid shares at its own boundary. An exact replay with the final source reproduced every saved v3 feature and plan; the export preserves its original code snapshot and the replay records both hashes. This final guard does not change any valid exported data.

## Full-population verification

- All **10,510 expected plans** and references pass finite individual, team and role budget checks. Maximum expected individual exposure is **90.0**; over-90 allocations: **0**.
- Expected allocations to a player whose latest prior club is different: **0**. The membership rule removes allocations in **670 plans**. **3,090 plans** contain an explicit replacement deficit, including cold starts.
- The Rennes reproduction (`1911289`) now gives Anthony Rouault 90 minutes and Brice Samba 89.7504, versus 100.9071 and 100.6574. Bournemouth (`1903294`) no longer expects Antoine Semenyo after the already-observed Manchester City appearance on 17 Jan 2026; his 89.2902 old-club minutes become replacement exposure.
- Source observations remain 10,502 complete sides, eight missing sides, 162,592 appearances and 4,333 players. Reused observation bytes are hash-verified; no redundant provider/source collection occurred. Readiness is 10,046 of 10,510 team targets; the existing event-quality comparison population stays 5,216 fixtures.
- Twelve player regression/property tests pass, including 300 random mixture cases, depletion, individual bounds, role budgets, NaN/infinity, transfer chronology, ambiguous same-date clubs, unchanged same-date forecasts, target-data mutation isolation, stale/missing fallback and hypothetical replacement accounting.
- Independently reloaded eight fold models and reconciled all **13,860 held-out prediction rows**, fallback masks and proper scores. Four final model hashes were checked. **{preserved['old_evidence_files_unchanged']} earlier evidence files** are byte-identical, including v2 exports, models, predictions and earlier advanced/baseline outputs.

## Corrected exploratory comparisons

Lower H/D/A log loss is better. Same chronological training/test sizes: 1,751/1,714 for 2024/25, and 3,465/1,751 for 2025/26. Same candidate set, alpha, imputation, rating prior, usage weights and bootstrap protocol; no test-driven retuning. Every non-baseline candidate still falls back on 82 and 57 evaluated fixtures respectively.

{chr(10).join(table)}

Ratings31 now slightly improves the 2025/26 point estimate (delta -0.000234101, interval [-0.000864313, +0.000220922]), while still worsening 2024/25 (+0.002474969, interval [+0.000271338, +0.004412987]). No candidate improves both seasons. These remain reused historical evaluations, not an untouched test or promotion evidence.

The hypothetical absence problem also remains. In the same Arsenal-Nottingham Forest example, substituting role-replacement exposure for Rice raises predicted home-win probability from 64.6026% to 66.3295%. The own home-player coefficient remains negative (-0.25732 in the 2025/26 ratings31 fit). This is not an injury claim; it demonstrates that a corrected feasible input still does not establish causal player value. Do not deploy this proxy for absence adjustments.

## Offline persistence precision

The unchanged SQL schema stores goal rates as `numeric(7,4)`, headline H/D/A probabilities as `numeric(8,7)`, and score grids as JSONB. Full Python precision does not survive those scalar database columns. No migration or database round trip was attempted.

The documented tolerance contract is: local headline/grid agreement within 2e-12; stored headline versus full JSONB grid mass within 5.0002e-8 per outcome; rounded headline sum within 1.50001e-7 (the SQL constraint allows 1e-6). Decimal half-up emulation over 1,752 actual historical rate pairs gives maximum headline error {capacity['max_headline_rounding_error']:.10g} and sum error {capacity['max_rounded_probability_sum_error']:.10g}. Rebuilding a grid from four-decimal stored rates changes H/D/A by as much as {capacity['max_regenerated_result_error_from_four_decimal_rates']:.10g}, so stored explicit score grids must be used when reproducing persisted forecasts. The simulator's existing normalized-headline alignment is retained and was exercised with emulated rounded columns.

These are offline numeric emulations, not certification of JSONB/PostgREST storage behavior. A real authorized database round trip remains pending before integration; no exact post-write equality is claimed.

## Offline payload and consumer capacity

Score dictionaries grow approximately 4.5x: this run's default JSON serialization measures {capacity['historical_score_dict_bytes']['legacy']:,} to {capacity['historical_score_dict_bytes']['adaptive']:,} bytes (4.52x); the independent review's compact serialization measured 4.54x. Median support is 324 cells; maximum 729 on the historical rate sample. Serialization choice changes byte totals, not the growth concern.

The actual existing 17 Sep frozen snapshot has **{snapshot['fixture_count']:,} remaining fixtures**. Replacing grids in memory expands the whole indented JSON from **{snapshot['original_file_bytes']:,} to {snapshot['adaptive_in_memory_bytes']:,} bytes** ({snapshot['file_ratio']:.2f}x), or {snapshot['adaptive_gzip_bytes']:,} bytes gzip. The original file is byte-identical afterward. No 2026/27 results were read or scored.

Its seven-day horizon contains **{snapshot['scoring_horizon_fixtures']} fixtures**; serialized row bodies are **{snapshot['horizon_row_body_bytes_excluding_model_run_id']:,} bytes**, excluding model-run-ID overhead. The local path currently submits that slate in one upsert; no byte-budget batching is configured. The ledger fetches up to 1,000 rows with their grids per page. The inspected SQL has no JSONB cell/byte limit, and the static model-review dashboard omits score grids, but service response/request limits are not established by those facts.

Local grid construction took {snapshot['grid_build_seconds']:.3f}s, JSON serialization {snapshot['json_serialize_seconds']:.3f}s, parsing {snapshot['json_parse_seconds_under_tracemalloc']:.3f}s with {snapshot['json_parse_peak_bytes']:,} traced peak bytes, and actual simulator fixture preparation {snapshot['simulation_prepare_seconds_under_tracemalloc']:.3f}s with {snapshot['simulation_prepare_peak_bytes']:,} traced peak bytes. Parsing/preparation timings include tracing overhead; this is one desktop run, not deployed end-to-end latency or a 10,000-simulation benchmark. DB storage/TOAST, transport compression and gateway capacity remain unverified. No capacity setting was silently changed.

## Deliverables and pending integration checks

- `artifacts/soccer_research_players_20261014_v3/`: new versioned feasible plans, replacement pools, membership evidence and feature rows.
- `artifacts/soccer_research_player_models_20261014_v3/`: protocol, eight fold models, four final models, predictions, metrics/calibration/uncertainty and validation.
- `artifacts/soccer_research_repair_20261014/`: old evidence hashes, exact replay/preservation proof, numeric/payload audit and updated probability/metric review patch.
- `pipeline/tools/verify_player_repair_evidence.py`, `validate_local_player_strength.py` and `audit_score_persistence_offline.py`: repeatable offline checks. Current scenario and experiment tools require v3; the v2 source/code snapshots and Git revision remain available for old evidence.

Remaining limitations are the existing missing source/usage records, historical publication vintages, injury/lineup and transaction timestamps, and unvalidated causal player impact. Future frozen evaluation remains reserved and unchanged. Before any integration, review only scoped hunks against the operational worktree, verify an authorized DB precision round trip and deployed payload limits, and keep research model selection separate from the already reviewed numerical probability repair. No action was denied or left with an uncertain write outcome.
'''
    (destination/'README.md').write_text(text,encoding='utf-8',newline='\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('output','old-output','repair','destination'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    write(args.output,args.old_output,args.repair,args.destination)
