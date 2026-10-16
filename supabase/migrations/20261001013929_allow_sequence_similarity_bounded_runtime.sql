-- PostgREST's short statement limit intermittently cancels the 110k-row
-- nearest-sequence scan under concurrent analytics work (SQLSTATE 57014).
-- Scope the longer budget to this read-only RPC; do not relax it for other
-- public queries. The browser retries once only for transient failures.
alter function public.similar_sequences(text, integer)
  set statement_timeout = '8s';
