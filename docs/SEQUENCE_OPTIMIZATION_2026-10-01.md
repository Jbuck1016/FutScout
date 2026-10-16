# Sequence similarity optimization — 2026-10-01

## Delivered
User approved replacing public.similar_sequences(text,integer). Production migration 20261001183221_optimize_similar_sequences_top_n applied successfully. No data, model, schedule, scraper, authentication or materialized-view refresh changes.

Exact 14-dimensional numeric distance formula retained. Inner ORDER BY unrounded distance, seq_uid LIMIT p_n precedes row_number. Exact ties now resolve deterministically by sequence ID; prior tie order was unspecified. Function signature/default10, STABLE, security invoker, search_path public/pg_temp, eight-second statement timeout and complete existing ACL verified unchanged. A definition-equality guard prevented overwriting concurrent function changes.

## Tests
- Three real seeds (1983549-73,1995397-92,1980894-238), 12 neighbours each: zero differences across all eight columns before deployment; all36 deployed rows match saved expected values after numeric transport normalization.
- Synthetic exact-distance cutoff ties choose a,b; same-game row excluded; 1.0001 precedes1.0002 despite equal rounded display; NULL limit returns all eligible synthetic rows; zero and absent seed return none.
- Actual deployed default count10, zero count0, absent seed count0.
- SQL diagnostic wrapper initially had missing column aliases and trailing semicolon, corrected before migration. Initial JavaScript postcheck compared numeric SQL strings with JSON numbers; normalized numeric columns and independently SQL EXCEPT-checked first seed: zero differences. No database regression found.

## Timings
Bounded read-only EXPLAIN ANALYZE, 8s timeout, one paired run per seed, 12 neighbours. Original body compared with deployed RPC. Not a controlled load test or p95.

| Seed | Original ms | Deployed ms | Improvement |
|---|---:|---:|---:|
|1983549-73|1716.952|1340.861|21.9%|
|1995397-92|1636.174|1341.379|18.0%|
|1980894-238|1619.203|1617.125|0.1%|

Earlier overnight samples showed15–17%. Current run demonstrates variable gains, not a guaranteed speedup. Further work would require more representative repeated timings before claiming tail-latency improvement.

## Recovery and evidence
- pipeline/generated/rollback_similar_sequences_top_n.sql: exact previous function; apply only for regression recovery.
- pipeline/generated/optimize_similar_sequences_top_n.sql: replacement definition.
- pipeline/tools/check_similar_sequences_top_n.sql: read-only synthetic regression.
- artifacts/model_reports/sequence_optimization_2026-10-01.json: paired plans and saved neighbour checks.
- Migration filename uses actual server-generated version from migration history. Local Supabase CLI unavailable; npx --no-install attempt failed on restricted npm network/cache access. Used approved Supabase migration tool, not an invented timestamp.

Security advisors checked after deployment; findings include other database objects. No broad security remediation included. Supabase skill required preserving security context and performance guidance required measured plans rather than assumed speedups.

