"""Four-fixture saved-data audit; reads retained raw archives, makes no API calls."""
import gzip
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
report_dir = root / 'artifacts/model_reports'
samples = json.loads((report_dir / 'overnight_identity_db_samples.json').read_text(encoding='utf-8'))
results = []
for sample in samples:
    source_id = Path(sample['object_path']).name.removesuffix('.json.gz')
    path = Path.home() / 'soccerdata/data/WhoScored/events' / f"{sample['league']}_{sample['season']}" / f'{source_id}.json'
    blob = path.read_bytes()
    raw = json.loads(blob)
    original = {str(e['id']): e for e in raw['events']}
    rows = sample['events']
    errors = []
    digest = hashlib.sha256(gzip.compress(blob, compresslevel=9, mtime=0)).hexdigest()
    if digest != sample['content_sha256']:
        errors.append('archive compressed checksum mismatch')
    if len(original) != len(raw['events']) or len({str(e['ws_id']) for e in rows}) != len(rows):
        errors.append('duplicate event ID')
    if set(original) != {str(e['ws_id']) for e in rows} or len(rows) != sample['event_count']:
        errors.append('event ID population mismatch')
    for e in rows:
        src = original.get(str(e['ws_id']), {})
        for dbk, rk in [('team_id','teamId'),('player_id','playerId'),('event_id','eventId')]:
            if str(e[dbk]) != str(src.get(rk)):
                errors.append(f"{e['ws_id']}: {dbk} mismatch")
        if e['player_id'] is not None and e['player'] != raw['playerIdNameDictionary'].get(str(e['player_id'])):
            errors.append(f"{e['ws_id']}: player name mismatch")
    fixture = sample['fixture']
    if fixture['date'][:10] != raw['startDate'][:10]:
        errors.append('fixture date mismatch')
    if [fixture['home_score'],fixture['away_score']] != [int(x.strip()) for x in raw['ftScore'].split(':')]:
        errors.append('fixture score mismatch')
    # Names are compared explicitly, never silently canonicalized.
    name_comparison = {side: {'raw': raw[side]['name'], 'database': fixture[f'{side}_team']} for side in ('home','away')}
    for side, pair in name_comparison.items():
        if pair['raw'] != pair['database']:
            errors.append(f'{side} fixture name differs; mapping review required')
    results.append({'game_id':sample['game_id'],'source_game_id':source_id,'league':sample['league'],
                    'events_checked':len(rows),'source_players':len(raw['playerIdNameDictionary']),
                    'raw_team_ids':{s:raw[s]['teamId'] for s in ('home','away')},
                    'fixture_names':name_comparison,'compressed_sha256':digest,'errors':errors})
out = {'scope':'Four additional current-season fixtures, one per other modeled league; source consistency, not independent provider verification.',
       'events_checked':sum(x['events_checked'] for x in results),'results':results}
(report_dir / 'overnight_identity_audit.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out,indent=2))
