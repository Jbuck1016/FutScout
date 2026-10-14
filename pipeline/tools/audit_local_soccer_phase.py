"""Reconcile legacy box-pass values against cached events without changing exports."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research_local_rich_features as rich
import research_soccer_forecasts as core
from event_phase import event_is_open_play


def audit(source, export, output):
    manifest = json.loads((export/'manifest.json').read_text(encoding='utf-8'))
    lineage = [json.loads(s) for s in (export/'source_lineage.jsonl').read_text(encoding='utf-8').splitlines()]
    observations = [json.loads(s) for s in (export/'observations.jsonl').read_text(encoding='utf-8').splitlines()]
    by_game = {}
    for row in observations:
        by_game.setdefault(row['game_id'], []).append(row)
    quarantined = {r['game_id'] for r in manifest['quarantined']}
    rows, excluded_tags = [], Counter()
    for index, item in enumerate(lineage):
        if item['game_id'] in quarantined:
            continue
        path = Path(item['path'])
        raw = path.read_bytes()
        import hashlib
        assert hashlib.sha256(raw).hexdigest() == item['sha256'], path
        payload = json.loads(raw)
        for side in by_game[item['game_id']]:
            events = [e for e in payload['events']
                      if str(e.get('teamId')) == side['source_team_id']
                      and (e.get('type') or {}).get('displayName') == 'Pass'
                      and (e.get('outcomeType') or {}).get('displayName') == 'Successful'
                      and e.get('endX') is not None and e['endX'] >= 83
                      and e.get('endY') is not None and 21 <= e['endY'] <= 79]
            open_play = sum(event_is_open_play(e.get('qualifiers')) for e in events)
            assert open_play == side['legacy_open_play_box_passes']
            for event in events:
                if not event_is_open_play(event.get('qualifiers')):
                    excluded_tags.update(q['type']['displayName'] for q in event['qualifiers']
                                         if isinstance(q.get('type'), dict))
            rows.append({k:side[k] for k in ('game_id','team','league','match_date','is_home')} |
                        {'all_phase':len(events),'open_play':open_play})
        if (index+1) % 1000 == 0:
            print(f'reconciled {index+1}/{len(lineage)} raw files', flush=True)
    frame, _ = rich.load_export(source, export)
    observations_frame = pd.DataFrame(rows)
    rolling_rows = []
    for _, group in observations_frame.groupby(['league','team']):
        ordered = group.sort_values(['match_date','game_id']).copy()
        assert not ordered.match_date.duplicated().any()
        for window in (3,5,10):
            ordered[f'all_phase_{window}'] = ordered.all_phase.shift().rolling(window,min_periods=1).mean()
        rolling_rows.append(ordered)
    rolled = pd.concat(rolling_rows).set_index(['game_id','is_home'])
    results = []
    examples = []
    for side, is_home in (('team',True),('opponent',False)):
        for window in (3,5,10):
            reference = frame.game_id.map(rolled.xs(is_home,level='is_home')[f'all_phase_{window}'])
            legacy = frame[f'{side}.box_entries_pass_{window}']
            valid = reference.notna() & legacy.notna()
            difference = (legacy[valid] - reference[valid]).abs()
            results.append({'side':side,'window':window,'valid_rows':int(valid.sum()),
                            'different_beyond_rounding':int((difference>.000051).sum()),
                            'max_difference':float(difference.max())})
            for idx in difference[difference>.000051].head(3).index:
                examples.append({'game_id':frame.loc[idx,'game_id'],'side':side,'window':window,
                                 'snapshot':float(legacy[idx]),'raw_all_phase':float(reference[idx])})
    result = {'status':'complete','manifest_sha256':core.sha256(export/'manifest.json'),
              'raw_files_rehashed':len(lineage)-len(quarantined),
              'team_rows':len(rows),'all_phase_completed_box_passes':int(observations_frame.all_phase.sum()),
              'open_play_completed_box_passes':int(observations_frame.open_play.sum()),
              'snapshot_vs_all_phase':results,'remaining_difference_examples':examples,
              'excluded_qualifier_counts':dict(excluded_tags),
              'interpretation':'Compare actual snapshot values with all-phase raw completions; intended SQL open-play predicate alone does not establish stored phase validity.'}
    (output/'phase_reconciliation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('excluded_qualifier_counts','remaining_difference_examples')},indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--export',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    audit(args.source,args.export,args.output)
