"""Retrospective shot/exposure slices; never a pre-match feature source."""
from collections import Counter
import math


def build_states(raw, shots):
    teams = [raw['home']['teamId'], raw['away']['teamId']]
    names = [raw['home']['name'], raw['away']['name']]
    periods = {1: 0, 2: 45 * 60}
    if any(e['period']['value'] in (3, 4, 5) for e in raw['events']):
        raise ValueError('Extra time/shootouts require a separate period contract')
    events = [e for e in raw['events'] if e['period']['value'] in periods]
    ids = [e['id'] for e in events]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate raw event IDs')
    clock = lambda e: int(e['minute']) * 60 + int(e.get('second', 0))
    ends, offsets, elapsed = {}, {}, 0
    for period, start in periods.items():
        markers = [clock(e) for e in events if e['period']['value'] == period and e['type']['displayName'] == 'End']
        if not markers or len(set(markers)) != 1 or markers[0] <= start:
            raise ValueError('Missing or conflicting period-end markers')
        ends[period] = markers[0]
        offsets[period] = elapsed
        elapsed += markers[0] - start
    # Period first: 45+2 must precede 2H 45:00. Preserve source order within a second.
    ordered = sorted(enumerate(events), key=lambda pair: (pair[1]['period']['value'], clock(pair[1]), pair[0]))
    shot_index = {}
    for s in shots:
        if not math.isfinite(float(s['xg'])) or not 0 <= float(s['xg']) <= 1:
            raise ValueError('Invalid fitted shot estimate')
        key = (s['period'], s['minute'], s['second'], s['team'])
        if key in shot_index:
            raise ValueError('Ambiguous shot snapshot join')
        shot_index[key] = s
    score, previous, segments, records = [0, 0], 0, [], []
    state = lambda: 'level' if score[0] == score[1] else ('home_leading' if score[0] > score[1] else 'away_leading')
    seen, shot_times = set(), {}
    goal_seconds = Counter()
    for _, e in ordered:
        p, c = e['period']['value'], clock(e)
        if not periods[p] <= c <= ends[p]:
            raise ValueError('Event outside period bounds')
        t = offsets[p] + c - periods[p]
        if e.get('isShot'):
            key = (p, e['minute'], e.get('second', 0), names[teams.index(e['teamId'])])
            if key not in shot_index:
                raise ValueError('Raw shot absent from fitted snapshot')
            s = shot_index[key]
            seen.add(key)
            shot_times[key] = t
            records.append({'t': t, 'state': state(), 'side': teams.index(e['teamId']), 'xg': float(s['xg'])})
        if e['type']['displayName'] == 'Goal':
            segments.append((previous, t, state()))
            side = teams.index(e['teamId'])
            own = e.get('isOwnGoal') or any(q['type']['displayName'] == 'OwnGoal' for q in e.get('qualifiers', []))
            score[1 - side if own else side] += 1
            previous = t
            goal_seconds[(p, c)] += 1
    segments.append((previous, elapsed, state()))
    if seen != set(shot_index):
        raise ValueError('Unmatched fitted shots')
    if raw.get('ftScore') and [int(v.strip()) for v in raw['ftScore'].split(':')] != score:
        raise ValueError('Goal events do not reconcile to final score')
    windows = [('full', 'Full match', 0, elapsed), ('first', 'First half + added time', 0, offsets[2]),
               ('second', 'Second half + added time', offsets[2], elapsed),
               ('early', 'First 30 elapsed minutes', 0, min(1800, elapsed)),
               ('late', 'Last 30 elapsed minutes', max(0, elapsed - 1800), elapsed)]
    rows = []
    for key, label, start, end in windows:
        for selected in ('all', 'level', 'home_leading', 'away_leading'):
            seconds = sum(max(0, min(b, end) - max(a, start)) for a, b, st in segments if selected == 'all' or selected == st)
            chosen = [r for r in records if start <= r['t'] < end and (selected == 'all' or r['state'] == selected)]
            # A recorded shot exactly at the final whistle belongs to the finishing window.
            if end == elapsed:
                chosen += [r for r in records if r['t'] == elapsed and (selected == 'all' or r['state'] == selected)]
            sides = []
            for side in (0, 1):
                ss = [r for r in chosen if r['side'] == side]
                total = sum(r['xg'] for r in ss)
                sides.append({'shots': len(ss), 'xg': round(total, 4), 'shots_per90': round(len(ss) * 5400 / seconds, 2) if seconds else None})
            rows.append({'window': key, 'state': selected, 'seconds': seconds, 'teams': sides})
    return {'teams': names, 'duration_seconds': elapsed,
            'shot_elapsed_seconds': [shot_times[(s['period'], s['minute'], s['second'], s['team'])] for s in shots],
            'windows': [{'id': k, 'label': l} for k, l, _, _ in windows],
            'rows': rows, 'shot_count': len(records), 'source': 'Retained WhoScored raw period/end/goal events + saved fitted shot snapshot',
            'same_second_goal_warning': any(sum(1 for e in events if e['period']['value'] == p and clock(e) == c and e.get('isShot')) > 1 for p, c in goal_seconds),
            'method': 'Clock exposure includes added time, excludes halftime; not ball-in-play minutes. Goals are assigned to the score before the event. Same-second events retain source order. Windows are elapsed match time with first-half added time retained. Rates use selected-state clock exposure; short slices are noisy. Fitted xG is retrospective, not frozen pre-match evidence.'}
