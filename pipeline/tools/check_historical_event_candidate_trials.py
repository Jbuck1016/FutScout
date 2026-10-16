"""Offline checks for the private historical event-candidate experiment."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evaluate_historical_event_candidates as trial


def main() -> None:
    rows = []
    for game_id, day, passes in (("one", "2024-01-01", 2),
                                 ("two", "2024-01-01", 100),
                                 ("three", "2024-01-02", 6)):
        row = {field: 1.0 for field in trial.ROLLING_FIELDS}
        row.update({"game_id": game_id, "team": "Test FC",
                    "match_date": pd.Timestamp(day),
                    "completed_progressive_passes": float(passes),
                    "non_penalty_shots": 2.0,
                    "non_penalty_box_shots": 1.0,
                    "non_penalty_big_chances": 0.0,
                    "npxg_for": 0.2,
                    "non_penalty_mean_shot_distance_m": 15.0})
        rows.append(row)
    features = trial.rolling_features(pd.DataFrame(rows), windows=(5,))
    assert features[("one", "Test FC")] == {}
    assert features[("two", "Test FC")] == {}
    assert features[("three", "Test FC")]["completed_progressive_passes_5"] == 51.0
    assert abs(features[("three", "Test FC")]["npxg_per_shot_5"] - 0.1) < 1e-12
    print("Historical event trial point-in-time checks passed")


if __name__ == "__main__":
    main()
