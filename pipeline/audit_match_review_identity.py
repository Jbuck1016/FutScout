"""Verify one review's relational event identities against its retained raw archive."""
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
raw_path = Path.home() / 'soccerdata/data/WhoScored/events/ENG-Premier League_2627/1983575.json'
raw = raw_path.read_bytes()
source = json.loads(raw)
db = json.loads((ROOT / 'artifacts/model_reports/match_review_db_events.json').read_text(encoding='utf-8'))
lookup = {str(e['id']): e for e in source['events']}
assert len(lookup) == len(source['events']) == len(db) == 1495
assert hashlib.sha256(gzip.compress(raw, compresslevel=9, mtime=0)).hexdigest() == '8cf3f17c757edcdbf7ef3261b10db300ecc895aafa4d4edd1711d60be4755128'
assert source['startDate'][:10] == '2026-09-19'
assert (source['home']['name'], source['away']['name'], source['ftScore']) == ('Brighton','Arsenal','3 : 0')
errors=[]
for event in db:
    original=lookup.get(str(event['ws_id']))
    if original is None:
        errors.append({'ws_id':event['ws_id'],'reason':'missing raw event'})
        continue
    for field,rawfield in [('team_id','teamId'),('player_id','playerId'),('event_id','eventId')]:
        if str(event[field]) != str(original.get(rawfield)):
            errors.append({'ws_id':event['ws_id'],'field':field})
    if event['player_id'] is not None and event['player'] != source['playerIdNameDictionary'].get(str(event['player_id'])):
        errors.append({'ws_id':event['ws_id'],'field':'player name'})
assert not errors,errors[:10]
report={'game_id':'fd-560586','source_game_id':'1983575','status':'raw_archive_identity_verified','events_verified':len(db),'players_in_source':len(source['playerIdNameDictionary']),'compressed_sha256':hashlib.sha256(gzip.compress(raw,compresslevel=9,mtime=0)).hexdigest(),'scope':'Matches retained WhoScored archive and verified storage manifest; not independent second-provider verification.'}
out=ROOT/'artifacts/model_reports/match_review_identity_audit.json'
out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report))
