"""Fixed chronological ablations for a lagged player-to-team strength layer."""
import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import research_local_rich_features as rich
import research_soccer_forecasts as core

CANDIDATES=('baseline29','usage33','ratings31','ratings_usage35')


def load_players(source,export,players):
    frame,quality=rich.load_export(source,export)
    manifest=json.loads((players/'manifest.json').read_text(encoding='utf-8'))
    if manifest['source_export_manifest_sha256'] != core.sha256(export/'manifest.json'):
        raise ValueError('player/source manifest mismatch')
    for name,metadata in manifest['outputs'].items():
        if core.sha256(players/name)!=metadata['sha256']:
            raise ValueError('player export digest mismatch')
    features=pd.DataFrame([json.loads(s) for s in (players/'player_features.jsonl').read_text(encoding='utf-8').splitlines()])
    if features.duplicated(['game_id','is_home']).any():
        raise ValueError('duplicate player features')
    if (features.history_cutoff_date.notna() & (features.history_cutoff_date>=features.match_date)).any():
        raise ValueError('player chronology violation')
    metrics=('rating_delta','usage_churn','rating_coverage','ready')
    for side,home in (('team',True),('opponent',False)):
        rows=features[features.is_home==home]
        names=dict(zip(rows.game_id,rows.team))
        if not np.array_equal(frame.game_id.map(names),frame.home_team if home else frame.away_team):
            raise ValueError('player team identity mismatch')
        selected=rows[['game_id',*metrics]].rename(columns={c:f'{side}.player.{c}' for c in metrics})
        frame=frame.merge(selected,on='game_id',validate='one_to_one')
    return frame,quality,manifest


def columns_for(name,baseline):
    added={'baseline29':(), 'usage33':('usage_churn','rating_coverage'),
           'ratings31':('rating_delta',), 'ratings_usage35':('usage_churn','rating_coverage','rating_delta')}
    return baseline+[f'{side}.player.{metric}' for side in ('team','opponent') for metric in added[name]]


def fit(name,train,columns):
    selected=columns_for(name,columns)
    return {'candidate':name,'columns':selected,'models':core.fit_rates(train,selected),'adjusters':{},'rho':0.,
            'trained_through':str(train.date.max().date()),'training_matches':len(train),
            'score_contract':core.SCORE_CONTRACT_VERSION,'status':'offline_research_only'}


def learned_coefficients(artifact):
    result={}
    for target,model in zip(('home_goal_rate','away_goal_rate'),artifact['models']):
        numeric=model.named_steps['prepare'].named_transformers_['numeric']
        names=numeric.named_steps['impute'].get_feature_names_out(artifact['columns'])
        result[target]={name:float(model.named_steps['model'].coef_[idx]/numeric.named_steps['scale'].scale_[idx])
                        for idx,name in enumerate(names) if '.player.' in name}
    return result


def predict(artifact,frame,baseline):
    p,h,a,matrices=core.predict_candidate(artifact,frame)
    ready=(frame['team.player.ready'] & frame['opponent.player.ready']).to_numpy(dtype=bool)
    if artifact['candidate']=='baseline29':
        return p,h,a,matrices,np.zeros(len(frame),dtype=bool)
    bp,bh,ba,bm=core.predict_candidate(baseline,frame)
    fallback=~ready
    p[fallback]=bp[fallback]; h[fallback]=bh[fallback]; a[fallback]=ba[fallback]
    for i in np.flatnonzero(fallback):
        matrices[i]=bm[i]
    return p,h,a,matrices,fallback


