#!/usr/bin/env python3
"""Checks earliest-freeze deduplication across weekly shadow snapshots."""
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))
from score_prediction_history import (  # noqa: E402
    combine_snapshots,
    complete_frozen_weekends,
    frozen_weekend_coverage,
)
import score_prediction_history as history  # noqa: E402


def payload(as_of: str, game_id: str, kickoff: str, probability: float,
            league: str = "ENG-Premier League") -> dict:
    return {
        "as_of": as_of, "evaluation_through": "2026-09-20T00:00:00+00:00",
        "predictions": [{"game_id": game_id, "date": kickoff, "league": league,
                         "home_win_probability": probability}],
    }


later = payload("2026-09-11T00:00:00+00:00", "g1", "2026-09-12T00:00:00+00:00", 0.7)
earlier = payload("2026-09-10T00:00:00+00:00", "g1", "2026-09-12T00:00:00+00:00", 0.6)
other = payload("2026-09-10T00:00:00+00:00", "g2", "2026-09-13T00:00:00+00:00", 0.5)
rows, repeats = combine_snapshots([later, other, earlier])
assert repeats == 1 and len(rows) == 2
assert next(row for row in rows if row["game_id"] == "g1")["home_win_probability"] == 0.6

complete = {
    "as_of": "2026-09-10T00:00:00+00:00",
    "evaluation_through": "2026-09-20T00:00:00+00:00",
    "predictions": [
        {"game_id": f"g{idx}", "date": "2026-09-12T00:00:00+00:00", "league": league}
        for idx, league in enumerate((
            "ENG-Premier League", "ESP-La Liga", "FRA-Ligue 1",
            "GER-Bundesliga", "ITA-Serie A",
        ))
    ],
}
completed_matches = [
    {
        "game_id": row["game_id"],
        "date": "2026-09-12",
        "kickoff_at": row["date"],
        "league": row["league"],
        "home_score": 1,
        "away_score": 0,
    }
    for row in complete["predictions"]
]
assert complete_frozen_weekends([complete], completed_matches) == 0, "unproven cutoff must not count"
with patch.object(history, "authentic_cutoff", return_value=True):
    assert complete_frozen_weekends([complete], completed_matches) == 1
assert complete_frozen_weekends([earlier], completed_matches) == 0

late_discovered = {
    "game_id": "late",
    "date": "2026-09-12",
    "kickoff_at": "2026-09-12T00:00:00+00:00",
    "league": "ENG-Premier League",
    "home_score": 2,
    "away_score": 1,
}
with patch.object(history, "authentic_cutoff", return_value=True):
    coverage = frozen_weekend_coverage([complete], completed_matches + [late_discovered])
assert coverage[0]["complete"] is False
assert coverage[0]["missing_completed_fixture_ids"] == ["late"]
print("Prediction history scoring checks passed")
