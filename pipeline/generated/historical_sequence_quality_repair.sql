-- Targeted repair for games whose archived-event pass xT and sequence xT
-- disagree. A provider event_id tie can otherwise merge both sides into one
-- possession. Only a mismatched, verified match is changed, and the rebuilt
-- result is checked in the same transaction.
create or replace function public.ml_historical_sequence_xt_mismatches(p_season text)
returns table(game_id text,team text,event_xt numeric,sequence_xt numeric,gap numeric)
language sql security invoker set search_path=''
as $fn$
with seq as (
  select s.game_id,m.team,round(sum(s.xt_sum),6) as xt
  from public.ml_historical_sequences s
  join public.ml_match_team_map m
    on m.game_id=s.game_id and m.team_id=s.team_id
  where m.season=p_season
  group by s.game_id,m.team
)
select c.game_id,c.team,c.pass_xt_net,s.xt,
  round(c.pass_xt_net-s.xt,6) gap
from public.ml_historical_event_candidates c
left join seq s on s.game_id=c.game_id and s.team=c.team
where c.season=p_season
  and (s.xt is null or abs(c.pass_xt_net-s.xt)>0.01)
order by c.game_id,c.team;
$fn$;
revoke all on function public.ml_historical_sequence_xt_mismatches(text)
  from public,anon,authenticated;
grant execute on function public.ml_historical_sequence_xt_mismatches(text)
  to service_role;

create or replace function public.ml_historical_sequence_pass_mismatches(
  p_season text,p_league text
)
returns table(game_id text,team_id text,event_passes bigint,sequence_passes bigint)
language sql security invoker set search_path=''
as $fn$
with ev as (
  select m.game_id,m.team_id,count(*) as n
  from public.events_archive e join public.ml_match_team_map m
    on m.game_id=e.game_id and m.team_id=e.team_id
  where m.season=p_season and m.league=p_league and e.type='Pass'
  group by m.game_id,m.team_id
), seq as (
  select s.game_id,s.team_id,sum(s.n_pass) as n
  from public.ml_historical_sequences s join public.ml_match_team_map m
    on m.game_id=s.game_id and m.team_id=s.team_id
  where m.season=p_season and m.league=p_league
  group by s.game_id,s.team_id
)
select coalesce(ev.game_id,seq.game_id),coalesce(ev.team_id,seq.team_id),
  coalesce(ev.n,0),coalesce(seq.n,0)
from ev full join seq using(game_id,team_id)
where coalesce(ev.n,0)<>coalesce(seq.n,0)
order by 1,2;
$fn$;
revoke all on function public.ml_historical_sequence_pass_mismatches(text,text)
  from public,anon,authenticated;
grant execute on function public.ml_historical_sequence_pass_mismatches(text,text)
  to service_role;

create or replace function public.ml_repair_historical_sequence_game(p_game_id text)
returns jsonb language plpgsql security invoker
set search_path to 'public','pg_temp'
set statement_timeout to '110s'
as $fn$
declare match_league text; match_season text; mismatches integer; pass_mismatches integer;
begin
  select m.league,m.season into match_league,match_season
  from public.matches m join public.archive_match_manifest a
    on a.game_id=m.game_id and a.verified_at is not null
  where m.game_id=p_game_id and m.season in ('2324','2425','2526')
    and m.league in ('ENG-Premier League','ESP-La Liga','ITA-Serie A',
                     'GER-Bundesliga','FRA-Ligue 1');
  if match_season is null then
    raise exception 'Not a verified historical training match: %',p_game_id;
  end if;
  select count(*) into mismatches
  from public.ml_historical_event_candidates c
  left join (select m.team,round(sum(s.xt_sum),6) xt
             from public.ml_historical_sequences s
             join public.ml_match_team_map m
               on m.game_id=s.game_id and m.team_id=s.team_id
             where s.game_id=p_game_id group by m.team) s on s.team=c.team
  where c.game_id=p_game_id
    and (s.xt is null or abs(c.pass_xt_net-s.xt)>0.01);
  select count(*) into pass_mismatches from (
    select m.team_id,count(*) n from public.events_archive e
    join public.ml_match_team_map m
      on m.game_id=e.game_id and m.team_id=e.team_id
    where e.game_id=p_game_id and e.type='Pass' group by m.team_id
  ) ev full join (
    select team_id,sum(n_pass) n from public.ml_historical_sequences
    where game_id=p_game_id group by team_id
  ) seq using(team_id)
  where coalesce(ev.n,0)<>coalesce(seq.n,0);
  if mismatches=0 and pass_mismatches=0 then
    return jsonb_build_object('status','not_needed','game_id',p_game_id);
  end if;
  delete from public.ml_historical_sequences where game_id=p_game_id;
  perform public.ml_build_historical_sequences_for(array[p_game_id]);
  update public.ml_historical_sequences set league=match_league
    where game_id=p_game_id;
  select count(*) into mismatches
  from public.ml_historical_event_candidates c
  left join (select m.team,round(sum(s.xt_sum),6) xt
             from public.ml_historical_sequences s
             join public.ml_match_team_map m
               on m.game_id=s.game_id and m.team_id=s.team_id
             where s.game_id=p_game_id group by m.team) s on s.team=c.team
  where c.game_id=p_game_id
    and (s.xt is null or abs(c.pass_xt_net-s.xt)>0.01);
  select count(*) into pass_mismatches from (
    select m.team_id,count(*) n from public.events_archive e
    join public.ml_match_team_map m
      on m.game_id=e.game_id and m.team_id=e.team_id
    where e.game_id=p_game_id and e.type='Pass' group by m.team_id
  ) ev full join (
    select team_id,sum(n_pass) n from public.ml_historical_sequences
    where game_id=p_game_id group by team_id
  ) seq using(team_id)
  where coalesce(ev.n,0)<>coalesce(seq.n,0);
  if mismatches<>0 or pass_mismatches<>0 then
    raise exception 'Sequence mismatch persists for %: xT %, passes %',
      p_game_id,mismatches,pass_mismatches;
  end if;
  return jsonb_build_object('status','repaired','game_id',p_game_id);
end $fn$;
revoke all on function public.ml_repair_historical_sequence_game(text)
  from public,anon,authenticated;
grant execute on function public.ml_repair_historical_sequence_game(text)
  to service_role;
notify pgrst,'reload schema';