def run(source,export,players,output):
    output.mkdir(parents=True,exist_ok=False)
    protocol={'created_at':datetime.now(UTC).isoformat(),'candidates':list(CANDIDATES),
              'design':'fixed before evaluating any player ablation; no test-driven tuning',
              'player_manifest_sha256':core.sha256(players/'manifest.json'),
              'training':'two Poisson alpha=1 goal models; learned conditional player-feature coefficients',
              'rating_interpretation':'individual ratings are shrunk lagged provider performance proxies, not learned causal goal impact',
              'double_counting_control':'expected player rating minus the same-cutoff prior-ten-lineup reference; no absolute team rating added to Elo',
              'forecast_inputs':'prior dates only, expected usage from last three matches; no target actual lineup/minutes',
              'fallback':'if either side is not ready, use the unchanged fitted baseline goal rates and probabilities',
              'holdout':'reused 2425/2526 exploratory only; future frozen plan and previous output files untouched',
              'market':'no prices or future publication snapshots used'}
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n',encoding='utf-8',newline='\n')
    frame,quality,manifest=load_players(source,export,players)
    meta=json.loads((source/'artifacts/models/v2-field-tilt-box-entries-poisson-2324-2425-2526-20260914t205131z.json').read_text(encoding='utf-8'))
    columns=meta['numeric_columns']
    report={'protocol':protocol,'quality':quality,'player_manifest':manifest,'folds':{},'models':{},'fold_models':{}}
    (output/'fold_models').mkdir()
    all_rows=[]
    for season in ('2425','2526'):
        train=frame[frame.season<season]; test=frame[frame.season==season]
        if train.date.max()>=test.date.min():
            raise ValueError('nonchronological training split')
        control=fit('baseline29',train,columns)
        cp,*_=core.predict_candidate(control,test)
        fold={'train_matches':len(train),'test_matches':len(test),'candidates':{}}
        for name in CANDIDATES:
            artifact=control if name=='baseline29' else fit(name,train,columns)
            model_path=output/'fold_models'/f'{season}_{name}.pkl'
            model_path.write_bytes(pickle.dumps(artifact,protocol=5))
            report['fold_models'][f'{season}_{name}']={'path':str(model_path),'sha256':core.sha256(model_path),
                'trained_through':artifact['trained_through'],'learned_log_rate_coefficients':learned_coefficients(artifact)}
            p,h,a,matrices,fallback=predict(artifact,test,control)
            metrics=core.evaluate_predictions(test,p,h,a,matrices)
            metrics['paired_vs_baseline']=core.paired_interval(test,p,cp)
            metrics['fallback_matches']=int(fallback.sum())
            metrics['columns']=artifact['columns']
            # Change in goal rate with only the player-rating delta set to zero;
            # quantifies the learned conditional component, not a causal claim.
            neutral=test.copy()
            for side in ('team','opponent'):
                neutral[f'{side}.player.rating_delta']=0.
            _,nh,na,_,_=predict(artifact,neutral,control)
            metrics['learned_rating_component']={'home_mean_abs_log_rate_change':float(np.abs(np.log(h/nh)).mean()),
                                                'away_mean_abs_log_rate_change':float(np.abs(np.log(a/na)).mean()),
                                                'max_abs_log_rate_change':float(max(np.abs(np.log(h/nh)).max(),np.abs(np.log(a/na)).max()))}
            fold['candidates'][name]=metrics
            for idx,(_,row) in enumerate(test.iterrows()):
                all_rows.append({'candidate':name,'fold':season,'game_id':row.game_id,'date':str(row.date.date()),
                    'result':row.result,'home_goals':row.home_goals,'away_goals':row.away_goals,
                    'p_home':p[idx,0],'p_draw':p[idx,1],'p_away':p[idx,2], 'home_rate':h[idx],'away_rate':a[idx],
                    'fallback_to_baseline':bool(fallback[idx]),'evidence_type':'historical_player_usage_reconstruction'})
            print(f"{season} {name} loss={metrics['log_loss']:.8f} delta={metrics['paired_vs_baseline']['delta_log_loss']:+.8f} fallback={int(fallback.sum())}",flush=True)
        report['folds'][season]=fold
    for name in CANDIDATES:
        artifact=fit(name,frame,columns)
        artifact['player_manifest_sha256']=protocol['player_manifest_sha256']
        path=output/f'{name}.pkl'; path.write_bytes(pickle.dumps(artifact,protocol=5))
        report['models'][name]={'path':str(path),'sha256':core.sha256(path),'columns':artifact['columns'],
                                'training_matches':len(frame),'trained_through':artifact['trained_through']}
    pd.DataFrame(all_rows).to_csv(output/'historical_predictions.csv',index=False)
    report['decision']='no promotion from reused holdouts; retain exact future freeze protocol'
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--export',type=Path,required=True)
    parser.add_argument('--players',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(args.source,args.export,args.players,args.output)
