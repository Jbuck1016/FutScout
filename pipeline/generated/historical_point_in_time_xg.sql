-- Point-in-time historical xG. Uses the live shot geometry/bin definitions,
-- but estimates each bin only from *earlier match dates*. The fixed 0.10
-- prior avoids future-season goal leakage in the first training season.
create table if not exists public.ml_historical_shot_context (
  game_id text not null,ws_id text not null,team text not null,
  season text not null,league text not null,match_date date not null,
  is_goal boolean not null,is_open_play boolean not null,is_pen boolean not null,
  is_header boolean not null,is_bigchance boolean not null,
  d_bin smallint not null,a_bin smallint not null,
  primary key(game_id,ws_id),
  check(d_bin between 1 and 6 and a_bin between 1 and 3)
);
create index if not exists ml_historical_shot_context_bin_date_idx
  on public.ml_historical_shot_context
    (d_bin,a_bin,is_header,is_bigchance,match_date);
create index if not exists ml_historical_shot_context_season_idx
  on public.ml_historical_shot_context(season,game_id);
alter table public.ml_historical_shot_context enable row level security;
revoke all on public.ml_historical_shot_context from public,anon,authenticated;
grant select,insert,update,delete on public.ml_historical_shot_context
  to service_role;

create or replace function public.ml_backfill_historical_shot_context(p_season text)
returns jsonb language plpgsql security invoker
set search_path to 'public','pg_temp'
set statement_timeout to '110s'
as $fn$
declare inserted_rows bigint;
begin
  if p_season not in ('2324','2425','2526') then
    raise exception 'Unsupported historical season';
  end if;
  with shots as (
    select e.game_id,e.ws_id::text ws_id,e.team,m.season,m.league,
      m.date match_date,coalesce(e.is_goal,false) is_goal,
      coalesce(e.is_open_play,false) is_open_play,
      coalesce(e.qualifiers @>
        '[{"type":{"displayName":"Penalty"}}]'::jsonb,false) is_pen,
      coalesce(e.qualifiers @>
        '[{"type":{"displayName":"Head"}}]'::jsonb,false) is_header,
      coalesce(e.qualifiers @>
        '[{"type":{"displayName":"BigChance"}}]'::jsonb,false) is_bigchance,
      sqrt(power((100-e.x)*1.05,2)+power((50-e.y)*0.68,2)) dist_m,
      degrees(case when
        power((100-e.x)*1.05,2)+power((e.y-50)*0.68,2)-power(3.66,2)<=0
        then pi() else atan(7.32*((100-e.x)*1.05)/
          (power((100-e.x)*1.05,2)+power((e.y-50)*0.68,2)-power(3.66,2)))
        end) angle_deg
    from public.events_archive e join public.matches m
      on m.game_id=e.game_id
    join public.archive_match_manifest a on a.game_id=m.game_id
      and a.season=p_season and a.verified_at is not null
    where m.season=p_season
      and m.league in ('ENG-Premier League','ESP-La Liga','ITA-Serie A',
                       'GER-Bundesliga','FRA-Ligue 1')
      and e.is_shot and e.x is not null and e.y is not null
      and not coalesce(e.qualifiers @>
        '[{"type":{"displayName":"OwnGoal"}}]'::jsonb,false)
  )
  insert into public.ml_historical_shot_context(
    game_id,ws_id,team,season,league,match_date,is_goal,is_open_play,
    is_pen,is_header,is_bigchance,d_bin,a_bin
  )
  select game_id,ws_id,team,season,league,match_date,is_goal,is_open_play,
    is_pen,is_header,is_bigchance,
    case when dist_m<6 then 1 when dist_m<11 then 2 when dist_m<16 then 3
      when dist_m<22 then 4 when dist_m<30 then 5 else 6 end,
    case when angle_deg<12 then 1 when angle_deg<25 then 2 else 3 end
  from shots on conflict(game_id,ws_id) do nothing;
  get diagnostics inserted_rows=row_count;
  return jsonb_build_object('season',p_season,'inserted',inserted_rows,
    'status','complete');
end $fn$;
revoke all on function public.ml_backfill_historical_shot_context(text)
  from public,anon,authenticated;
grant execute on function public.ml_backfill_historical_shot_context(text)
  to service_role;

create or replace function public.ml_score_historical_shot_xg(p_season text)
returns jsonb language plpgsql security invoker
set search_path to 'public','pg_temp'
set statement_timeout to '110s'
as $fn$
declare inserted_rows bigint;
begin
  if p_season not in ('2324','2425','2526') then
    raise exception 'Unsupported historical season';
  end if;
  if (select count(distinct season) from public.ml_historical_shot_context)<3 then
    raise exception 'All three source seasons must be loaded before xG scoring';
  end if;
  with daily as (
    select match_date,d_bin,a_bin,is_header,is_bigchance,
      count(*) filter(where not is_pen) n,
      count(*) filter(where not is_pen and is_goal) goals
    from public.ml_historical_shot_context
    group by match_date,d_bin,a_bin,is_header,is_bigchance
  ), prior as (
    select d.*,
      sum(n) over w prior_n,
      sum(goals) over w prior_goals
    from daily d
    window w as (partition by d_bin,a_bin,is_header,is_bigchance
      order by match_date rows between unbounded preceding and 1 preceding)
  )
  insert into public.ml_historical_shot_xg(
    game_id,ws_id,team,xg,is_pen,is_open_play,model_version
  )
  select c.game_id,c.ws_id,c.team,
    case when c.is_pen then 0.76 else
      round((coalesce(p.prior_goals,0)::numeric+2.0)/
            (coalesce(p.prior_n,0)::numeric+20.0),4) end,
    c.is_pen,c.is_open_play,'asof_bin_v1_prior20_base010'
  from public.ml_historical_shot_context c join prior p
    on p.match_date=c.match_date and p.d_bin=c.d_bin
    and p.a_bin=c.a_bin and p.is_header=c.is_header
    and p.is_bigchance=c.is_bigchance
  where c.season=p_season
  on conflict(game_id,ws_id) do update set
    xg=excluded.xg,is_pen=excluded.is_pen,
    is_open_play=excluded.is_open_play,
    model_version=excluded.model_version,computed_at=now();
  get diagnostics inserted_rows=row_count;
  return jsonb_build_object('season',p_season,'scored',inserted_rows,
    'status','complete','model_version','asof_bin_v1_prior20_base010');
end $fn$;
revoke all on function public.ml_score_historical_shot_xg(text)
  from public,anon,authenticated;
grant execute on function public.ml_score_historical_shot_xg(text)
  to service_role;
notify pgrst,'reload schema';
