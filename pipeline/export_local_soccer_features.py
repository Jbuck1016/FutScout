"""Versioned, credential-free export of existing historical WhoScored caches.

Reads only snapshot-selected 2023/24–2025/26 files. Never imports a provider
client, reads .env, connects to a database, or writes into the source cache.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd

from event_phase import event_is_open_play
from soccer_metric_contracts import completed_open_play_box_entry, inside_box

VERSION = "local-cache-rich-v1"
XG_VERSION = "asof_bin_v1_prior20_base010_local"
QUARANTINE = {
    '1834391': 'Holstein Kiel–Bochum, 2025-02-09: local cache has 22 events ending at minute 0; completed 2–2 verified by club report, full event source missing',
    '1824906': 'Montpellier–Saint-Etienne, 2025-03-16: match abandoned, feed ends at minute 62; 0–2 ratified only on 2025-04-02; not a 90-minute observation',
    '1911525': 'Nantes–Toulouse, 2026-05-17: match abandoned at minute 22; local 0–0 is not a verified full-match outcome',
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_jsonl(path: Path, rows) -> dict:
    count = 0
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, allow_nan=False, separators=(',', ':'))+'\n')
            count += 1
    return {'path': path.name, 'rows': count, 'sha256': digest(path), 'bytes': path.stat().st_size}


def load_grid(path: Path) -> dict:
    text = path.read_text(encoding='utf-8')
    block = text.split('insert into public.xt_grid (x_bin,y_bin,v) values', 1)[1].split(';', 1)[0]
    grid = {(int(x), int(y)): float(value)
            for x, y, value in re.findall(r'\((\d+),(\d+),([.\d]+)\)', block)}
    if set(grid) != {(x, y) for x in range(12) for y in range(8)}:
        raise ValueError('xT grid is not complete 12 by 8')
    return grid


def coordinate(value):
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError(f'invalid coordinate: {value}')
    return value


def xt_value(grid, x, y):
    return grid[(min(11, int(x/100*12)), min(7, int(y/100*8)))]


def qualifier_names(event):
    return {q['type']['displayName'] for q in event.get('qualifiers', [])
            if isinstance(q, dict) and isinstance(q.get('type'), dict) and 'displayName' in q['type']}


def shot_bins(x, y, header, big_chance):
    dx, dy = (100-x)*1.05, (y-50)*.68
    distance = math.hypot(dx, dy)
    denominator = dx*dx + dy*dy - 3.66*3.66
    angle = 180.0 if denominator <= 0 else math.degrees(math.atan(7.32*dx/denominator))
    d_bin = next((i+1 for i, bound in enumerate((6, 11, 16, 22, 30)) if distance < bound), 6)
    a_bin = 1 if angle < 12 else 2 if angle < 25 else 3
    return (d_bin, a_bin, bool(header), bool(big_chance)), distance


def summarize_match(payload: dict, match: dict, grid: dict):
    if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
        raise ValueError('missing event payload')
    if str(payload.get('startDate', ''))[:10] != match['match_date']:
        raise ValueError('raw cache date disagrees with snapshot')
    events = payload['events']
    if not events or max(float(e.get('expandedMinute') or e.get('minute') or 0) for e in events) < 80:
        raise ValueError('empty or short completed-match feed')
    if str(payload.get('elapsed')) not in ('FT','F') or int(payload.get('statusCode', -1)) != 6:
        raise ValueError('raw cache is not marked FT')
    # Cached OffsideGiven annotations (type value 10000) can reuse IDs of real
    # events. They contribute to none of our metrics. Never deduplicate across
    # event types and accidentally discard a pass or shot with the same ID.
    football_events = [e for e in events if (e.get('type') or {}).get('displayName') != 'OffsideGiven']
    ids = [str(e['id']) for e in football_events if e.get('id') is not None]
    if len(ids) != len(football_events) or len(set(ids)) != len(ids):
        raise ValueError('missing or duplicate source event ID')
    sides, by_id = [], {}
    for role, team, opponent, goals, allowed in (
        ('home', match['team'], match['opponent'], match['goals_for'], match['goals_against']),
        ('away', match['opponent'], match['team'], match['goals_against'], match['goals_for'])):
        raw = payload[role]
        if int(raw['scores']['fulltime']) != goals:
            raise ValueError(f'{role} fulltime score disagrees with snapshot')
        side = {k: match[k] for k in ('game_id', 'season', 'league', 'match_date')}
        side.update(team=team, opponent=opponent, is_home=(role == 'home'), source_team_id=str(raw['teamId']),
                    source_team_name=raw['name'], goals_for=goals, goals_against=allowed,
                    raw_events=0, shots=0, np_shots=0, np_shots_without_coordinates=0,
                    complete_passes=0, complete_passes_without_coordinates=0,
                    pass_xt_net=0., pass_xt_positive=0., open_play_pass_xt_net=0.,
                    legacy_open_play_box_passes=0, true_open_play_box_entries=0,
                    completed_final_third_entries=0, npxg_for=0., geometry_npxg_for=0.,
                    open_play_npxg_for=0., set_piece_npxg_for=0.,
                    high_recoveries=0, high_tackles_interceptions=0, quality_status='complete')
        sides.append(side)
        by_id[str(raw['teamId'])] = side
    if len(by_id) != 2:
        raise ValueError('match must have two distinct source team IDs')
    shots, unassigned = [], Counter()
    for event in events:
        typ = (event.get('type') or {}).get('displayName')
        side = by_id.get(str(event.get('teamId')))
        if side is None:
            unassigned[str(typ)] += 1
            if typ in ('Pass', 'Goal', 'MissedShots', 'SavedShot', 'ShotOnPost') or event.get('isShot'):
                raise ValueError('unassigned on-ball event')
            continue
        side['raw_events'] += 1
        q = qualifier_names(event)
        x, y = coordinate(event.get('x')), coordinate(event.get('y'))
        end_x, end_y = coordinate(event.get('endX')), coordinate(event.get('endY'))
        phase = event_is_open_play(event.get('qualifiers'))
        if typ == 'BallRecovery' and x is not None and x >= 66.7:
            side['high_recoveries'] += 1
        if typ in ('Tackle', 'Interception') and x is not None and x >= 50:
            side['high_tackles_interceptions'] += 1
        if typ == 'Pass' and (event.get('outcomeType') or {}).get('displayName') == 'Successful':
            side['complete_passes'] += 1
            if None in (x, y, end_x, end_y):
                side['complete_passes_without_coordinates'] += 1
            else:
                xt = xt_value(grid, end_x, end_y)-xt_value(grid, x, y)
                side['pass_xt_net'] += xt
                side['pass_xt_positive'] += max(0., xt)
                side['completed_final_third_entries'] += int(x < 66.7 <= end_x)
                if phase:
                    side['open_play_pass_xt_net'] += xt
                    side['legacy_open_play_box_passes'] += int(inside_box(end_x, end_y))
                    converted = dict(type='Pass', outcome_type='Successful', is_open_play=True,
                                     x=x, y=y, end_x=end_x, end_y=end_y)
                    side['true_open_play_box_entries'] += int(completed_open_play_box_entry(converted))
        if event.get('isShot'):
            side['shots'] += 1
            if 'OwnGoal' in q or 'Penalty' in q:
                continue
            side['np_shots'] += 1
            if x is None or y is None:
                side['np_shots_without_coordinates'] += 1
                continue
            bins, distance = shot_bins(x, y, 'Head' in q, 'BigChance' in q)
            shots.append({k: side[k] for k in ('game_id', 'team', 'season', 'league', 'match_date')} |
                         {'source_event_id': str(event['id']), 'bins': list(bins), 'goal': int(bool(event.get('isGoal'))),
                          'is_open_play': phase, 'distance_m': distance})
    return sides, shots, dict(unassigned)


def score_shots(shots: list[dict]):
    """Bin outcomes update only after ALL shots on that calendar date are scored."""
    count, goals = Counter(), Counter()
    geometry_count, geometry_goals = Counter(), Counter()
    output = []
    grouped = defaultdict(list)
    for shot in shots:
        grouped[shot['match_date']].append(shot)
    previous_date = None
    for date in sorted(grouped):
        for shot in grouped[date]:
            key = tuple(shot['bins'])
            geometry_key = key[:3]
            def shrunk(n, g):
                return float(((Decimal(g)+2)/(Decimal(n)+20)).quantize(Decimal('.0001'), rounding=ROUND_HALF_UP))
            output.append(shot | {'xg': shrunk(count[key], goals[key]),
                                 'geometry_xg': shrunk(geometry_count[geometry_key], geometry_goals[geometry_key]),
                                 'prior_bin_shots': count[key], 'prior_bin_goals': goals[key],
                                 'fit_through_date': previous_date, 'model_version': XG_VERSION})
        for shot in grouped[date]:
            key = tuple(shot['bins'])
            count[key] += 1; goals[key] += shot['goal']
            geometry_count[key[:3]] += 1; geometry_goals[key[:3]] += shot['goal']
        previous_date = date
    return output


def enrich_sides(sides, scored):
    keyed = {(r['game_id'], r['team']): r.copy() for r in sides}
    for shot in scored:
        row = keyed[(shot['game_id'], shot['team'])]
        row['npxg_for'] += shot['xg']
        row['geometry_npxg_for'] += shot['geometry_xg']
        row['open_play_npxg_for' if shot['is_open_play'] else 'set_piece_npxg_for'] += shot['xg']
    for key, row in keyed.items():
        if row['np_shots_without_coordinates']:
            for field in ('npxg_for', 'geometry_npxg_for', 'open_play_npxg_for', 'set_piece_npxg_for'):
                row[field] = None
        if row['complete_passes_without_coordinates']:
            for field in ('pass_xt_net', 'pass_xt_positive', 'open_play_pass_xt_net', 'true_open_play_box_entries'):
                row[field] = None
    for key, row in keyed.items():
        other = keyed[(row['game_id'], row['opponent'])]
        for field in ('npxg_for', 'geometry_npxg_for', 'open_play_npxg_for', 'set_piece_npxg_for'):
            row[field.replace('_for', '_against')] = other[field]
        row['pass_xt_net_against'] = other['pass_xt_net']
        row['pass_xt_net_difference'] = (row['pass_xt_net']-other['pass_xt_net']
                                         if row['pass_xt_net'] is not None and other['pass_xt_net'] is not None else None)
        row['xg_per_np_shot'] = row['npxg_for']/row['np_shots'] if row['np_shots'] and row['npxg_for'] is not None else None
        row['definition_version'] = VERSION
    return list(keyed.values())


ROLLING_METRICS = ('npxg_for', 'npxg_against', 'geometry_npxg_for', 'geometry_npxg_against',
                   'open_play_npxg_for', 'open_play_npxg_against', 'set_piece_npxg_for', 'set_piece_npxg_against',
                   'pass_xt_net', 'pass_xt_positive', 'open_play_pass_xt_net', 'pass_xt_net_difference',
                   'true_open_play_box_entries', 'legacy_open_play_box_passes', 'completed_final_third_entries',
                   'high_recoveries', 'high_tackles_interceptions')


def rolling_features(sides):
    history = defaultdict(list)
    grouped = defaultdict(list)
    for row in sides:
        grouped[row['match_date']].append(row)
    output = []
    for date in sorted(grouped):
        for row in grouped[date]:
            prior = history[(row['league'], row['team'])]
            record = {k: row[k] for k in ('game_id', 'team', 'opponent', 'is_home', 'season', 'league', 'match_date')}
            record['history_cutoff_date'] = prior[-1]['match_date'] if prior else None
            record['source_game_ids'] = [item['game_id'] for item in prior[-10:]]
            for window in (3, 5, 10):
                sample = prior[-window:]
                record[f'prior_count_{window}'] = len(sample)
                for metric in ROLLING_METRICS:
                    values = [item[metric] for item in sample]
                    # No partial sums disguised as zero; any missing observation invalidates that window.
                    record[f'{metric}_{window}'] = (sum(values)/len(values) if values and all(v is not None for v in values) else None)
            output.append(record)
        for row in sorted(grouped[date], key=lambda r: (r['game_id'], r['team'])):
            history[(row['league'], row['team'])].append(row)
    return output


def export(cache: Path, snapshot: Path, output: Path, grid_path: Path):
    snapshot_manifest = json.loads(snapshot.with_suffix('.manifest.json').read_text(encoding='utf-8'))
    if digest(snapshot) != snapshot_manifest['sha256']:
        raise ValueError('snapshot digest mismatch')
    matches = [json.loads(line) for line in snapshot.read_text(encoding='utf-8').splitlines()]
    if len(matches) != 5255 or len({r['game_id'] for r in matches}) != 5255:
        raise ValueError('unexpected snapshot population')
    if set(r['season'] for r in matches) != {'2324', '2425', '2526'}:
        raise ValueError('only approved historical seasons allowed')
    output.mkdir(parents=True, exist_ok=False)
    grid = load_grid(grid_path)
    sides, shots, lineage, failures, quarantined = [], [], [], [], []
    team_names = defaultdict(set)
    unassigned = Counter()
    for index, match in enumerate(matches):
        path = cache/f"{match['league']}_{match['season']}"/f"{match['game_id']}.json"
        try:
            before = path.stat()
            raw = path.read_bytes()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('source file changed during read')
            payload=json.loads(raw)
            if str(match['game_id']) in QUARANTINE:
                # Preserve the actual file and identity while declining to turn
                # a short feed into manufactured full-match numeric values.
                side=[]
                for role,team,opponent in (('home',match['team'],match['opponent']),('away',match['opponent'],match['team'])):
                    item={field:None for field in (*ROLLING_METRICS,'np_shots','np_shots_without_coordinates',
                        'complete_passes_without_coordinates','raw_events')}
                    item.update({k:match[k] for k in ('game_id','season','league','match_date')})
                    item.update(team=team,opponent=opponent,is_home=role=='home',source_team_id=str(payload[role]['teamId']),
                                source_team_name=payload[role]['name'],quality_status='quarantined')
                    side.append(item)
                shot=[];unassigned_types={}
                quarantined.append({'game_id':str(match['game_id']),'path':str(path),'reason':QUARANTINE[str(match['game_id'])]})
            else:
                side, shot, unassigned_types = summarize_match(payload, match, grid)
            sides.extend(side); shots.extend(shot); unassigned.update(unassigned_types)
            for row in side:
                team_names[(row['league'], row['source_team_id'])].add(row['team'])
            lineage.append({'game_id': match['game_id'], 'season': match['season'], 'league': match['league'],
                            'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
                            'mtime_ns': after.st_mtime_ns, 'event_count': len(payload['events']),
                            'quality_status':side[0]['quality_status'],
                            'offside_given_id_collisions':sum(1 for e in payload['events']
                                if (e.get('type') or {}).get('displayName')=='OffsideGiven'
                                and str(e.get('id')) in {str(x.get('id')) for x in payload['events']
                                    if (x.get('type') or {}).get('displayName')!='OffsideGiven'}),
                            'source_teams': [{k: r[k] for k in ('team', 'source_team_id', 'source_team_name', 'is_home')} for r in side]})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failures.append({'game_id': match['game_id'], 'path': str(path), 'reason': str(exc)})
        if (index+1) % 500 == 0:
            print(f'Read {index+1}/{len(matches)} source files; failures={len(failures)}', flush=True)
    ambiguous = {str(key): sorted(names) for key, names in team_names.items() if len(names) > 1}
    audit = {'matches_requested': len(matches), 'matches_valid': len(lineage), 'source_bytes': sum(r['bytes'] for r in lineage),
             'failures': failures, 'quarantined':quarantined, 'ambiguous_source_team_mapping': ambiguous, 'unassigned_administrative_events': dict(unassigned),
             'excluded_source_exception': {'game_id': '1741059', 'fixture': 'Rennes–Metz 2023-08-13',
                                           'reason': 'excluded by existing training snapshot; no invented event data'}}
    (output/'source_audit.json').write_text(json.dumps(audit, indent=2)+'\n', encoding='utf-8', newline='\n')
    if failures or ambiguous:
        raise ValueError(f"export blocked: {len(failures)} source failures, {len(ambiguous)} ambiguous team mappings; see source_audit.json")
    scored = score_shots(shots)
    enriched = enrich_sides(sides, scored)
    rolling = rolling_features(enriched)
    outputs = {name: write_jsonl(output/name, rows) for name, rows in (
        ('source_lineage.jsonl', lineage), ('shots.jsonl', scored), ('observations.jsonl', enriched), ('rolling_features.jsonl', rolling))}
    definitions = output/'definitions'
    definitions.mkdir()
    root = Path(__file__).resolve().parent
    source_definitions = [Path(__file__).resolve(), root/'event_phase.py', root/'soccer_metric_contracts.py', grid_path]
    code = {}
    for path in source_definitions:
        (definitions/path.name).write_bytes(path.read_bytes())
        code[path.name] = {'source': str(path), 'sha256': digest(path)}
    manifest = {'export_version': VERSION, 'created_at': datetime.now(UTC).isoformat(),
                'status': 'complete_with_explicit_quarantine', 'quarantined':quarantined,
                'snapshot_path': str(snapshot), 'snapshot_sha256': digest(snapshot),
                'matches': len(matches), 'team_sides': len(enriched), 'non_penalty_shots_scored': len(scored),
                'source_bytes': audit['source_bytes'], 'outputs': outputs, 'definitions': code,
                'xg_version': XG_VERSION, 'xg_fit_rule': 'strictly earlier calendar dates; bin prior 20 shots and base 0.10; ROUND_HALF_UP 4 decimals',
                'geometry_xg': 'same prior-date bin estimator excluding BigChance from bins',
                'xt_version': 'repository static 12x8 grid; signed/positive successful-pass value difference; not learned or provider xT',
                'missing_policy': 'missing required shot/pass coordinates make corresponding match metrics and subsequent windows missing',
                'scope': 'private local historical reconstruction; no new collection, keys, credentials, network or operational writes',
                'nonmissing': {metric: sum(row[metric] is not None for row in enriched) for metric in ROLLING_METRICS},
                'shots_by_season': dict(Counter(row['season'] for row in scored)),
                'source_audit_sha256': digest(output/'source_audit.json')}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: manifest[k] for k in ('status','matches','team_sides','non_penalty_shots_scored','shots_by_season','nonmissing')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--grid-sql', type=Path, default=Path(__file__).resolve().parents[1]/'supabase/migrations/20260723193027_expected_threat.sql')
    args = parser.parse_args()
    export(args.cache, args.snapshot, args.output, args.grid_sql)
