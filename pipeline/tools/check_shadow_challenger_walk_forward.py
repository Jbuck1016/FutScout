"""Offline checks for the historical same-fixture comparison contract."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evaluate_shadow_challenger_walk_forward as evaluation  # noqa: E402


def main() -> None:
    rows = pd.DataFrame([
        {"game_id": "a", "date": "2024-01-01", "home_team": "A", "away_team": "B",
         "home_goals": 4, "away_goals": 0},
        {"game_id": "b", "date": "2024-01-01", "home_team": "A", "away_team": "C",
         "home_goals": 0, "away_goals": 2},
        {"game_id": "c", "date": "2024-01-02", "home_team": "A", "away_team": "D",
         "home_goals": 1, "away_goals": 1},
    ])
    rows["date"] = pd.to_datetime(rows["date"])
    rated = evaluation.date_batched_pre_match_elo(rows)
    assert rated.loc[0, "elo_home"] == rated.loc[1, "elo_home"] == 1500.0
    assert rated.loc[2, "elo_home"] != 1500.0
    assert list(rated["elo_diff"].notna()) == [True, True, True]
    available = evaluation.availability(
        pd.DataFrame({"elo_diff": [55.0, 60.0], "team.xt_difference_5": [None, 0.1]}),
        ["elo_diff", "team.xt_difference_5"],
    )
    assert available["fixtures_with_any_missing_input"] == 1
    assert available["missing_values_by_feature"] == {"team.xt_difference_5": 1}
    print("Historical challenger chronology and feature-availability checks passed")


if __name__ == "__main__":
    main()
