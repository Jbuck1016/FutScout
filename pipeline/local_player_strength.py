"""Prior-date player performance and expected-usage changes for offline research.

Individual ratings are shrunk historical provider performance proxies, not causal
player goal contributions. The downstream goal model learns their conditional
team-level association. Target-game participants are never prediction inputs.
"""
from collections import defaultdict, deque
from datetime import date
import math

import numpy as np

VERSION = 'lagged-player-performance-usage-v3'
PRIOR_MINUTES = 900.0
USAGE_WEIGHTS = (0.5, 0.3, 0.2)


def position_group(position):
    if position == 'GK':
        return 'GK'
    if position.startswith(('D', 'WB')):
        return 'D'
    if position.startswith(('M', 'AM')):
        return 'M'
    if position.startswith(('F', 'S')) and position != 'Sub':
        return 'F'
    return 'unknown'


def extract_usage(payload, side, match):
    players = payload[side]['players']
    by_id = {str(p['playerId']):p for p in players}
    if len(by_id) != len(players):
        raise ValueError('duplicate player IDs')
    if sum(bool(p.get('isFirstEleven')) for p in players) != 11:
        raise ValueError('starting XI missing or not eleven')
    ends = [e for e in payload['events'] if (e.get('type') or {}).get('displayName') == 'End'
            and (e.get('period') or {}).get('displayName') == 'SecondHalf']
    if not ends:
        raise ValueError('second-half end missing')
    duration = max(float(e['expandedMinute']) + float(e.get('second') or 0)/60 for e in ends)
    if not 85 <= duration <= 135:
        raise ValueError('unexpected regulation duration')
    reds = {}
    for event in payload['events']:
        if (event.get('cardType') or {}).get('displayName') in ('Red','SecondYellow') and event.get('playerId'):
            reds[str(event['playerId'])] = float(event['expandedMinute']) + float(event.get('second') or 0)/60
    goalkeeper_ids=set()
    for formation in payload[side].get('formations',[]):
        if float(formation.get('endMinuteExpanded',duration)) <= float(formation.get('startMinuteExpanded',0)):
            continue
        for pid,slot in zip(formation.get('playerIds',[]),formation.get('formationSlots',[])):
            if slot==1:
                goalkeeper_ids.add(str(pid))
    result=[]
    for player in players:
        player_id=str(player['playerId'])
        starter=bool(player.get('isFirstEleven'))
        start=0.0 if starter else player.get('subbedInExpandedMinute')
        if start is None:
            continue
        end=min(float(player.get('subbedOutExpandedMinute',duration)),reds.get(player_id,duration),duration)
        if not 0 <= float(start) <= end:
            raise ValueError('invalid player interval')
        minutes=(end-float(start))*90/duration
        if minutes <= 0:
            continue
        role='GK' if player_id in goalkeeper_ids else position_group(player['position'])
        previous=player
        visited={player_id}
        # A substitute's nominal role comes from the player replaced in this
        # completed historical match. It is explicitly only a role proxy.
        while role == 'unknown' and previous.get('subbedOutPlayerId'):
            prior_id=str(previous['subbedOutPlayerId'])
            if prior_id in visited or prior_id not in by_id:
                break
            visited.add(prior_id); previous=by_id[prior_id]
            role=position_group(previous['position'])
        ratings=player.get('stats',{}).get('ratings',{})
        rating=float(ratings[max(ratings,key=lambda k:float(k))]) if ratings else None
        if rating is not None and (not math.isfinite(rating) or not 0 <= rating <= 10):
            raise ValueError('invalid final retrospective player rating')
        result.append({'player_id':player_id,'name':player['name'],'role':role,
                       'minutes_equivalent90':minutes,'starter':starter,'rating':rating})
    total=sum(p['minutes_equivalent90'] for p in result)
    if not 810 <= total <= 990.1:
        raise ValueError(f'player minute conservation failed: {total}')
    if sum(p['minutes_equivalent90'] for p in result if p['role']=='GK') < 70:
        raise ValueError('goalkeeper role coverage insufficient')
    return {'game_id':match['game_id'],'match_date':match['match_date'],'league':match['league'],
            'season':match['season'],'team':match['team'] if side=='home' else match['opponent'],
            'is_home':side=='home','duration_expanded_minutes':duration,'players':result,
            'team_minutes_equivalent90':total,'role_method':'formation goalkeeper slot; otherwise starter position or replaced player role proxy',
            'quality_status':'complete'}


