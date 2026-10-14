"""Prove prior evidence is unchanged and final hardened code reproduces v3 rows."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import local_player_strength as layer


def read_rows(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(source,players,repair):
    hashes=json.loads((repair/'old_evidence_sha256.json').read_text(encoding='utf-8'))
    assert all(digest(Path(path))==expected for path,expected in hashes.items())
    snapshot=source/'artifacts/training_snapshots/top_five_2324_2526_v1.jsonl'
    features,plans=layer.build_features(read_rows(snapshot),read_rows(players/'player_observations.jsonl'))
    assert features==read_rows(players/'player_features.jsonl')
    assert plans==read_rows(players/'expected_players.jsonl')
    by_key={(r['game_id'],r['team']):r for r in plans}
    rennes=by_key['1911289','Rennes']; bournemouth=by_key['1903294','Bournemouth']
    assert max(rennes['expected_minutes'].values())<=90
    assert '357073' not in bournemouth['expected_minutes']
    assert bournemouth['membership_evidence']['357073']['teams']==['Manchester City']
    assert bournemouth['membership_evidence']['357073']['observed_date']=='2026-01-17'
    manifest=json.loads((players/'manifest.json').read_text(encoding='utf-8'))
    result={'status':'passed','old_evidence_files_unchanged':len(hashes),
            'exact_feature_rows_rebuilt':len(features),'exact_expected_plans_rebuilt':len(plans),
            'current_module_sha256':digest(Path(layer.__file__)),
            'export_definition_sha256':manifest['code']['local_player_strength.py'],
            'source_note':'Final source adds allocation-bound input rejection after initial v3 export; every saved valid feature and plan is exactly reproduced.',
            'review_examples':{'Rennes_1911289':{'Rouault_minutes':rennes['expected_minutes']['416149'],
                                               'Samba_minutes':rennes['expected_minutes']['105198'],
                                               'replacement_by_role':rennes['expected_replacement_by_role']},
                               'Bournemouth_1903294':{'Semenyo_expected':False,'prior_membership':bournemouth['membership_evidence']['357073'],
                                                     'removed_minutes':bournemouth['membership_removed_minutes']['357073']}}}
    (repair/'evidence_preservation_and_rebuild.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--players',type=Path,required=True)
    parser.add_argument('--repair',type=Path,required=True)
    args=parser.parse_args()
    verify(args.source,args.players,args.repair)
