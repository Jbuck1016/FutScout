-- Historical sequences live apart from the current-season analytics table.
-- A live rebuild may TRUNCATE public.sequences, so historical data must not
-- be stored there. This copies the same deterministic sequence definition but
-- reads the archived raw events.
create table if not exists public.ml_historical_sequences
  (like public.sequences including all);
create index if not exists ml_historical_sequences_game_id_idx
  on public.ml_historical_sequences (game_id);
-- The existing sequence builder does not insert league; the batch stamps it
-- from matches before the transaction commits.
alter table public.ml_historical_sequences alter column league drop not null;
alter table public.ml_historical_sequences enable row level security;
revoke all on public.ml_historical_sequences from public, anon, authenticated;
grant select, insert, update, delete on public.ml_historical_sequences to service_role;

do $clone$
declare source_definition text;
begin
  select pg_get_functiondef(p.oid) into source_definition
  from pg_proc p join pg_namespace n on n.oid=p.pronamespace
  where n.nspname='public' and p.proname='build_sequences_for'
    and pg_get_function_arguments(p.oid)='p_game_ids text[]';
  if source_definition is null
     or position('from public.events' in source_definition)=0
     or position('insert into public.sequences' in source_definition)=0 then
    raise exception 'Unexpected build_sequences_for definition; refuse historical clone';
  end if;
  source_definition:=replace(source_definition,
    'public.build_sequences_for','public.ml_build_historical_sequences_for');
  source_definition:=replace(source_definition,
    'insert into public.sequences','insert into public.ml_historical_sequences');
  source_definition:=replace(source_definition,
    'from public.events','from public.events_archive');
  -- WhoScored event_id is not unique across the two teams. The live builder's
  -- ORDER BY can tie on period/minute/second/event_id; RANGE then assigns both
  -- sides the same sequence number. ws_id is unique per match and supplies a
  -- deterministic final key to every window/order in the cloned builder.
  if position('game_id, period, expanded_minute, second, event_id,'
              in source_definition)=0 then
    raise exception 'Historical sequence clone cannot locate event ordering';
  end if;
  source_definition:=replace(source_definition,
    'game_id, period, expanded_minute, second, event_id,',
    'game_id, period, expanded_minute, second, event_id, ws_id,');
  source_definition:=replace(source_definition,
    'period,expanded_minute,second,event_id desc',
    'period,expanded_minute,second,event_id desc,ws_id desc');
  source_definition:=replace(source_definition,
    'period desc,expanded_minute desc,second desc,event_id desc',
    'period desc,expanded_minute desc,second desc,event_id desc,ws_id desc');
  source_definition:=replace(source_definition,
    'period,expanded_minute,second,event_id',
    'period,expanded_minute,second,event_id,ws_id');
  execute source_definition;
end $clone$;
revoke all on function public.ml_build_historical_sequences_for(text[])
  from public, anon, authenticated;
grant execute on function public.ml_build_historical_sequences_for(text[])
  to service_role;

create or replace function public.ml_backfill_historical_sequence_batch(
  p_season text, p_limit integer default 4
)
returns jsonb language plpgsql security invoker
set search_path to 'public','pg_temp'
set statement_timeout to '110s'
as $batch$
declare ids text[]; n integer; total integer;
begin
  if p_season not in ('2324','2425','2526') or p_limit not between 1 and 8 then
    raise exception 'Unsupported season or batch size';
  end if;
  if not pg_try_advisory_xact_lock(hashtextextended('ml-historical-sequences',0)) then
    return jsonb_build_object('status','busy');
  end if;
  select array_agg(game_id) into ids from (
    select m.game_id from public.matches m
    join public.archive_match_manifest a on a.game_id=m.game_id
      and a.season=p_season and a.verified_at is not null
    where m.season=p_season
      and m.league in ('ENG-Premier League','ESP-La Liga','ITA-Serie A',
                       'GER-Bundesliga','FRA-Ligue 1')
      and m.home_score is not null and m.away_score is not null
      and exists (select 1 from public.events_archive e where e.game_id=m.game_id)
      and not exists (select 1 from public.ml_historical_sequences s
                      where s.game_id=m.game_id)
    order by m.game_id limit p_limit
  ) missing;
  if ids is null then
    return jsonb_build_object('status','complete','season',p_season,'games',0);
  end if;
  perform public.ml_build_historical_sequences_for(ids);
  update public.ml_historical_sequences s set league=m.league
    from public.matches m
    where s.game_id=m.game_id and s.game_id=any(ids)
      and s.league is distinct from m.league;
  select count(distinct game_id),count(*) into n,total
    from public.ml_historical_sequences where game_id=any(ids);
  if n<>array_length(ids,1) then
    raise exception 'Historical sequence coverage mismatch: % of % games',
      n,array_length(ids,1);
  end if;
  if exists (select 1 from public.ml_historical_sequences
             where game_id=any(ids) and league is null) then
    raise exception 'Historical sequences were not league-stamped';
  end if;
  return jsonb_build_object('status','progress','season',p_season,
    'games',n,'sequences',total,'game_ids',ids);
end $batch$;
revoke all on function public.ml_backfill_historical_sequence_batch(text,integer)
  from public, anon, authenticated;
grant execute on function public.ml_backfill_historical_sequence_batch(text,integer)
  to service_role;
notify pgrst, 'reload schema';