def mixture(history, weights=None):
    """Average exposure/990 without inflating players after dismissals.

    Missing exposure remains unallocated. A convex combination of valid observed
    equivalent-90 exposures cannot exceed 90 for any named player.
    """
    result=defaultdict(float)
    if not history:
        return {}
    weights=np.ones(len(history)) if weights is None else np.array(weights[:len(history)],dtype=float)
    if len(weights)!=len(history) or not np.isfinite(weights).all() or (weights<0).any() or weights.sum()<=0:
        raise ValueError('invalid mixture weights')
    weights=weights/weights.sum()
    for match,weight in zip(reversed(history),weights):
        if len({p['player_id'] for p in match['players']})!=len(match['players']):
            raise ValueError('duplicate historical player')
        for player in match['players']:
            minutes=float(player['minutes_equivalent90'])
            if not math.isfinite(minutes) or not 0<=minutes<=90:
                raise ValueError('historical exposure outside [0,90]')
            result[player['player_id']]+=float(weight)*minutes/990
    return dict(result)


def role_bucket(role):
    return 'GK' if role=='GK' else 'outfield' if role in ('D','M','F') else None


def feasible_allocation(shares, roles):
    """Only reduce exposure to role budgets; leave all deficits as replacement."""
    if any(not math.isfinite(v) or v<0 or v*990>90+1e-10 for v in shares.values()):
        raise ValueError('invalid individual allocation share')
    allocated={pid:share for pid,share in shares.items() if role_bucket(roles.get(pid)) is not None and share>0}
    pools={}
    for bucket,budget in (('GK',90.),('outfield',900.)):
        ids=[pid for pid in allocated if role_bucket(roles.get(pid))==bucket]
        used=math.fsum(allocated[pid]*990 for pid in ids)
        factor=min(1.,budget/used) if used else 1.
        for pid in ids:
            allocated[pid]*=factor
        pools[bucket]=max(0.,budget-math.fsum(allocated[pid]*990 for pid in ids))
    validate_lineup({pid:v*990 for pid,v in allocated.items()},roles,math.fsum(pools.values()),pools)
    return allocated,pools


def validate_lineup(minutes_by_player, roles, replacement_minutes=0, replacement_by_role=None):
    """Finite named-player [0,90], GK=90, outfield=900 and team=990 budgets."""
    if not math.isfinite(replacement_minutes) or not 0<=replacement_minutes<=990:
        raise ValueError('invalid replacement minutes')
    used={'GK':0.,'outfield':0.}
    for pid,minutes in minutes_by_player.items():
        if not math.isfinite(minutes) or not 0<=minutes<=90+1e-10:
            raise ValueError('individual minutes must be finite and in [0,90]')
        bucket=role_bucket(roles.get(pid))
        if bucket is None:
            raise ValueError('unknown named-player role; use the explicit replacement pool')
        used[bucket]+=minutes
    total=math.fsum(minutes_by_player.values())+replacement_minutes
    if not math.isfinite(total) or abs(total-990)>1e-6:
        raise ValueError('scenario must account for 990 equivalent player-minutes')
    deficits={bucket:budget-used[bucket] for bucket,budget in (('GK',90.),('outfield',900.))}
    if any(v < -1e-6 for v in deficits.values()):
        raise ValueError('goalkeeper/outfield budget exceeded')
    pools={k:max(0.,v) for k,v in deficits.items()} if replacement_by_role is None else replacement_by_role
    if set(pools)!={'GK','outfield'} or any(not math.isfinite(v) or v<0 for v in pools.values()):
        raise ValueError('invalid role replacement pool')
    if abs(math.fsum(pools.values())-replacement_minutes)>1e-6 or any(abs(pools[k]-deficits[k])>1e-6 for k in pools):
        raise ValueError('replacement roles do not reconcile')
    return dict(pools)


def lineup_value(minutes_by_player, ratings, replacement_minutes=0, *, roles=None, replacement_by_role=None):
    """Explicit scenario accounting: unknown/replacement slots have zero excess.

    Minutes are scenario assumptions, not learned availability. Caller must supply
    only ratings known at the requested cutoff. Returns an average excess rating,
    not a goal prediction. A full team has 990 equivalent player-minutes.
    """
    roles=roles if roles is not None else {pid:r.get('role') for pid,r in ratings.items()}
    validate_lineup(minutes_by_player,roles,replacement_minutes,replacement_by_role)
    if any(not math.isfinite(ratings.get(pid,{}).get('excess_rating',0.)) for pid in minutes_by_player):
        raise ValueError('non-finite player rating')
    return sum(minutes/990*ratings.get(pid,{}).get('excess_rating',0.0)
               for pid,minutes in minutes_by_player.items())


