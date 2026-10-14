"""Offline numeric-column coercion and score-grid payload audit; no service clients."""
import argparse
from collections import defaultdict
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import gzip
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter
import tracemalloc

import numpy as np
from scipy.stats import poisson

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_probabilities import score_matrix, result_masses, score_dict
from simulate_league_table import prepare_fixtures

FIELDS=('home_win_probability','draw_probability','away_win_probability')


def quantize(value,places):
    return float(Decimal(str(value)).quantize(Decimal(1).scaleb(-places),rounding=ROUND_HALF_UP))


def instant(value):
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def run(historical,snapshot,output):
    source=snapshot.read_bytes(); source_hash=hashlib.sha256(source).hexdigest()
    payload=json.loads(source)
    pairs=[(float(r['home_rate']),float(r['away_rate'])) for r in csv.DictReader(historical.open(encoding='utf-8'))
           if r['candidate']=='baseline29' and r['fold']=='2526']
    errors=[]; counts=[]; legacy_bytes=0; adaptive_bytes=0
    for h,a in pairs:
        matrix=score_matrix(h,a); p=result_masses(matrix)
        stored=np.array([quantize(v,7) for v in p]); rounded_rates=(quantize(h,4),quantize(a,4))
        errors.append((float(np.max(np.abs(stored-p))),float(abs(stored.sum()-1)),
                       float(np.max(np.abs(result_masses(score_matrix(*rounded_rates))-p))),
                       max(abs(rounded_rates[0]-h),abs(rounded_rates[1]-a))))
        counts.append(matrix.size)
        grid=np.arange(9); old=np.outer(poisson.pmf(grid,h),poisson.pmf(grid,a)); old/=old.sum()
        old_dict={f'{x}-{y}':float(old[x,y]) for x in range(9) for y in range(9)}
        new_dict={f'{x}-{y}':float(matrix[x,y]) for x in range(len(matrix)) for y in range(len(matrix))}
        legacy_bytes+=len(json.dumps(old_dict).encode()); adaptive_bytes+=len(json.dumps(new_dict).encode())
    maxima=np.max(errors,axis=0)
    assert maxima[0]<=5.0001e-8 and maxima[1]<=1.50001e-7 and maxima[3]<=5.0001e-5
    # Rebuild only a memory copy of the existing frozen forecast. No outcomes
    # are loaded, scored or used, and the original snapshot stays byte-identical.
    start=perf_counter()
    for row in payload['predictions']:
        h,a=float(row['home_expected_goals']),float(row['away_expected_goals'])
        m=score_matrix(h,a)
        row['scoreline_distribution']={f'{x}-{y}':float(m[x,y]) for x in range(len(m)) for y in range(len(m))}
        row.update(dict(zip(FIELDS,map(float,result_masses(m)))))
    generation_seconds=perf_counter()-start
    start=perf_counter(); encoded=(json.dumps(payload,indent=2,sort_keys=True)+'\n').encode()
    serialization_seconds=perf_counter()-start
    tracemalloc.start(); start=perf_counter(); parsed=json.loads(encoded)
    parse_seconds=perf_counter()-start; _,peak=tracemalloc.get_traced_memory(); tracemalloc.stop()
    as_of=instant(payload['as_of']); through=instant(payload.get('evaluation_through',(as_of+timedelta(days=7)).isoformat()))
    slate=[r for r in parsed['predictions'] if as_of<instant(r['date'])<=through]
    strip={'league','date','home_team','away_team','explanation','score_distribution_contract'}
    body=[{k:v for k,v in r.items() if k not in strip}|{'as_of':payload['as_of'],'forecast_kind':payload['forecast_kind']} for r in slate]
    fixtures=[]; leagues=defaultdict(int); explicit_precision=[]
    for row in parsed['predictions']:
        leagues[row['league']]+=1
        fixture={'home_team':row['home_team'],'away_team':row['away_team'],
                 'expected_home_goals':quantize(row['home_expected_goals'],4),
                 'expected_away_goals':quantize(row['away_expected_goals'],4),
                 **{k:quantize(row[k],7) for k in FIELDS},
                 'score_probabilities':[{'home_goals':int(k.split('-')[0]),'away_goals':int(k.split('-')[1]),'probability':v}
                                        for k,v in row['scoreline_distribution'].items()]}
        fixtures.append(fixture)
    tracemalloc.start(); start=perf_counter()
    prepared=prepare_fixtures(fixtures,{r[k] for r in fixtures for k in ('home_team','away_team')})
    prepare_seconds=perf_counter()-start; _,prepare_peak=tracemalloc.get_traced_memory(); tracemalloc.stop()
    for original,fixture in zip(parsed['predictions'],prepared):
        explicit_precision.append(max(abs(fixture['result_probabilities'][i]-original[k]) for i,k in enumerate(FIELDS)))
    assert max(explicit_precision)<=1.1e-7
    assert snapshot.read_bytes()==source
    schema=Path(__file__).resolve().parents[2]/'supabase/migrations/20260901230956_model_data_foundations.sql'
    sql=schema.read_text(encoding='utf-8')
    assert 'home_expected_goals numeric(7,4)' in sql and 'home_win_probability numeric(8,7)' in sql
    report={'mode':'offline Decimal coercion emulation and in-memory payload profile; not a database round trip',
            'schema_path':str(schema),'schema_sha256':hashlib.sha256(schema.read_bytes()).hexdigest(),
            'historical_rate_pairs':len(pairs),'max_headline_rounding_error':maxima[0],
            'max_rounded_probability_sum_error':maxima[1],'max_regenerated_result_error_from_four_decimal_rates':maxima[2],
            'max_goal_rate_rounding_error':maxima[3],
            'precision_contract':{'local_headline_vs_grid_atol':2e-12,'stored_headline_vs_jsonb_mass_atol':5.0002e-8,
                                  'stored_probability_sum_atol':1.50001e-7,'schema_sum_constraint':1e-6,
                                  'instruction':'Use JSONB explicit scores for stored forecasts. Four-decimal goal rates cannot recreate the original exact distribution.'},
            'historical_score_dict_bytes':{'legacy':legacy_bytes,'adaptive':adaptive_bytes,'ratio':adaptive_bytes/legacy_bytes,
                                           'min_cells':min(counts),'median_cells':float(np.median(counts)),'max_cells':max(counts)},
            'frozen_snapshot_profile':{'path':str(snapshot),'sha256':source_hash,'unchanged':True,
                'fixture_count':len(fixtures),'by_league':dict(leagues),'original_file_bytes':len(source),
                'adaptive_in_memory_bytes':len(encoded),'file_ratio':len(encoded)/len(source),
                'adaptive_gzip_bytes':len(gzip.compress(encoded,mtime=0)),
                'scoring_horizon_fixtures':len(slate),'horizon_row_body_bytes_excluding_model_run_id':len(json.dumps(body).encode()),
                'grid_build_seconds':generation_seconds,'json_serialize_seconds':serialization_seconds,
                'json_parse_seconds_under_tracemalloc':parse_seconds,'json_parse_peak_bytes':peak,
                'simulation_prepare_seconds_under_tracemalloc':prepare_seconds,'simulation_prepare_peak_bytes':prepare_peak,
                'max_consumer_error_after_stored_headline_alignment':max(explicit_precision)},
            'static_findings':['No JSONB object byte/cell cap in inspected migration; actual storage is not measured by JSON byte counts.',
                'Persistence emits a single upsert for the configured 7-day slate (CLI permits 1-14 days); no byte-based batching.',
                'Ledger reader requests score grids in pages of 1000; upstream response limits/timeouts are not recorded locally.',
                'Model-review dashboard builder omits scoreline_distribution; simulator accepts variable-length explicit score lists.',
                'No provider/service/network call; deployment gateway limits, database storage/TOAST and end-to-end latency remain unverified.']}
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--historical',type=Path,required=True)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(args.historical,args.snapshot,args.output)
