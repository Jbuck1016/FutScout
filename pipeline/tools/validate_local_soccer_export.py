"""Independent reconciliation of immutable local export and rich-model runs."""
from pathlib import Path
import argparse
import json
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import research_soccer_forecasts as core
import research_local_rich_features as rich
from export_local_soccer_features import ROLLING_METRICS


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def validate(source, export, output):
    manifest=json.loads((export/'manifest.json').read_text(encoding='utf-8'))
    for name,metadata in manifest['outputs'].items():
        assert core.sha256(export/name)==metadata['sha256'],name
    lineage=read_rows(export/'source_lineage.jsonl')
    assert len(lineage)==5255 and len({r['game_id'] for r in lineage})==5255
    changed=[]
    for row in lineage:
        stat=Path(row['path']).stat()
        if stat.st_size!=row['bytes'] or stat.st_mtime_ns!=row['mtime_ns']:
            changed.append(row['game_id'])
    assert not changed,changed
    for row in lineage[::101]:
        assert core.sha256(Path(row['path']))==row['sha256']
    shots=pd.DataFrame(read_rows(export/'shots.jsonl'))
    assert not shots.duplicated(['game_id','source_event_id']).any()
    assert (shots.fit_through_date.isna() | (shots.fit_through_date < shots.match_date)).all()
    shots['bin_key']=shots.bins.map(lambda b:json.dumps(b))
    daily=shots.groupby(['bin_key','match_date'],as_index=False).agg(n=('goal','size'),goals=('goal','sum'))
    daily=daily.sort_values(['bin_key','match_date'])
    daily['prior_n']=daily.groupby('bin_key').n.cumsum()-daily.n
    daily['prior_goals']=daily.groupby('bin_key').goals.cumsum()-daily.goals
    joined=shots.merge(daily,on=['bin_key','match_date'],validate='many_to_one')
    assert (joined.prior_n==joined.prior_bin_shots).all()
    assert (joined.prior_goals==joined.prior_bin_goals).all()
    error=np.abs(joined.xg-(joined.prior_goals+2)/(joined.prior_n+20))
    assert float(error.max())<=.0000500001
    observations=pd.DataFrame(read_rows(export/'observations.jsonl'))
    assert len(observations)==10510 and not observations.duplicated(['game_id','team']).any()
    sums=shots.groupby(['game_id','team']).xg.sum()
    for row in observations.itertuples(index=False):
        if row.quality_status=='quarantined':
            assert pd.isna(row.npxg_for) and pd.isna(row.pass_xt_net)
        else:
            assert abs(row.npxg_for-sums.get((row.game_id,row.team),0))<1e-10
            assert row.true_open_play_box_entries <= row.legacy_open_play_box_passes
    rolling=pd.DataFrame(read_rows(export/'rolling_features.jsonl')).set_index(['game_id','team'])
    checked=0
    for _,group in observations.groupby(['league','team']):
        ordered=group.sort_values(['match_date','game_id'])
        assert not ordered.match_date.duplicated().any(),'same-team/date requires grouped-date reference calculation'
        keys=list(zip(ordered.game_id,ordered.team))
        for window in (3,5,10):
            shifted=ordered[list(ROLLING_METRICS)].shift(1)
            reference=shifted.rolling(window,min_periods=1).mean()
            count=shifted.rolling(window,min_periods=1).count()
            expected_count=np.minimum(np.arange(len(ordered)),window)
            reference=reference.mask(count.lt(expected_count,axis=0))
            for metric in ROLLING_METRICS:
                actual=rolling.loc[keys,f'{metric}_{window}'].to_numpy(dtype=float)
                np.testing.assert_allclose(actual,reference[metric].to_numpy(),atol=1e-10,rtol=0,equal_nan=True)
                checked+=len(group)
    frame,selected=rich.load_export(source,export)
    legacy=[]
    for side in ('team','opponent'):
        for window in (3,5,10):
            old=frame[f'{side}.box_entries_pass_{window}']
            new=frame[f'{side}.local.legacy_open_play_box_passes_{window}']
            valid=old.notna()&new.notna()
            difference=(old[valid]-new[valid]).abs()
            legacy.append({'side':side,'window':window,'valid_rows':int(valid.sum()),
                           'different_beyond_rounding':int((difference>0.000051).sum()),
                           'max_difference':float(difference.max())})
    report=json.loads((output/'report.json').read_text(encoding='utf-8'))
    predictions=pd.read_csv(output/'historical_predictions.csv',dtype={'game_id':str,'fold':str})
    assert not predictions.duplicated(['candidate','fold','game_id']).any()
    numerical=[]
    for season in ('2425','2526'):
        ids=set(frame.loc[frame.season==season,'game_id'])
        for name in rich.CANDIDATES:
            rows=predictions[(predictions.fold==season)&(predictions.candidate==name)]
            assert set(rows.game_id)==ids and len(rows)==len(ids)
            p=rows[['p_home','p_draw','p_away']].to_numpy()
            np.testing.assert_allclose(p.sum(axis=1),1,atol=1e-14)
            actual=np.array([{'H':0,'D':1,'A':2}[x] for x in rows.result])
            loss=float(-np.log(p[np.arange(len(rows)),actual]).mean())
            brier=float(np.mean(np.sum((p-np.eye(3)[actual])**2,axis=1)))
            expected=report['folds'][season]['candidates'][name]
            assert abs(loss-expected['log_loss'])<1e-12
            assert abs(brier-expected['brier'])<1e-12
            numerical.append({'fold':season,'candidate':name,'n':len(rows),'log_loss':loss,'brier':brier,
                              'delta':expected['paired_vs_baseline']['delta_log_loss'],
                              'ci95':expected['paired_vs_baseline']['ci95']})
    reloads={}
    for name,metadata in report['models'].items():
        path=output/f'{name}.pkl'
        assert core.sha256(path)==metadata['sha256']
        model=pickle.loads(path.read_bytes())
        prob,*_=rich.predict_candidate(model,frame.iloc[::41])
        np.testing.assert_allclose(prob.sum(axis=1),1,atol=1e-14)
        reloads[name]={'n':len(prob),'passed':True,'sha256':metadata['sha256']}
    validation={'status':'passed','raw_source_files':len(lineage),'source_stat_changes':changed,
                'raw_source_hashes_rechecked':len(lineage[::101]),'administrative_id_collisions':sum(r['offside_given_id_collisions'] for r in lineage),
                'shots_independently_checked':len(shots),'maximum_xg_rounding_error':float(error.max()),
                'rolling_values_independently_checked':checked,'quarantined':manifest['quarantined'],
                'common_population_by_season':selected['evaluation_matches_by_season'],
                'excluded_game_ids':selected['evaluation_excluded_game_ids'],'legacy_box_pass_reconciliation':legacy,
                'prediction_rows':len(predictions),'metrics':numerical,'model_reloads':reloads,
                'export_manifest_sha256':core.sha256(export/'manifest.json'),'report_sha256':core.sha256(output/'report.json')}
    (output/'validation.json').write_text(json.dumps(validation,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in validation.items() if k not in ('model_reloads','excluded_game_ids','quarantined','legacy_box_pass_reconciliation')},indent=2))
    return validation


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--export',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    validate(args.source,args.export,args.output)