def scenario_delta(plan, minutes_by_player, cutoff_date, replacement_minutes=0, replacement_by_role=None):
    """Explicit hypothetical lineup delta for use with the fitted team model."""
    if plan['cutoff_date'] != cutoff_date:
        raise ValueError('scenario must use the exact saved prediction cutoff')
    if any(r['rating_fit_through'] >= cutoff_date for r in plan['ratings'].values()):
        raise ValueError('scenario rating violates cutoff')
    if plan.get('version')!=VERSION:
        raise ValueError('scenario requires a v3 feasible allocation plan')
    for pid,minutes in minutes_by_player.items():
        membership=plan['membership_evidence'].get(pid)
        if minutes>0 and (membership is None or membership['teams']!=[plan['team']] or membership['observed_date']>=cutoff_date):
            raise ValueError('named player lacks prior-only membership evidence for this club')
    roles=plan['roles']
    reference_pool=plan['reference_replacement_by_role']
    reference=lineup_value(plan['reference_minutes'],plan['ratings'],math.fsum(reference_pool.values()),roles=roles,replacement_by_role=reference_pool)
    pool=validate_lineup(minutes_by_player,roles,replacement_minutes,replacement_by_role)
    return {'rating_delta':lineup_value(minutes_by_player,plan['ratings'],replacement_minutes,roles=roles,replacement_by_role=pool)-reference,
            'evidence_type':'user-supplied hypothetical minutes; no availability claim',
            'unknown_player_minutes':sum(m for pid,m in minutes_by_player.items() if pid not in plan['ratings']),
            'replacement_minutes':replacement_minutes,'replacement_by_role':pool}


