"""Explore locally reconstructed xG/xT and genuine pass-entry features offline."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline

import research_soccer_forecasts as core
import train_match_baselines as baseline

RICH_METRICS = ('npxg_for', 'npxg_against', 'pass_xt_net_difference', 'true_open_play_box_entries')
CANDIDATES = ('baseline29', 'npxg33', 'geometry_npxg33', 'pass_xt31', 'true_entries29', 'rich37', 'adjusted_rich37')


def load_export(source: Path, export: Path):
    manifest = json.loads((export/'manifest.json').read_text(encoding='utf-8'))
    if manifest['status'] != 'complete_with_explicit_quarantine' or manifest['matches'] != 5255 or manifest['team_sides'] != 10510:
        raise ValueError('incomplete export')
    for name, meta in manifest['outputs'].items():
        if core.sha256(export/name) != meta['sha256']:
            raise ValueError(f'export digest mismatch: {name}')
    snapshot = source/'artifacts/training_snapshots/top_five_2324_2526_v1.jsonl'
    if core.sha256(snapshot) != manifest['snapshot_sha256']:
        raise ValueError('export and baseline snapshot differ')
    frame = core.add_schedule_context(core.load_snapshot(snapshot))
    rows = [json.loads(line) for line in (export/'rolling_features.jsonl').read_text(encoding='utf-8').splitlines()]
    rolling = pd.DataFrame(rows)
    quarantined={row['game_id'] for row in manifest['quarantined']}
    affected=set(rolling.loc[rolling.source_game_ids.apply(lambda ids: bool(set(ids)&quarantined)),'game_id'])|quarantined
    if rolling.duplicated(['game_id','team']).any():
        raise ValueError('duplicate rolling feature rows')
    if ((rolling.history_cutoff_date.notna()) & (rolling.history_cutoff_date >= rolling.match_date)).any():
        raise ValueError('feature cutoff violates chronology')
    feature_cols = [c for c in rolling if c.endswith(('_3','_5','_10')) and not c.startswith('prior_count')]
    for side, is_home in (('team',True), ('opponent',False)):
        subset = rolling[rolling.is_home == is_home]
        names = dict(zip(subset.game_id, subset.team))
        actual = frame.home_team if is_home else frame.away_team
        if not np.array_equal(frame.game_id.map(names).to_numpy(),actual.to_numpy()):
            raise ValueError(f'{side} identity mismatch')
        selected = subset[['game_id']+feature_cols].rename(columns={c:f'{side}.local.{c}' for c in feature_cols})
        frame = frame.merge(selected, on='game_id', how='left', validate='one_to_one')
    # Exclude short-feed targets and every target whose snapshot 3/5/10 history
    # contains a quarantined game, identically for every candidate. Recompute
    # Elo without quarantined outcomes before selecting the common population.
    frame=frame[~frame.game_id.isin(quarantined)].copy()
    baseline.add_pre_match_elo(frame)
    frame=frame.drop(columns=[c for c in frame if '.schedule_' in c])
    frame=core.add_schedule_context(frame)
    frame=frame[~frame.game_id.isin(affected)].reset_index(drop=True)
    manifest=manifest|{'evaluation_excluded_game_ids':sorted(affected),
                       'evaluation_matches_by_season':frame.season.value_counts().to_dict()}
    return frame, manifest


def columns_for(name, columns):
    metrics = {'npxg33': ('npxg_for','npxg_against'), 'geometry_npxg33': ('geometry_npxg_for','geometry_npxg_against'),
               'pass_xt31': ('pass_xt_net_difference',), 'rich37': RICH_METRICS, 'adjusted_rich37': RICH_METRICS}
    if name == 'baseline29':
        return columns
    if name == 'true_entries29':
        return [c for c in columns if 'box_entries_pass' not in c] + [f'{side}.local.true_open_play_box_entries_{window}'
            for side in ('team','opponent') for window in (3,5,10)]
    adjusted = 'adjusted_' if name == 'adjusted_rich37' else ''
    return columns+[f'{side}.local.{adjusted}{metric}_5' for side in ('team','opponent') for metric in metrics[name]]


def metric_values(frame, side, metric):
    values = pd.to_numeric(frame[f'{side}.local.{metric}_5'])
    if metric != 'pass_xt_net_difference':
        if (values.dropna() < 0).any():
            raise ValueError(f'negative {metric}')
        return np.log1p(values)
    return values


def fit_adjusters(train):
    context = pd.concat([core.adjustment_context(train,side) for side in ('team','opponent')],ignore_index=True)
    models = {}
    for metric in RICH_METRICS:
        y = pd.concat([metric_values(train,side,metric) for side in ('team','opponent')],ignore_index=True)
        valid = y.notna()
        if valid.sum() < 500:
            raise ValueError(f'insufficient reliable historical coverage for {metric}')
        models[metric] = Pipeline([
            ('prepare',baseline.preprocessing([c for c in context if c != 'league'],['league'])),
            ('model',Ridge(alpha=100.0))]).fit(context.loc[valid],y.loc[valid])
    return models


def adjusted_frame(frame, adjusters):
    transformed = frame.copy()
    for side in ('team','opponent'):
        context = core.adjustment_context(frame,side)
        for metric, model in adjusters.items():
            transformed[f'{side}.local.adjusted_{metric}_5'] = metric_values(frame,side,metric)-model.predict(context)
    return transformed


def fit_candidate(name, train, baseline_columns):
    columns = columns_for(name,baseline_columns)
    adjusters = fit_adjusters(train) if name == 'adjusted_rich37' else {}
    transformed = adjusted_frame(train,adjusters) if adjusters else train
    return {'candidate':name,'columns':columns,'models':core.fit_rates(transformed,columns),
            'adjusters':adjusters,'rho':0.,'status':'offline_research_only',
            'training_matches':len(train),'trained_through':str(train.date.max().date()),
            'score_contract':core.SCORE_CONTRACT_VERSION}


def predict_candidate(artifact, frame):
    prepared = adjusted_frame(frame,artifact['adjusters']) if artifact['adjusters'] else frame
    proxy = artifact | {'adjusters':{}}
    return core.predict_candidate(proxy,prepared)


def run(source, export, output):
    output.mkdir(parents=True,exist_ok=False)
    protocol = {'created_at':datetime.now(UTC).isoformat(),'candidates':list(CANDIDATES),
                'selection_metric':'paired H/D/A log loss; require repeatable improvement before promotion',
                'evaluation_status':'exploratory: previously reused 2425 and 2526 seasons',
                'future_holdout':'2026-10-15 onward reserved; no 2627 outcomes read; no collection job installed',
                'export_manifest_sha256':core.sha256(export/'manifest.json'),
                'hyperparameters':'Poisson alpha=1; ridge residualization alpha=100; no tuning',
                'market':'no odds loaded, fitted, calibrated or used for selection'}
    protocol['quality_population']='Exclude the 3 quarantined targets and rows with any of them in either last-10 history; same population for every candidate; recompute Elo without quarantined outcomes'
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n',encoding='utf-8',newline='\n')
    frame, manifest = load_export(source,export)
    metadata = json.loads((source/'artifacts/models/v2-field-tilt-box-entries-poisson-2324-2425-2526-20260914t205131z.json').read_text(encoding='utf-8'))
    columns = metadata['numeric_columns']
    report = {'protocol':protocol,'export':str(export),'source_manifest':manifest,'folds':{},'models':{},
              'coverage':{c:{s:int(frame.loc[frame.season==s,c].notna().sum()) for s in core.SEASONS}
                          for c in frame if '.local.' in c}}
    rows=[]
    for season in ('2425','2526'):
        train=frame[frame.season < season].copy(); test=frame[frame.season == season].copy()
        if train.date.max() >= test.date.min():
            raise ValueError('nonchronological split')
        fold={'train_matches':len(train),'test_matches':len(test),'candidates':{}}
        control=None
        for name in CANDIDATES:
            artifact=fit_candidate(name,train,columns)
            p,h,a,matrices=predict_candidate(artifact,test)
            metrics=core.evaluate_predictions(test,p,h,a,matrices)
            if name == 'baseline29':
                control=p
            metrics['paired_vs_baseline']=core.paired_interval(test,p,control)
            metrics['columns']=artifact['columns']
            fold['candidates'][name]=metrics
            for index,(_,row) in enumerate(test.iterrows()):
                rows.append(dict(candidate=name,fold=season,game_id=row.game_id,date=str(row.date.date()),league=row.league,
                                 result=row.result,home_goals=row.home_goals,away_goals=row.away_goals,
                                 p_home=p[index,0],p_draw=p[index,1],p_away=p[index,2],home_rate=h[index],away_rate=a[index],
                                 evidence_type='historical_local_cache_reconstruction'))
            print(f"{season} {name}: loss={metrics['log_loss']:.8f}, delta={metrics['paired_vs_baseline']['delta_log_loss']:+.8f}",flush=True)
        report['folds'][season]=fold
    for name in CANDIDATES:
        artifact=fit_candidate(name,frame,columns)
        artifact['export_manifest_sha256']=protocol['export_manifest_sha256']
        path=output/f'{name}.pkl'
        path.write_bytes(pickle.dumps(artifact,protocol=5))
        report['models'][name]={'path':str(path),'sha256':core.sha256(path),'columns':artifact['columns'],
                                'training_matches':len(frame),'status':'offline_research_only'}
    pd.DataFrame(rows).to_csv(output/'historical_predictions.csv',index=False)
    report['decision']='no promotion; review exploratory comparisons and require future frozen evidence'
    report['created_at']=datetime.now(UTC).isoformat()
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--export',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(args.source,args.export,args.output)
