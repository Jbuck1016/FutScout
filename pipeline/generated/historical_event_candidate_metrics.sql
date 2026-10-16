-- Point-in-time safe, event-derived candidate signals. These are match
-- observations, not automatically promoted model inputs. Raw qualifiers and
-- spatial coordinates are used; no future match outcomes train a feature.
create table if not exists public.ml_historical_event_candidates (
  game_id text not null,
  team text not null,
  season text not null,
  league text not null,
  raw_event_count integer not null,
  completed_progressive_passes integer not null,
  completed_final_third_entries integer not null,
  completed_box_entries integer not null,
  pass_xt_net numeric,
  pass_xt_positive numeric,
  high_ball_recoveries integer not null,
  high_defensive_actions integer not null,
  non_penalty_shots integer not null,
  non_penalty_box_shots integer not null,
  non_penalty_big_chances integer not null,
  non_penalty_mean_shot_distance_m numeric,
  definition_version integer not null default 1,
  computed_at timestamptz not null default now(),
  primary key (game_id,team),
  check (raw_event_count>0),
  check (completed_progressive_passes>=0 and completed_final_third_entries>=0
    and completed_box_entries>=0 and high_ball_recoveries>=0
    and high_defensive_actions>=0 and non_penalty_shots>=0
    and non_penalty_box_shots>=0 and non_penalty_big_chances>=0)
);
create index if not exists ml_historical_event_candidates_season_league_idx
  on public.ml_historical_event_candidates (season,league);
alter table public.ml_historical_event_candidates enable row level security;
revoke all on public.ml_historical_event_candidates from public,anon,authenticated;
grant select,insert,update,delete on public.ml_historical_event_candidates to service_role;

create or replace function public.ml_backfill_historical_event_candidate_batch(
  p_season text,p_limit integer default 4
)
returns jsonb language plpgsql security invoker
set search_path to 'public','pg_temp'
set statement_timeout to '110s'
as $batch$
declare ids text[]; inserted_rows integer;
begin
  if p_season not in ('2324','2425','2526') or p_limit not between 1 and 8 then
    raise exception 'Unsupported season or batch size';
  end if;
  if not pg_try_advisory_xact_lock(hashtextextended('ml-historical-event-candidates',0)) then
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
      and not exists (select 1 from public.ml_historical_event_candidates c
                      where c.game_id=m.game_id)
    order by m.game_id limit p_limit
  ) missing;
  if ids is null then
    return jsonb_build_object('status','complete','season',p_season,'games',0);
  end if;
  with events as (
    select m.game_id,m.team,m.season,m.league,e.type,e.outcome_type,
      e.x,e.y,e.end_x,e.end_y,e.is_shot,e.qualifiers,
      (e.type='Pass' and e.outcome_type='Successful'
       and e.x is not null and e.y is not null
       and e.end_x is not null and e.end_y is not null) as pass_ok,
      (e.is_shot and not coalesce(e.qualifiers @>
       '[{"type":{"displayName":"Penalty"}}]'::jsonb,false)
       and not coalesce(e.qualifiers @>
       '[{"type":{"displayName":"OwnGoal"}}]'::jsonb,false)) as np_shot
    from public.events_archive e join public.ml_match_team_map m
      on m.game_id=e.game_id and m.team_id=e.team_id
    where m.season=p_season and m.game_id=any(ids)
  ), summary as (
    select game_id,team,max(season) season,max(league) league,
      count(*)::integer raw_event_count,
      count(*) filter(where pass_ok and end_x-x>=10)::integer
        completed_progressive_passes,
      count(*) filter(where pass_ok and x<66.7 and end_x>=66.7)::integer
        completed_final_third_entries,
      count(*) filter(where pass_ok and x<83 and end_x>=83
        and end_y between 21.1 and 78.9)::integer completed_box_entries,
      round(sum(case when pass_ok then
        public.xt_val(end_x,end_y)-public.xt_val(x,y) end)::numeric,6) pass_xt_net,
      round(sum(case when pass_ok then greatest(
        public.xt_val(end_x,end_y)-public.xt_val(x,y),0) end)::numeric,6)
        pass_xt_positive,
      count(*) filter(where type='BallRecovery' and x>=66.7)::integer
        high_ball_recoveries,
      count(*) filter(where type in ('Tackle','Interception') and x>=50)::integer
        high_defensive_actions,
      count(*) filter(where np_shot)::integer non_penalty_shots,
      count(*) filter(where np_shot and x>=83
        and y between 21.1 and 78.9)::integer non_penalty_box_shots,
      count(*) filter(where np_shot and qualifiers @>
        '[{"type":{"displayName":"BigChance"}}]'::jsonb)::integer
        non_penalty_big_chances,
      round(avg(sqrt(power((100-x)*1.05,2)+power((50-y)*0.68,2)))
        filter(where np_shot and x is not null and y is not null)::numeric,3)
        non_penalty_mean_shot_distance_m
    from events group by game_id,team
  )
  insert into public.ml_historical_event_candidates (
    game_id,team,season,league,raw_event_count,
    completed_progressive_passes,completed_final_third_entries,
    completed_box_entries,pass_xt_net,pass_xt_positive,
    high_ball_recoveries,high_defensive_actions,non_penalty_shots,
    non_penalty_box_shots,non_penalty_big_chances,
    non_penalty_mean_shot_distance_m
  ) select game_id,team,season,league,raw_event_count,
    completed_progressive_passes,completed_final_third_entries,
    completed_box_entries,pass_xt_net,pass_xt_positive,
    high_ball_recoveries,high_defensive_actions,non_penalty_shots,
    non_penalty_box_shots,non_penalty_big_chances,
    non_penalty_mean_shot_distance_m
    from summary on conflict (game_id,team) do nothing;
  get diagnostics inserted_rows=row_count;
  if inserted_rows<>array_length(ids,1)*2 then
    raise exception 'Historical candidate coverage mismatch: % of % sides',
      inserted_rows,array_length(ids,1)*2;
  end if;
  return jsonb_build_object('status','progress','season',p_season,
    'games',array_length(ids,1),'sides',inserted_rows,'game_ids',ids);
end $batch$;
revoke all on function public.ml_backfill_historical_event_candidate_batch(text,integer)
  from public,anon,authenticated;
grant execute on function public.ml_backfill_historical_event_candidate_batch(text,integer)
  to service_role;
notify pgrst,'reload schema';