def build_features(targets, observations):
    observations_by_date=defaultdict(list)
    for row in observations:
        observations_by_date[row['match_date']].append(row)
    targets_by_date=defaultdict(list)
    for row in targets:
        targets_by_date[row['match_date']].append(row)
    team_history=defaultdict(lambda:deque(maxlen=10))
    player_history=defaultdict(lambda:deque(maxlen=20))
    player_role={}
    membership={}
    role_samples=defaultdict(list)
    feature_rows=[]; plans=[]
    for day in sorted(set(targets_by_date)|set(observations_by_date)):
        references={role:(float(np.average([r for r,m in samples],weights=[m for r,m in samples])),
                          float(np.quantile([r for r,m in samples],.25)),
                          float(np.var([r for r,m in samples])))
                    for role,samples in role_samples.items() if len(samples)>=20}
        for target in targets_by_date[day]:
            for is_home in (True,False):
                team=target['team'] if is_home else target['opponent']
                all_history=list(team_history[(target['league'],team)])
                missing_history=any(r['quality_status']!='complete' for r in all_history)
                history=[r for r in all_history if r['quality_status']=='complete']
                raw_expected=mixture(history[-3:],USAGE_WEIGHTS)
                raw_reference=mixture(history)
                candidate_ids=set(raw_expected)|set(raw_reference)
                roles={pid:player_role.get(pid,'unknown') for pid in candidate_ids}
                evidence={pid:membership[pid] for pid in candidate_ids if pid in membership}
                removed={pid:share*990 for pid,share in raw_expected.items()
                         if pid not in evidence or evidence[pid]['teams']!=[team]}
                expected,expected_pool=feasible_allocation({pid:w for pid,w in raw_expected.items() if pid not in removed},roles)
                reference,reference_pool=feasible_allocation(raw_reference,roles)
                ratings={}
                for pid in set(expected)|set(reference):
                    role=player_role.get(pid,'unknown'); samples=list(player_history[pid])
                    if role not in references or not samples:
                        continue
                    center,replacement,role_variance=references[role]
                    minutes=sum(m for r,m,d in samples)
                    rating=(sum(r*m for r,m,d in samples)+PRIOR_MINUTES*center)/(minutes+PRIOR_MINUTES)
                    ratings[pid]={'role':role,'rating':rating,'replacement_rating':replacement,
                                  'excess_rating':rating-replacement,'prior_minutes':minutes,
                                  'rating_fit_through':max(d for r,m,d in samples),
                                  'shrinkage_weight':minutes/(minutes+PRIOR_MINUTES),
                                  'approximate_rating_se':math.sqrt(max(role_variance,.01)/(1+minutes/90))}
                values={pid:r['excess_rating'] for pid,r in ratings.items()}
                expected_value=sum(w*values.get(pid,0) for pid,w in expected.items())
                reference_value=sum(w*values.get(pid,0) for pid,w in reference.items())
                coverage=sum(w for pid,w in expected.items() if pid in ratings)
                prior_date=history[-1]['match_date'] if history else None
                stale_days=(date.fromisoformat(day)-date.fromisoformat(prior_date)).days if prior_date else None
                valid=not missing_history and len(history)>=2 and coverage>=.8 and stale_days is not None and stale_days<=60
                scenarios=[]
                for match in history[-3:]:
                    allocation,_=feasible_allocation({pid:w for pid,w in mixture([match]).items()
                        if pid in evidence and evidence[pid]['teams']==[team]},roles)
                    scenarios.append(sum(w*values.get(pid,0) for pid,w in allocation.items()))
                row={'game_id':target['game_id'],'team':team,'is_home':is_home,'match_date':day,
                     'history_cutoff_date':prior_date,'source_game_ids':[r['game_id'] for r in all_history],
                     'missing_history':missing_history,
                     'history_matches':len(history),'rating_coverage':coverage,'ready':bool(valid),
                     'rating_delta':float(expected_value-reference_value) if valid else 0.0,
                     'expected_excess_rating':expected_value if history else None,
                     'reference_excess_rating':reference_value if history else None,
                     'usage_churn':.5*(sum(abs(expected.get(pid,0)-reference.get(pid,0)) for pid in set(expected)|set(reference))+
                                          sum(abs(expected_pool[k]-reference_pool[k])/990 for k in expected_pool)),
                     'unknown_replacement_minutes':math.fsum(expected_pool.values()),
                     'membership_removed_minutes':math.fsum(removed.values()),
                     'usage_scenario_sd':float(np.std(scenarios)) if scenarios else None,
                     'approximate_rating_se':math.sqrt(sum((w*ratings[pid]['approximate_rating_se'])**2 for pid,w in expected.items() if pid in ratings)),
                     'fallback_reason':None if valid else 'missing recent usage, insufficient history/rating coverage or stale usage',
                     'availability_evidence':'prior-match usage only; no timestamped injury/lineup report'}
                feature_rows.append(row)
                plans.append({'version':VERSION,'game_id':target['game_id'],'team':team,'cutoff_date':day,
                              'expected_minutes':{pid:w*990 for pid,w in expected.items()},
                              'reference_minutes':{pid:w*990 for pid,w in reference.items()},'ratings':ratings,
                              'roles':roles,'membership_evidence':evidence,'membership_removed_minutes':removed,
                              'expected_replacement_by_role':expected_pool,'reference_replacement_by_role':reference_pool,
                              'assumption':'last-three exposure weights 0.5/0.3/0.2; no upward normalization; GK/outfield caps 90/900; deficits explicitly unknown',
                              'replacement_assumption':'25th percentile of earlier role-match performance ratings; not market replacement value'})
        # Both target features and all same-date sides are emitted BEFORE any
        # actual participants, minutes, ratings or roles on that date are learned.
        day_membership=defaultdict(lambda:{'teams':set(),'source_game_ids':set()})
        for row in observations_by_date[day]:
            team_history[(row['league'],row['team'])].append(row)
            if row['quality_status']!='complete':
                continue
            for player in row['players']:
                pid=player['player_id']; role=player['role']; rating=player['rating']
                day_membership[pid]['teams'].add(row['team'])
                day_membership[pid]['source_game_ids'].add(row['game_id'])
                if role!='unknown':
                    player_role[pid]=role
                if rating is not None:
                    minutes=player['minutes_equivalent90']
                    player_history[pid].append((rating,minutes,day))
                    role_samples[role].append((rating,minutes))
        for pid,item in day_membership.items():
            membership[pid]={'teams':sorted(item['teams']),'source_game_ids':sorted(item['source_game_ids']),'observed_date':day}
    return feature_rows,plans
