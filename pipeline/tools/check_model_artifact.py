"""Synthetic checks for packaging, point-in-time fixtures, and prediction output."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))

import model_artifact  # noqa: E402
import generate_match_predictions as generation  # noqa: E402


def training_frame() -> pd.DataFrame:
    rows = []
    for index in range(36):
        rows.append({
            "game_id": str(index), "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=index),
            "league": "ENG-Premier League", "season": "test",
            "home_team": "A" if index % 2 == 0 else "B", "away_team": "B" if index % 2 == 0 else "A",
            "home_goals": index % 4, "away_goals": (index + 1) % 3,
            "result": "H" if index % 4 > (index + 1) % 3 else "D" if index % 4 == (index + 1) % 3 else "A",
            "source_match_count": index * 2,
            "context.team_prior_matches": index, "context.opponent_prior_matches": index,
            "context.team_rest_days": 7, "context.opponent_rest_days": 7,
            "elo_home": 1500 + index, "elo_away": 1500 - index, "elo_diff": 55 + 2 * index,
            **{f"{side}.{metric}_{window}": float((index + window) % 12 + 1)
               for side in ("team", "opponent") for metric in ("shots", "shots_against")
               for window in (3, 5, 10)},
            **{f"{side}.{metric}_{window}": float((index + window) % 20 + 1)
               for side in ("team", "opponent")
               for metric in ("field_tilt_pct", "box_entries_pass")
               for window in (3, 5, 10)},
            "team.xt_difference_3": float(index % 5),
            "opponent.xt_difference_3": float(-(index % 5)),
            "context.team_matches_last_14_days": 2,
            "context.opponent_matches_last_14_days": 2,
        })
    return pd.DataFrame(rows)


def main() -> None:
    generator_source = (PIPELINE / "generate_match_predictions.py").read_text(encoding="utf-8")
    assert '.eq("observation_schema_version", int(artifact["feature_schema_version"]))' in generator_source
    artifact = model_artifact.train_compact_poisson(training_frame(), 1)
    assert "source_match_count" not in artifact["numeric_columns"]
    assert not any("prior_matches" in column for column in artifact["numeric_columns"])
    normalized = model_artifact.multiseason.normalize_model_features(pd.DataFrame([
        {"context.team_rest_days": 90, "context.opponent_rest_days": -2}
    ]))
    assert normalized.iloc[0]["context.team_rest_days"] == 30
    assert normalized.iloc[0]["context.opponent_rest_days"] == 0
    observations = [
        {"game_id": "h1", "team": team, "league": "ENG-Premier League", "match_date": "2025-08-01",
         "shots": 10 if team == "A" else 7, "shots_against": 7 if team == "A" else 10,
         "field_tilt_pct": 62 if team == "A" else 38,
         "box_entries_pass": 12 if team == "A" else 6,
         "xt_difference": 1.2 if team == "A" else -1.2}
        for team in ("A", "B")
    ]
    matches = [{"game_id": "h1", "date": "2025-08-01", "home_team": "A", "away_team": "B",
                "home_score": 2, "away_score": 0}]
    fixtures = [{"game_id": "f1", "date": "2025-08-08", "kickoff_at": "2025-08-08T19:00:00+00:00",
                 "league": "ENG-Premier League", "home_team": "A", "away_team": "B"}]
    rows = model_artifact.predict_rows(artifact, fixtures, observations, matches)
    assert len(rows) == 1
    prediction = rows[0]
    total = prediction["home_win_probability"] + prediction["draw_probability"] + prediction["away_win_probability"]
    assert abs(total - 1.0) < 1e-6
    assert prediction["home_expected_goals"] > 0 and prediction["away_expected_goals"] > 0
    assert abs(sum(prediction["scoreline_distribution"].values()) - 1.0) < 1e-9
    rich_columns = artifact["numeric_columns"] + [
        f"{side}.{metric}_{window}"
        for side in ("team", "opponent")
        for metric in ("field_tilt_pct", "box_entries_pass")
        for window in (3, 5, 10)
    ]
    rich_artifact = model_artifact.train_poisson(
        training_frame(), 1, rich_columns, "compact_territory_poisson"
    )
    rich_prediction = model_artifact.predict_rows(rich_artifact, fixtures, observations, matches)[0]
    ledger = rich_prediction['explanation']['feature_ledger']
    assert any(item['feature'].endswith('_10') for item in ledger)
    for driver in rich_prediction['explanation']['drivers']:
        effects = [item['log_rate_balance_contribution'] for item in ledger if item['family'] == driver['label']]
        assert abs(sum(effects) - driver['goal_balance_effect']) <= 0.000051
    assert 'log goal rate' in rich_prediction['explanation']['contribution_units']
    assert any(
        driver["label"] in {"Field tilt", "Box entries"}
        for driver in rich_prediction["explanation"]["drivers"]
    ), "rich territory inputs were not available to prediction explanations"
    assert all(
        "combines the model's standardized 3-, 5-, and 10-match inputs" in driver["detail"]
        for driver in rich_prediction["explanation"]["drivers"]
        if driver["label"] in {"Field tilt", "Box entries", "Shot volume", "Shots allowed"}
    ), "rolling contribution explanations must not imply that last-three context is the full calculation"
    v2_artifact = model_artifact.train_poisson(
        training_frame(), 2,
        [
            "elo_diff", "team.xt_difference_3", "opponent.xt_difference_3",
            "context.team_matches_last_14_days",
            "context.opponent_matches_last_14_days",
        ],
        "v2_contract_test_poisson",
    )
    v2_prediction = model_artifact.predict_rows(v2_artifact, fixtures, observations, matches)[0]
    assert v2_prediction["home_expected_goals"] > 0
    v2_row = model_artifact.fixture_row(
        fixtures[0], observations, matches, feature_schema_version=2
    )
    assert v2_row["team.xt_difference_3"] == 1.2
    assert v2_row["opponent.xt_difference_3"] == -1.2
    slate = generation.persistence_horizon(
        [
            prediction | {"date": "2025-08-08T19:00:00+00:00"},
            prediction | {"game_id": "f2", "date": "2025-09-08T19:00:00+00:00"},
        ],
        generation.parse_instant("2025-08-07T12:00:00Z"),
        generation.parse_instant("2025-08-14T12:00:00Z"),
    )
    assert [row["game_id"] for row in slate] == ["f1"], "persistence leaked beyond the scoring horizon"
    later_observation = {
        "game_id": "h2", "team": "A", "league": "ENG-Premier League",
        "match_date": "2025-08-06", "shots": 40, "shots_against": 1,
    }
    later_match = {
        "game_id": "h2", "date": "2025-08-06", "kickoff_at": "2025-08-06T19:00:00+00:00",
        "home_team": "A", "away_team": "B", "home_score": 8, "away_score": 0,
    }
    cutoff = pd.Timestamp("2025-08-05T12:00:00+00:00")
    before = model_artifact.fixture_row(fixtures[0], observations, matches, prediction_as_of=cutoff)
    after_data_added = model_artifact.fixture_row(
        fixtures[0], observations + [later_observation], matches + [later_match], prediction_as_of=cutoff
    )
    assert before == after_data_added, "post-cutoff evidence changed a frozen prediction row"
    print("Model artifact and point-in-time prediction checks passed")


if __name__ == "__main__":
    main()
