"""Synthetic player chronology and scenario regressions, never training data."""
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_player_strength import build_features, extract_usage, lineup_value, mixture, scenario_delta, feasible_allocation, validate_lineup, VERSION
import research_player_strength as research


def fixtures():
    targets=[]; observations=[]
    for i in range(30):
        day=str(date(2023,8,1)+timedelta(days=i))
        targets.append(dict(game_id=str(i),match_date=day,league='L',season='2324',team='A',opponent='B'))
        for team in ('A','B'):
            players=[dict(player_id=f'{team}{j}',name=f'{team}{j}',role='GK' if j==0 else 'M',
                          minutes_equivalent90=90.,starter=True,rating=6+j/10+(i%3)/100) for j in range(11)]
            observations.append(dict(game_id=str(i),team=team,league='L',match_date=day,players=players,quality_status='complete'))
    return targets,observations


class PlayerTests(unittest.TestCase):
    def test_no_target_participants_minutes_role_or_rating_leak(self):
        targets,observations=fixtures()
        before,plans=build_features(targets,observations)
        altered=deepcopy(observations)
        for row in altered:
            if row['match_date']>=targets[20]['match_date']:
                row['players']=[dict(player_id=f"future{row['team']}{i}",name='future',role='GK' if i==0 else 'F',rating=10.,minutes_equivalent90=90.,starter=True) for i in range(11)]
        after,_=build_features(targets,altered)
        self.assertEqual(before[:42],after[:42])
        for plan in plans:
            for rating in plan['ratings'].values():
                self.assertLess(rating['rating_fit_through'],plan['cutoff_date'])
        self.assertFalse(any(p.startswith('future') for p in plans[40]['expected_minutes']))

    def test_stable_players_have_no_added_absolute_strength(self):
        targets,observations=fixtures()
        features,plans=build_features(targets,observations)
        self.assertTrue(features[-1]['ready'])
        self.assertAlmostEqual(features[-1]['rating_delta'],0.,places=12)
        self.assertGreater(features[-1]['expected_excess_rating'],0)
        self.assertAlmostEqual(sum(plans[-1]['expected_minutes'].values()),990.,places=8)

    def test_replacement_scenario_is_explicit_and_relative(self):
        ratings={str(i):{'excess_rating':1. if i==1 else 0.,'role':'GK' if i==0 else 'M'} for i in range(11)}
        minutes={p:90. for p in ratings}; absent_minutes={p:m for p,m in minutes.items() if p!='1'}
        full=lineup_value(minutes,ratings)
        absent=lineup_value(absent_minutes,ratings,replacement_minutes=90.)
        self.assertAlmostEqual(full-absent,1/11)
        with self.assertRaises(ValueError):
            lineup_value({'1':90},ratings)
        plan={'version':VERSION,'team':'A','cutoff_date':'2023-08-02','reference_minutes':minutes,
              'reference_replacement_by_role':{'GK':0.,'outfield':0.},'roles':{p:r['role'] for p,r in ratings.items()},
              'membership_evidence':{p:{'teams':['A'],'observed_date':'2023-08-01'} for p in ratings},
              'ratings':{p:r|{'rating_fit_through':'2023-08-01'} for p,r in ratings.items()}}
        scenario=scenario_delta(plan,absent_minutes,'2023-08-02',replacement_minutes=90)
        self.assertAlmostEqual(scenario['rating_delta'],-1/11)
        with self.assertRaises(ValueError):
            scenario_delta(plan,absent_minutes,'2023-08-01',replacement_minutes=90)

    def test_scenario_rejects_nonfinite_and_unbounded_budgets(self):
        for value in (float('nan'),float('inf'),-float('inf'),-1.,991.):
            with self.assertRaises(ValueError):
                lineup_value({}, {},replacement_minutes=value)
        for value in (float('nan'),float('inf'),-1.,90.01,990.):
            with self.assertRaises(ValueError):
                lineup_value({'a':value},{'a':{'role':'M','excess_rating':1.}},replacement_minutes=990-value)
        with self.assertRaises(ValueError):
            lineup_value({'a':90,'b':90},{'a':{'role':'GK'},'b':{'role':'GK'}},810)
        with self.assertRaises(ValueError):
            lineup_value({'a':90},{'a':{'role':'GK'}},900,replacement_by_role={'GK':900,'outfield':0})
        self.assertEqual(lineup_value({}, {},990),0.)
        for value in (float('nan'),float('inf'),-1.,1.):
            with self.assertRaises(ValueError):
                feasible_allocation({'a':value},{'a':'M'})

    def test_depleted_lineup_never_inflates_remaining_players(self):
        history=[{'players':[{'player_id':str(i),'minutes_equivalent90':90. if i<9 else 30.} for i in range(11)]}]
        roles={str(i):'GK' if i==0 else 'M' for i in range(11)}
        shares,pool=feasible_allocation(mixture(history),roles)
        self.assertAlmostEqual(shares['0']*990,90.)
        self.assertAlmostEqual(sum(pool.values()),120.)

    def test_random_mixtures_obey_individual_team_and_role_budgets(self):
        rng=np.random.default_rng(20261014)
        for _ in range(300):
            roles={str(i):'GK' if i<2 else 'M' for i in range(25)}
            history=[{'players':[{'player_id':str(i),'minutes_equivalent90':float(rng.uniform(0,90))} for i in rng.choice(25,15,replace=False)]} for _ in range(3)]
            shares,pool=feasible_allocation(mixture(history,(.5,.3,.2)),roles)
            minutes={p:w*990 for p,w in shares.items()}
            self.assertTrue(all(0<=m<=90+1e-10 for m in minutes.values()))
            self.assertAlmostEqual(sum(minutes.values())+sum(pool.values()),990.,places=8)
            self.assertLessEqual(sum(m for p,m in minutes.items() if roles[p]=='GK'),90+1e-9)
            validate_lineup(minutes,roles,sum(pool.values()),pool)

    def test_prior_club_change_is_applied_after_all_same_date_forecasts(self):
        targets,observations=fixtures()
        transfer=deepcopy(next(r for r in observations if r['team']=='B' and r['game_id']=='20'))
        transfer['players'][1]=dict(transfer['players'][1],player_id='A1')
        observations=[transfer if r['team']=='B' and r['game_id']=='20' else r for r in observations]
        # No conflicting old-club appearance on or after the move.
        for row in observations:
            if row['team']=='A' and int(row['game_id'])>=20:
                row['players'][1]=dict(row['players'][1],player_id='new_A1')
        _,plans=build_features(targets,observations)
        on_day=next(p for p in plans if p['game_id']=='20' and p['team']=='A')
        after=next(p for p in plans if p['game_id']=='21' and p['team']=='A')
        self.assertIn('A1',on_day['expected_minutes'])
        self.assertNotIn('A1',after['expected_minutes'])
        self.assertIn('A1',after['reference_minutes'])
        self.assertEqual(after['membership_evidence']['A1']['teams'],['B'])
        self.assertGreater(after['expected_replacement_by_role']['outfield'],0)
        invalid=dict(after['expected_minutes']); invalid['A1']=10.
        with self.assertRaisesRegex(ValueError,'membership'):
            scenario_delta(after,invalid,after['cutoff_date'],990-sum(invalid.values()))

    def test_conflicting_prior_same_date_clubs_are_ineligible(self):
        targets,observations=fixtures()
        for row in observations:
            if row['team']=='B' and row['game_id']=='20':
                row['players'][1]=dict(row['players'][1],player_id='A1')
        _,plans=build_features(targets,observations)
        for team in ('A','B'):
            plan=next(p for p in plans if p['game_id']=='21' and p['team']==team)
            self.assertEqual(plan['membership_evidence']['A1']['teams'],['A','B'])
            self.assertNotIn('A1',plan['expected_minutes'])

    def test_missing_recent_usage_cannot_be_silently_skipped(self):
        targets,observations=fixtures()
        for row in observations:
            if row['game_id']=='20' and row['team']=='A':
                row['quality_status']='missing'; row['players']=[]
        features,_=build_features(targets,observations)
        affected=next(r for r in features if r['game_id']=='21' and r['team']=='A')
        self.assertTrue(affected['missing_history'])
        self.assertFalse(affected['ready'])
        self.assertEqual(affected['rating_delta'],0)

    def test_cold_or_stale_history_is_neutral(self):
        targets,observations=fixtures()
        targets.append(dict(targets[-1],game_id='future',match_date='2024-06-01'))
        features,_=build_features(targets,observations)
        for row in (features[0],features[-1]):
            self.assertFalse(row['ready'])
            self.assertEqual(row['rating_delta'],0)
            self.assertIsNotNone(row['fallback_reason'])

    def test_minutes_conserve_substitutions_and_red_cards(self):
        players=[dict(playerId=j,name=str(j),position='GK' if j==0 else 'MC',isFirstEleven=True,
                      stats={'ratings':{'0':6,'100':7}}) for j in range(11)]
        players[-1]['subbedOutExpandedMinute']=50
        players.append(dict(playerId=20,name='20',position='Sub',subbedInExpandedMinute=50,
                            subbedOutPlayerId=10,stats={'ratings':{'50':6,'100':6.5}}))
        events=[dict(type={'displayName':'End'},period={'displayName':'SecondHalf'},expandedMinute=100),
                dict(playerId=20,cardType={'displayName':'Red'},expandedMinute=90)]
        payload={'home':{'players':players},'events':events}
        target=dict(game_id='1',match_date='2023-08-01',league='L',season='2324',team='A',opponent='B')
        result=extract_usage(payload,'home',target)
        self.assertAlmostEqual(result['team_minutes_equivalent90'],981.)
        substitute=next(p for p in result['players'] if p['player_id']=='20')
        self.assertEqual(substitute['role'],'M')
        self.assertEqual(substitute['minutes_equivalent90'],36.)
        self.assertEqual(substitute['rating'],6.5)

    def test_unready_predictions_equal_baseline_exactly(self):
        frame=pd.DataFrame({'team.player.ready':[True,False],'opponent.player.ready':[True,True]})
        def fake(artifact,frame):
            value=.2 if artifact['candidate']=='baseline29' else .4
            return np.full((2,3),value),np.full(2,value),np.full(2,value),[np.array([[value]]) for _ in range(2)]
        with patch.object(research.core,'predict_candidate',side_effect=fake):
            p,h,a,matrices,fallback=research.predict({'candidate':'ratings31'},frame,{'candidate':'baseline29'})
        self.assertEqual(fallback.tolist(),[False,True])
        self.assertEqual(p[0,0],.4); self.assertEqual(p[1,0],.2)
        self.assertEqual(matrices[1][0,0],.2)


if __name__=='__main__':
    unittest.main(verbosity=2)
