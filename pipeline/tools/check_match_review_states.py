"""Offline chronology/exposure regression checks, no database calls."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from match_review_states import build_states

def event(i, p, minute, kind, team=1, **kw):
    return dict(id=i, period={'value': p}, minute=minute, second=0,
                type={'displayName': kind}, teamId=team, **kw)

raw = {'home': {'teamId': 1, 'name': 'Home'}, 'away': {'teamId': 2, 'name': 'Away'}, 'ftScore': '1 : 1',
       'events': [event(1, 1, 30, 'Goal', isShot=True), event(2, 1, 47, 'End'),
                  event(3, 2, 46, 'Goal', isOwnGoal=True), event(4, 2, 95, 'End')]}
shots = [dict(period=1, minute=30, second=0, team='Home', xg=.2)]
r = build_states(raw, shots)
row = lambda w, s: next(x for x in r['rows'] if x['window'] == w and x['state'] == s)
assert r['duration_seconds'] == 97 * 60
assert row('full', 'home_leading')['seconds'] == 18 * 60
assert row('full', 'level')['seconds'] == 79 * 60
assert row('full', 'level')['teams'][0]['shots'] == 1, 'Goal shot belongs to pre-goal state'
assert row('full', 'away_leading')['teams'][0]['shots_per90'] is None
assert row('first', 'all')['seconds'] == 47 * 60
assert row('second', 'all')['seconds'] == 50 * 60
assert row('early', 'all')['teams'][0]['shots'] == 0, 'Half-open window boundary'
raw['events'].reverse()
assert build_states(raw, shots)['rows'] == r['rows'], 'Period/time chronology independent of input sort'
raw['ftScore'] = '2 : 0'
try:
    build_states(raw, shots)
    raise AssertionError('Invalid score accepted')
except ValueError:
    pass
raw['ftScore'] = '1 : 1'
raw['events'] = [e for e in raw['events'] if e['id'] != 4]
try:
    build_states(raw, shots)
    raise AssertionError('Missing period end accepted')
except ValueError:
    pass
print('PASS: added time, period ordering, own goal, pre-goal state, zero exposure, window boundaries, score/end fail-closed')
