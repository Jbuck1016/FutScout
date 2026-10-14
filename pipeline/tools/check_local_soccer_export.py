"""Synthetic edge-case regressions; fixtures never enter historical training."""
from pathlib import Path
import sys
import unittest
from copy import deepcopy

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from export_local_soccer_features import score_shots, rolling_features, enrich_sides, ROLLING_METRICS, shot_bins, summarize_match


class LocalExportTests(unittest.TestCase):
    def shots(self):
        return [dict(game_id=str(i),team='A',season='2324',league='L',match_date=d,
                     bins=[2,2,False,False],goal=g,is_open_play=True,source_event_id=str(i))
                for i,(d,g) in enumerate([('2023-08-01',1),('2023-08-01',0),('2023-08-02',0),('2023-08-03',1)])]

    def test_xg_strictly_prior_dates(self):
        shots=self.shots()
        result=score_shots(shots)
        self.assertEqual([r['xg'] for r in result[:2]],[.1,.1])
        self.assertEqual(result[2]['xg'],.1364)
        self.assertEqual(result[2]['prior_bin_shots'],2)
        altered=deepcopy(shots)
        altered[2]['goal']=1; altered[3]['goal']=0
        after=score_shots(altered)
        self.assertEqual([r['xg'] for r in result[:3]],[r['xg'] for r in after[:3]])
        self.assertNotEqual(result[3]['xg'],after[3]['xg'])
        for r in result:
            self.assertTrue(r['fit_through_date'] is None or r['fit_through_date'] < r['match_date'])

    def test_geometry_xg_does_not_depend_on_big_chance(self):
        before=score_shots(self.shots())
        altered=self.shots()
        altered[-1]['bins'][-1]=True
        after=score_shots(altered)
        self.assertEqual(before[-1]['geometry_xg'],after[-1]['geometry_xg'])
        self.assertEqual(after[-1]['xg'],.1)

    def test_rolling_excludes_target_and_same_date(self):
        rows=[]
        for i,date in enumerate(('2023-08-01','2023-08-01','2023-08-02')):
            rows.append(dict(game_id=str(i),team='A',opponent='B',is_home=True,league='L',season='2324',match_date=date,
                             **{m:float(i+1) for m in ROLLING_METRICS}))
        result=rolling_features(rows)
        self.assertIsNone(result[0]['npxg_for_5'])
        self.assertIsNone(result[1]['npxg_for_5'])
        self.assertEqual(result[2]['npxg_for_5'],1.5)
        rows[-1]['npxg_for']=999
        self.assertEqual(rolling_features(rows)[2]['npxg_for_5'],1.5)
        rows[0]['npxg_for']=None
        self.assertIsNone(rolling_features(rows)[2]['npxg_for_5'])

    def test_geometry_thresholds(self):
        key,distance=shot_bins(100,50,False,True)
        self.assertEqual(key,(1,3,False,True))
        self.assertEqual(distance,0)

    def test_admin_id_collision_cannot_delete_real_pass(self):
        match=dict(game_id='1',season='2324',league='L',match_date='2023-08-01',team='A',opponent='B',goals_for=1,goals_against=0)
        football=dict(id=7,type={'displayName':'Pass'},teamId=1,expandedMinute=90,
                      outcomeType={'displayName':'Successful'},x=70,y=50,endX=90,endY=50,qualifiers=[])
        admin=dict(id=7,type={'displayName':'OffsideGiven'},teamId=2,minute=12,x=30,y=40)
        payload=dict(startDate='2023-08-01',elapsed='F',statusCode=6,
                     home=dict(teamId=1,name='A',scores={'fulltime':1}),away=dict(teamId=2,name='B',scores={'fulltime':0}),
                     events=[admin,football])
        grid={(x,y):x/100 for x in range(12) for y in range(8)}
        sides,shots,_=summarize_match(payload,match,grid)
        self.assertEqual(sides[0]['complete_passes'],1)
        self.assertEqual(sides[0]['true_open_play_box_entries'],1)
        self.assertGreater(sides[0]['pass_xt_net'],0)
        payload['events'].append(football.copy())
        with self.assertRaisesRegex(ValueError,'duplicate source event ID'):
            summarize_match(payload,match,grid)

    def test_missing_shot_geometry_is_not_zero_xg(self):
        sides=[]
        for team,opponent in [('A','B'),('B','A')]:
            sides.append(dict(game_id='1',team=team,opponent=opponent,np_shots=1,
                np_shots_without_coordinates=1 if team=='A' else 0,
                complete_passes_without_coordinates=0,npxg_for=0.,geometry_npxg_for=0.,
                open_play_npxg_for=0.,set_piece_npxg_for=0.,pass_xt_net=0.))
        output=enrich_sides(sides,[])
        self.assertIsNone(output[0]['npxg_for'])
        self.assertIsNone(output[1]['npxg_against'])


if __name__=='__main__':
    unittest.main(verbosity=2)
