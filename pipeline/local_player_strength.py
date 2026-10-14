"""Prior-date player performance and expected-usage changes for offline research.

Individual ratings are shrunk historical provider performance proxies, not causal
player goal contributions. The downstream goal model learns their conditional
team-level association. Target-game participants are never prediction inputs.
"""
from collections import defaultdict, deque
from datetime import date
import math

import numpy as np

VERSION = 'lagged-player-performance-usage-v2'
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
    result=defaultdict(float)
    if not history:
        return {}
    weights=np.ones(len(history)) if weights is None else np.array(weights[:len(history)],dtype=float)
    weights=weights/weights.sum()
    for match,weight in zip(reversed(history),weights):
        total=sum(p['minutes_equivalent90'] for p in match['players'])
        for player in match['players']:
            result[player['player_id']]+=float(weight)*player['minutes_equivalent90']/total
    return dict(result)


def lineup_value(minutes_by_player, ratings, replacement_minutes=0):
    """Explicit scenario accounting: unknown/replacement slots have zero excess.

    Minutes are scenario assumptions, not learned availability. Caller must supply
    only ratings known at the requested cutoff. Returns an average excess rating,
    not a goal prediction. A full team has 990 equivalent player-minutes.
    """
    if replacement_minutes < 0 or any(v < 0 or not math.isfinite(v) for v in minutes_by_player.values()):
        raise ValueError('invalid scenario minutes')
    total=sum(minutes_by_player.values())+replacement_minutes
    if abs(total-990)>1e-6:
        raise ValueError('scenario must account for 990 equivalent player-minutes')
    return sum(minutes/990*ratings.get(pid,{}).get('excess_rating',0.0)
               for pid,minutes in minutes_by_player.items())


def scenario_delta(plan, minutes_by_player, cutoff_date, replacement_minutes=0):
    """Explicit hypothetical lineup delta for use with the fitted team model."""
    if plan['cutoff_date'] != cutoff_date:
        raise ValueError('scenario must use the exact saved prediction cutoff')
    if any(r['rating_fit_through'] >= cutoff_date for r in plan['ratings'].values()):
        raise ValueError('scenario rating violates cutoff')
    reference=lineup_value(plan['reference_minutes'],plan['ratings'])
    return {'rating_delta':lineup_value(minutes_by_player,plan['ratings'],replacement_minutes)-reference,
            'evidence_type':'user-supplied hypothetical minutes; no availability claim',
            'unknown_player_minutes':sum(m for pid,m in minutes_by_player.items() if pid not in plan['ratings']),
            'replacement_minutes':replacement_minutes}


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
                expected=mixture(history[-3:],USAGE_WEIGHTS)
                reference=mixture(history)
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
                scenarios=[sum(w*values.get(pid,0) for pid,w in mixture([match]).items()) for match in history[-3:]]
                row={'game_id':target['game_id'],'team':team,'is_home':is_home,'match_date':day,
                     'history_cutoff_date':prior_date,'source_game_ids':[r['game_id'] for r in all_history],
                     'missing_history':missing_history,
                     'history_matches':len(history),'rating_coverage':coverage,'ready':bool(valid),
                     'rating_delta':float(expected_value-reference_value) if valid else 0.0,
                     'expected_excess_rating':expected_value if history else None,
                     'reference_excess_rating':reference_value if history else None,
                     'usage_churn':.5*sum(abs(expected.get(pid,0)-reference.get(pid,0)) for pid in set(expected)|set(reference)),
                     'usage_scenario_sd':float(np.std(scenarios)) if scenarios else None,
                     'approximate_rating_se':math.sqrt(sum((w*ratings[pid]['approximate_rating_se'])**2 for pid,w in expected.items() if pid in ratings)),
                     'fallback_reason':None if valid else 'missing recent usage, insufficient history/rating coverage or stale usage',
                     'availability_evidence':'prior-match usage only; no timestamped injury/lineup report'}
                feature_rows.append(row)
                plans.append({'game_id':target['game_id'],'team':team,'cutoff_date':day,
                              'expected_minutes':{pid:w*990 for pid,w in expected.items()},
                              'reference_minutes':{pid:w*990 for pid,w in reference.items()},'ratings':ratings,
                              'assumption':'last-three usage weights 0.5/0.3/0.2, normalized to 990; historical nominal roles',
                              'replacement_assumption':'25th percentile of earlier role-match performance ratings; not market replacement value'})
        # Both target features and all same-date sides are emitted BEFORE any
        # actual participants, minutes, ratings or roles on that date are learned.
        for row in observations_by_date[day]:
            team_history[(row['league'],row['team'])].append(row)
            if row['quality_status']!='complete':
                continue
            for player in row['players']:
                pid=player['player_id']; role=player['role']; rating=player['rating']
                if role!='unknown':
                    player_role[pid]=role
                if rating is not None:
                    minutes=player['minutes_equivalent90']
                    player_history[pid].append((rating,minutes,day))
                    role_samples[role].append((rating,minutes))
    return feature_rows,plans
