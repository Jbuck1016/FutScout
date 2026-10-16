-- The existing v2 helper reads live events/sequences/xG only. Clone its
-- audited calculations against archive-safe sources; do not alter live RPCs.
-- Historical xG is deliberately empty until a point-in-time xG calibration
-- is built, so future-season goal outcomes cannot leak into backtests.
create table if not exists public.ml_historical_shot_xg (
  game_id text not null,ws_id text not null,team text not null,
  xg numeric not null,is_pen boolean not null,is_open_play boolean not null,
  model_version text not null,computed_at timestamptz not null default now(),
  primary key (game_id,ws_id)
);
create index if not exists ml_historical_shot_xg_game_idx
  on public.ml_historical_shot_xg (game_id);
alter table public.ml_historical_shot_xg enable row level security;
revoke all on public.ml_historical_shot_xg from public,anon,authenticated;
grant select,insert,update,delete on public.ml_historical_shot_xg to service_role;

do $clone$
declare source_definition text;
begin
  select pg_get_functiondef(p.oid) into source_definition
  from pg_proc p join pg_namespace n on n.oid=p.pronamespace
  where n.nspname='public' and p.proname='ml_v2_side_metrics';
  if source_definition is null
    or position('from public.events e join' in source_definition)=0
    or position('from public.sequences s join' in source_definition)=0
    or position('from public.mv_shot_xg x join' in source_definition)=0 then
    raise exception 'Unexpected ml_v2_side_metrics definition';
  end if;
  source_definition:=replace(source_definition,'public.ml_v2_side_metrics(',
    'public.ml_v2_side_metrics_historical(');
  source_definition:=replace(source_definition,'from public.events e join',
    'from public.events_archive e join');
  source_definition:=replace(source_definition,'from public.sequences s join',
    'from public.ml_historical_sequences s join');
  source_definition:=replace(source_definition,'from public.mv_shot_xg x join',
    'from public.ml_historical_shot_xg x join');
  execute source_definition;

  select pg_get_functiondef(p.oid) into source_definition
  from pg_proc p join pg_namespace n on n.oid=p.pronamespace
  where n.nspname='public'
    and p.proname='ml_backfill_team_match_observations_v2';
  if source_definition is null
    or position('public.ml_v2_side_metrics(' in source_definition)=0 then
    raise exception 'Unexpected v2 observation builder definition';
  end if;
  source_definition:=replace(source_definition,
    'public.ml_backfill_team_match_observations_v2(',
    'public.ml_backfill_team_match_observations_v2_historical(');
  source_definition:=replace(source_definition,'public.ml_v2_side_metrics(',
    'public.ml_v2_side_metrics_historical(');
  execute source_definition;
end $clone$;
revoke all on function public.ml_v2_side_metrics_historical(text,text,text[])
  from public,anon,authenticated;
grant execute on function public.ml_v2_side_metrics_historical(text,text,text[])
  to service_role;
revoke all on function public.ml_backfill_team_match_observations_v2_historical(text,text,text[])
  from public,anon,authenticated;
grant execute on function public.ml_backfill_team_match_observations_v2_historical(text,text,text[])
  to service_role;

create table if not exists public.ml_historical_v2_observation_backfill_done (
  game_id text primary key,
  season text not null,
  league text not null,
  completed_at timestamptz not null default now()
);
alter table public.ml_historical_v2_observation_backfill_done enable row level security;
revoke all on public.ml_historical_v2_observation_backfill_done
  from public,anon,authenticated;
grant select,insert,update,delete
  on public.ml_historical_v2_observation_backfill_done to service_role;

create or replace function public.ml_backfill_historical_v2_observation_batch(
  p_season text,p_limit integer default 4
)
returns jsonb language plpgsql security invoker
set search_path to 'public','pg_temp'
set statement_timeout to '110s'
as $batch$
declare ids text[]; selected_league text; inserted_rows bigint;
begin
  if p_season not in ('2324','2425','2526') or p_limit not between 1 and 8 then
    raise exception 'Unsupported season or batch size';
  end if;
  if not pg_try_advisory_xact_lock(hashtextextended('ml-historical-v2-observations',0)) then
    return jsonb_build_object('status','busy');
  end if;
  select m.league into selected_league from public.matches m
  join public.archive_match_manifest a on a.game_id=m.game_id
    and a.season=p_season and a.verified_at is not null
  where m.season=p_season
    and m.league in ('ENG-Premier League','ESP-La Liga','ITA-Serie A',
                     'GER-Bundesliga','FRA-Ligue 1')
    and exists(select 1 from public.ml_historical_sequences s
               where s.game_id=m.game_id)
    and not exists(select 1 from public.ml_historical_v2_observation_backfill_done d
                   where d.game_id=m.game_id)
  order by m.league,m.game_id limit 1;
  if selected_league is null then
    return jsonb_build_object('status','complete','season',p_season,'games',0);
  end if;
  select array_agg(game_id) into ids from (
    select m.game_id from public.matches m
    join public.archive_match_manifest a on a.game_id=m.game_id
      and a.season=p_season and a.verified_at is not null
    where m.season=p_season and m.league=selected_league
      and exists(select 1 from public.ml_historical_sequences s
                 where s.game_id=m.game_id)
      and not exists(select 1 from public.ml_historical_v2_observation_backfill_done d
                     where d.game_id=m.game_id)
    order by m.game_id limit p_limit
  ) missing;
  select public.ml_backfill_team_match_observations_v2_historical(
    p_season,selected_league,ids) into inserted_rows;
  if inserted_rows<>array_length(ids,1)*2 then
    raise exception 'Historical observation coverage mismatch: % of % sides',
      inserted_rows,array_length(ids,1)*2;
  end if;
  insert into public.ml_historical_v2_observation_backfill_done(game_id,season,league)
    select unnest(ids),p_season,selected_league;
  return jsonb_build_object('status','progress','season',p_season,
    'league',selected_league,'games',array_length(ids,1),
    'sides',inserted_rows,'game_ids',ids);
end $batch$;
revoke all on function public.ml_backfill_historical_v2_observation_batch(text,integer)
  from public,anon,authenticated;
grant execute on function public.ml_backfill_historical_v2_observation_batch(text,integer)
  to service_role;
notify pgrst,'reload schema';
