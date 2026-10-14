"""Reconcile player lineage, independent usage weights and saved held-out predictions."""
import argparse
from bisect import bisect_left
from collections import defaultdict
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import research_player_strength as research
from local_player_strength import scenario_delta, validate_lineup


def rows(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]


def validate(source,export,players,output):
    frame,_,manifest=research.load_players(source,export,players)
    plans=rows(players/'expected_players.jsonl')
    observations=rows(players/'player_observations.jsonl')
    features=rows(players/'player_features.jsonl')
    by_team=defaultdict(list)
    by_player=defaultdict(list)
    for row in observations:
        by_team[row['team']].append(row)
        if row['quality_status']=='complete':
            for player in row['players']:
                by_player[player['player_id']].append((row['match_date'],row['team'],player['role'],row['game_id']))
    by_player={pid:sorted(history,key=lambda r:r[0]) for pid,history in by_player.items()}
    dates={pid:[r[0] for r in history] for pid,history in by_player.items()}
    feature_by_key={(r['game_id'],r['team']):r for r in features}
    assert len(feature_by_key)==10510
    rating_rows=0; ready=0; maximum_minutes=0.; replacement_plans=0; membership_removal_plans=0
    for plan in plans:
        key=(plan['game_id'],plan['team']); feature=feature_by_key[key]
        historical=sorted((r for r in by_team[plan['team']] if r['match_date']<plan['cutoff_date']),key=lambda r:(r['match_date'],r['game_id']))[-10:]
        assert set(feature['source_game_ids'])=={r['game_id'] for r in historical}
        complete=[r for r in historical if r['quality_status']=='complete']
        actual=defaultdict(float)
        recent=complete[-3:][::-1]
        weights=np.array([.5,.3,.2][:len(recent)])
        if len(recent):
            weights/=weights.sum()
        for row,weight in zip(recent,weights):
            for player in row['players']:
                actual[player['player_id']]+=float(weight)*player['minutes_equivalent90']
        # Independently query each player's latest strictly earlier appearance,
        # grouping equal dates so the source row order cannot resolve conflicts.
        roles={}; clubs={}
        for pid in plan['roles']:
            end=bisect_left(dates.get(pid,[]),plan['cutoff_date'])
            prior=by_player.get(pid,[])[:end]
            if prior:
                last_date=prior[-1][0]
                latest=[r for r in prior if r[0]==last_date]
                clubs[pid]=sorted({r[1] for r in latest})
                role=next((r[2] for r in reversed(prior) if r[2]!='unknown'),'unknown')
                roles[pid]=role
                evidence=plan['membership_evidence'][pid]
                assert evidence['observed_date']==last_date and evidence['teams']==clubs[pid]
                assert set(evidence['source_game_ids'])=={r[3] for r in latest}
        actual={pid:m for pid,m in actual.items() if clubs.get(pid)==[plan['team']] and roles.get(pid) in ('GK','D','M','F') and m>0}
        for goalkeeper,budget in ((True,90.),(False,900.)):
            selected=[pid for pid in actual if (roles[pid]=='GK')==goalkeeper]
            total=sum(actual[pid] for pid in selected)
            if total>budget:
                for pid in selected:
                    actual[pid]*=budget/total
        assert set(actual)==set(plan['expected_minutes'])
        for pid,value in actual.items():
            assert abs(value-plan['expected_minutes'][pid])<1e-9
        pools=plan['expected_replacement_by_role']
        validate_lineup(plan['expected_minutes'],roles,sum(pools.values()),pools)
        reference_pool=plan['reference_replacement_by_role']
        validate_lineup(plan['reference_minutes'],roles,sum(reference_pool.values()),reference_pool)
        maximum_minutes=max(maximum_minutes,max(plan['expected_minutes'].values(),default=0.))
        replacement_plans+=int(sum(pools.values())>1e-8)
        membership_removal_plans+=int(bool(plan['membership_removed_minutes']))
        assert all(clubs[pid]==[plan['team']] for pid in plan['expected_minutes'])
        for rating in plan['ratings'].values():
            assert rating['rating_fit_through']<plan['cutoff_date']
            assert 0<rating['shrinkage_weight']<1
            rating_rows+=1
        if any(r['quality_status']!='complete' for r in historical):
            assert not feature['ready']
        if not feature['ready']:
            assert feature['rating_delta']==0.
        else:
            ready+=1
            check=scenario_delta(plan,plan['expected_minutes'],plan['cutoff_date'],sum(pools.values()),pools)
            assert abs(check['rating_delta']-feature['rating_delta'])<1e-12
    report=json.loads((output/'report.json').read_text(encoding='utf-8'))
    predictions=pd.read_csv(output/'historical_predictions.csv',dtype={'fold':str,'game_id':str})
    assert not predictions.duplicated(['candidate','fold','game_id']).any()
    checked=[]
    for season in ('2425','2526'):
        test=frame[frame.season==season].copy()
        control=pickle.loads((output/'fold_models'/f'{season}_baseline29.pkl').read_bytes())
        for name in research.CANDIDATES:
            path=output/'fold_models'/f'{season}_{name}.pkl'
            assert research.core.sha256(path)==report['fold_models'][f'{season}_{name}']['sha256']
            artifact=pickle.loads(path.read_bytes())
            assert artifact['trained_through']<str(test.date.min().date())
            p,h,a,_,fallback=research.predict(artifact,test,control)
            saved=predictions[(predictions.fold==season)&(predictions.candidate==name)].set_index('game_id')
            assert set(saved.index)==set(test.game_id)
            saved=saved.loc[test.game_id]
            np.testing.assert_allclose(p,saved[['p_home','p_draw','p_away']],atol=1e-14,rtol=0)
            np.testing.assert_allclose(p.sum(axis=1),1,atol=1e-14)
            np.testing.assert_array_equal(fallback,saved.fallback_to_baseline)
            index=np.array([{'H':0,'D':1,'A':2}[r] for r in saved.result])
            loss=float(-np.log(p[np.arange(len(p)),index]).mean())
            expected=report['folds'][season]['candidates'][name]
            assert abs(loss-expected['log_loss'])<1e-12
            checked.append({'fold':season,'candidate':name,'n':len(p),'log_loss':loss,'fallback':int(fallback.sum()),
                            'paired_vs_baseline':expected['paired_vs_baseline']})
    # A transparent example, picked by date/team eligibility, not by effect size.
    eligible=frame[(frame.season=='2526') & (frame.home_team=='Arsenal') & frame['team.player.ready'] & frame['opponent.player.ready']]
    scenario=None
    if not eligible.empty:
        example=eligible.sort_values(['date','game_id']).iloc[[0]].copy()
        plan=next(p for p in plans if p['game_id']==example.iloc[0].game_id and p['team']=='Arsenal')
        known={p:m for p,m in plan['expected_minutes'].items() if p in plan['ratings']}
        pid=max(known,key=lambda p:known[p]*plan['ratings'][p]['excess_rating'])
        minutes=known[pid]
        proposed=dict(plan['expected_minutes']); proposed.pop(pid)
        delta=scenario_delta(plan,proposed,plan['cutoff_date'],replacement_minutes=minutes+sum(plan['expected_replacement_by_role'].values()))
        model=pickle.loads((output/'fold_models'/'2526_ratings31.pkl').read_bytes())
        control=pickle.loads((output/'fold_models'/'2526_baseline29.pkl').read_bytes())
        before=research.predict(model,example,control)
        example['team.player.rating_delta']=delta['rating_delta']
        after=research.predict(model,example,control)
        scenario={'game_id':plan['game_id'],'cutoff_date':plan['cutoff_date'],'player_id':pid,
                  'hypothetical_replacement_minutes':minutes,'rating':plan['ratings'][pid],
                  'home_goal_rate_before':float(before[1][0]),'home_goal_rate_after':float(after[1][0]),
                  'away_goal_rate_before':float(before[2][0]),'away_goal_rate_after':float(after[2][0]),
                  'home_win_before':float(before[0][0,0]),'home_win_after':float(after[0][0,0]),
                  'evidence':'hypothetical removal; no claim this player was injured or unavailable',
                  'model_trained_through':model['trained_through']}
    for name,meta in report['models'].items():
        assert research.core.sha256(output/f'{name}.pkl')==meta['sha256']
    result={'status':'passed','expected_player_plans':len(plans),'lagged_player_ratings_checked':rating_rows,
            'maximum_expected_minutes':maximum_minutes,'over90_allocations':0,'ineligible_club_allocations':0,
            'plans_with_replacement_pool':replacement_plans,'plans_with_membership_removal':membership_removal_plans,
            'ready_team_targets':ready,'heldout_prediction_rows':len(predictions),'fold_models_reloaded':8,
            'final_model_hashes_checked':4,'metrics':checked,'hypothetical_scenario':scenario,
            'player_manifest_sha256':research.core.sha256(players/'manifest.json'),
            'report_sha256':research.core.sha256(output/'report.json')}
    (output/'validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--export',type=Path,required=True)
    parser.add_argument('--players',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    validate(args.source,args.export,args.players,args.output)
