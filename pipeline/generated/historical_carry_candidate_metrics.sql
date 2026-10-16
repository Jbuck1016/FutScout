-- Match-level carry candidates, using the same receipt-to-next-action
-- definition as the live mv_receipt_events view. Unlike the current
-- sequence xT, this estimates xT gained while carrying the ball.
create table if not exists public.ml_historical_carry_candidates (
  game_id text not null,team text not null,season text not null,league text not null,
  carries integer not null,progressive_carries integer not null,
  carry_box_entries integer not null,carry_xt_net numeric not null,
  carry_xt_positive numeric not null,definition_version integer not null default 1,
  computed_at timestamptz not null default now(),
  primary key (game_id,team),
  check (carries>=0 and progressive_carries>=0 and carry_box_entries>=0)
);
create index if not exists ml_historical_carry_candidates_season_league_idx
  on public.ml_historical_carry_candidates(season,league);
alter table public.ml_historical_carry_candidates enable row level security;
revoke all on public.ml_historical_carry_candidates from public,anon,authenticated;
grant select,insert,update,delete on public.ml_historical_carry_candidates
  to service_role;

create or replace function public.ml_backfill_historical_carry_candidate_batch(
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
  if not pg_try_advisory_xact_lock(hashtextextended('ml-historical-carry-candidates',0)) then
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
      and not exists (select 1 from public.ml_historical_carry_candidates c
                      where c.game_id=m.game_id)
    order by m.game_id limit p_limit
  ) missing;
  if ids is null then
    return jsonb_build_object('status','complete','season',p_season,'games',0);
  end if;
  with ordered as (
    select e.game_id,e.team_id,e.player_id,e.x,e.y,e.minute,e.second,
      lag(e.team_id) over w as prev_team_id,
      lag(coalesce(e.end_x,e.x)) over w as start_x,
      lag(coalesce(e.end_y,e.y)) over w as start_y,
      lag(e.minute*60+e.second) over w as prev_sec
    from public.events_archive e
    where e.game_id=any(ids)
      and e.type not in ('Start','End','FormationSet','FormationChange',
        'Card','SubstitutionOn','SubstitutionOff','CornerAwarded',
        'OffsideGiven','OffsideProvoked')
    window w as (partition by e.game_id order by e.ws_id)
  ), carries as (
    select o.game_id,o.team_id,o.start_x,o.start_y,o.x,o.y,
      sqrt(power((o.x-o.start_x)*1.05,2)
        +power((o.y-o.start_y)*0.68,2)) as carry_m,
      sqrt(power((100-o.start_x)*1.05,2)
        +power((50-o.start_y)*0.68,2)) as d0,
      sqrt(power((100-o.x)*1.05,2)
        +power((50-o.y)*0.68,2)) as d1
    from ordered o
    where o.prev_team_id=o.team_id and o.player_id is not null
      and o.x is not null and o.y is not null
      and o.start_x is not null and o.start_y is not null
      and (o.minute*60+o.second)-o.prev_sec between 0 and 20
  ), sides as (
    select m.game_id,m.team,m.team_id,m.season,m.league
    from public.ml_match_team_map m
    where m.season=p_season and m.game_id=any(ids)
  ), summary as (
    select s.game_id,s.team,max(s.season) season,max(s.league) league,
      count(*) filter(where c.carry_m>=3)::integer carries,
      count(*) filter(where c.carry_m>=3 and c.d1<0.85*c.d0)::integer
        progressive_carries,
      count(*) filter(where c.carry_m>=3
        and c.x>=83 and c.y between 21 and 79
        and not(c.start_x>=83 and c.start_y between 21 and 79))::integer
        carry_box_entries,
      coalesce(round(sum(public.xt_val(c.x,c.y)
        -public.xt_val(c.start_x,c.start_y))
        filter(where c.carry_m>=3)::numeric,6),0) carry_xt_net,
      coalesce(round(sum(greatest(public.xt_val(c.x,c.y)
        -public.xt_val(c.start_x,c.start_y),0))
        filter(where c.carry_m>=3)::numeric,6),0) carry_xt_positive
    from sides s left join carries c
      on c.game_id=s.game_id and c.team_id=s.team_id
    group by s.game_id,s.team
  )
  insert into public.ml_historical_carry_candidates(
    game_id,team,season,league,carries,progressive_carries,
    carry_box_entries,carry_xt_net,carry_xt_positive
  ) select game_id,team,season,league,carries,progressive_carries,
    carry_box_entries,carry_xt_net,carry_xt_positive from summary
    on conflict (game_id,team) do nothing;
  get diagnostics inserted_rows=row_count;
  if inserted_rows<>array_length(ids,1)*2 then
    raise exception 'Historical carry coverage mismatch: % of % sides',
      inserted_rows,array_length(ids,1)*2;
  end if;
  return jsonb_build_object('status','progress','season',p_season,
    'games',array_length(ids,1),'sides',inserted_rows,'game_ids',ids);
end $batch$;
revoke all on function public.ml_backfill_historical_carry_candidate_batch(text,integer)
  from public,anon,authenticated;
grant execute on function public.ml_backfill_historical_carry_candidate_batch(text,integer)
  to service_role;
notify pgrst,'reload schema';
