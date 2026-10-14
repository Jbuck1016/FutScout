"""Read existing raw cache and export historical player lineage and pre-match proxies."""
import argparse
from collections import Counter
import json
from pathlib import Path

from export_local_soccer_features import digest, write_jsonl
from local_player_strength import VERSION, extract_usage, build_features


def run(source, export, output):
    output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((export/'manifest.json').read_text(encoding='utf-8'))
    snapshot=source/'artifacts/training_snapshots/top_five_2324_2526_v1.jsonl'
    assert digest(snapshot)==manifest['snapshot_sha256']
    targets=[json.loads(s) for s in snapshot.read_text(encoding='utf-8').splitlines()]
    match_by_id={m['game_id']:m for m in targets}
    lineage=[json.loads(s) for s in (export/'source_lineage.jsonl').read_text(encoding='utf-8').splitlines()]
    excluded={r['game_id'] for r in manifest['quarantined']}
    observations=[]; failures=[]
    def missing(match,side,reason):
        return {k:match[k] for k in ('game_id','match_date','league','season')} | {
            'team':match['team'] if side=='home' else match['opponent'],'is_home':side=='home',
            'quality_status':'missing','reason':reason,'players':[]}
    for index,item in enumerate(lineage):
        if item['game_id'] in excluded:
            observations.extend(missing(match_by_id[item['game_id']],side,'quarantined event feed') for side in ('home','away'))
            continue
        path=Path(item['path'])
        assert digest(path)==item['sha256']
        payload=json.loads(path.read_text(encoding='utf-8'))
        for side in ('home','away'):
            try:
                observations.append(extract_usage(payload,side,match_by_id[item['game_id']]))
            except (ValueError,KeyError,TypeError) as exc:
                failures.append({'game_id':item['game_id'],'side':side,'reason':str(exc),'path':str(path)})
                observations.append(missing(match_by_id[item['game_id']],side,str(exc)))
        if (index+1)%1000==0:
            print(f'player source audit {index+1}/{len(lineage)}',flush=True)
    features,plans=build_features(targets,observations)
    outputs={name:write_jsonl(output/name,rows) for name,rows in
             [('player_observations.jsonl',observations),('player_features.jsonl',features),('expected_players.jsonl',plans)]}
    players=[p for row in observations for p in row['players']]
    report={'version':VERSION,'source_export_manifest_sha256':digest(export/'manifest.json'),
            'snapshot_sha256':digest(snapshot),'raw_files_rehashed':len(lineage)-len(excluded),
            'team_observations':len(observations),'complete_team_observations':sum(r['quality_status']=='complete' for r in observations),
            'player_appearances':len(players),
            'unique_players':len({p['player_id'] for p in players}),
            'missing_ratings':sum(p['rating'] is None for p in players),
            'roles':dict(Counter(p['role'] for p in players)),'failures':failures,
            'ready_team_targets':sum(r['ready'] for r in features),'team_targets':len(features),'outputs':outputs,
            'source_timestamp_limitation':'raw historical final data, no lineup or rating publication snapshots',
            'minutes_contract':'interval from starter/substitution metadata to sub-out/red/fulltime; normalize expanded duration to 90; approximate, not official minutes',
            'rating_contract':'last provider retrospective match rating; lagged <=20 appearances, shrink 900 minutes to earlier role mean',
            'expected_usage':'prior three completed observations weights 0.5/0.3/0.2 versus prior ten reference, each normalized to 990',
            'uncertainty':'recent-lineup scenario spread and approximate rating SE, not calibrated forecast intervals',
            'fallback':'no missing source in prior ten team games; at least two earlier team observations, >=80% expected rating coverage, latest usage <=60 days; else neutral delta',
            'code':{p.name:digest(p) for p in [Path(__file__),Path(__file__).with_name('local_player_strength.py')]}}
    (output/'manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n')
    definitions=output/'definitions'; definitions.mkdir()
    for path in (Path(__file__),Path(__file__).with_name('local_player_strength.py')):
        (definitions/path.name).write_bytes(path.read_bytes())
    print(json.dumps({k:v for k,v in report.items() if k not in ('outputs','code','failures')},indent=2))
    print('failed team sides:',len(failures),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--export',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(args.source,args.export,args.output)
