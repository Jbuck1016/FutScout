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
from local_player_strength import build_features, extract_usage, lineup_value, mixture, scenario_delta
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
                row['players']=[dict(player_id='future',name='future',role='F',rating=10.,minutes_equivalent90=990.,starter=True)]
        after,_=build_features(targets,altered)
        self.assertEqual(before[:42],after[:42])
        for plan in plans:
            for rating in plan['ratings'].values():
                self.assertLess(rating['rating_fit_through'],plan['cutoff_date'])
        self.assertNotIn('future',plans[40]['expected_minutes'])

    def test_stable_players_have_no_added_absolute_strength(self):
        targets,observations=fixtures()
        features,plans=build_features(targets,observations)
        self.assertTrue(features[-1]['ready'])
        self.assertAlmostEqual(features[-1]['rating_delta'],0.,places=12)
        self.assertGreater(features[-1]['expected_excess_rating'],0)
        self.assertAlmostEqual(sum(plans[-1]['expected_minutes'].values()),990.,places=8)

    def test_replacement_scenario_is_explicit_and_relative(self):
        ratings={'a':{'excess_rating':1.},'b':{'excess_rating':0.}}
        full=lineup_value({'a':90.,'b':900.},ratings)
        absent=lineup_value({'b':900.},ratings,replacement_minutes=90.)
        self.assertAlmostEqual(full-absent,1/11)
        with self.assertRaises(ValueError):
            lineup_value({'a':90},ratings)
        plan={'cutoff_date':'2023-08-02','reference_minutes':{'a':90,'b':900},
              'ratings':{p:r|{'rating_fit_through':'2023-08-01'} for p,r in ratings.items()}}
        scenario=scenario_delta(plan,{'b':900},'2023-08-02',replacement_minutes=90)
        self.assertAlmostEqual(scenario['rating_delta'],-1/11)
        with self.assertRaises(ValueError):
            scenario_delta(plan,{'b':900},'2023-08-01',replacement_minutes=90)

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
