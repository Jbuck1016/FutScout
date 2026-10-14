"""Deterministic offline checks for simulate_league_table.py."""

from __future__ import annotations

import copy
import sys
from pathlib import Path


PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))

from simulate_league_table import _score_distribution, apply_result, ranked_head_to_head, ranked_table, simulate_league  # noqa: E402
from run_league_simulation import RULES_VERSION, validate_schedule_identity  # noqa: E402


def expect_error(callable_, phrase: str) -> None:
    try:
        callable_()
    except ValueError as exc:
        assert phrase in str(exc), (phrase, str(exc))
    else:
        raise AssertionError(f"expected ValueError containing {phrase!r}")


def main() -> None:
    assert RULES_VERSION == 4, "persisted simulation rules version must match review artifacts"
    # A duplicate directed pairing must not quietly become one more simulated
    # match, even when it has a different source game ID or kickoff date.
    duplicate = [
        {"game_id": "123", "home_team": "A", "away_team": "B"},
        {"game_id": "fd-456", "home_team": "A", "away_team": "B"},
    ]
    try:
        validate_schedule_identity(duplicate, "ESP-La Liga", "2627")
    except RuntimeError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate fixture was accepted by table simulator")
    try:
        validate_schedule_identity(duplicate[:1], "ESP-La Liga", "2627")
    except RuntimeError as exc:
        assert "expected 380" in str(exc)
    else:
        raise AssertionError("incomplete 2026/27 schedule was accepted")
    standings = [
        {"team": "A", "played": 1, "wins": 1, "draws": 0, "losses": 0, "goals_for": 2, "goals_against": 0, "points": 3},
        {"team": "B", "played": 1, "wins": 0, "draws": 0, "losses": 1, "goals_for": 0, "goals_against": 2, "points": 0},
    ]
    fixtures = [
        {
            "home_team": "B",
            "away_team": "A",
            "score_probabilities": [
                {"home_goals": 3, "away_goals": 0, "probability": 0.25},
                {"home_goals": 0, "away_goals": 0, "probability": 0.25},
                {"home_goals": 0, "away_goals": 1, "probability": 0.5},
            ],
        }
    ]
    original = copy.deepcopy(standings)
    first = simulate_league(standings, fixtures, simulations=2_000, seed=44)
    second = simulate_league(standings, fixtures, simulations=2_000, seed=44)
    assert first == second
    assert standings == original, "simulation mutated its input"
    pace_row = next(row for row in first["teams"] if row["team"] == "A")
    assert pace_row["current_points"] == 3
    assert pace_row["current_played"] == 1
    assert pace_row["current_points_pace"] == 6
    assert abs(pace_row["projected_remaining_points"] - (pace_row["expected_points"] - 3)) < 1e-9
    for team in first["teams"]:
        assert abs(sum(team["position_probabilities"].values()) - 1.0) < 1e-12
    a = next(team for team in first["teams"] if team["team"] == "A")
    assert 0.70 < a["champion_probability"] < 0.80
    uncertain_first = simulate_league(
        standings, fixtures, simulations=2_000, seed=44,
        team_strength_uncertainty_sd=0.15,
    )
    uncertain_second = simulate_league(
        standings, fixtures, simulations=2_000, seed=44,
        team_strength_uncertainty_sd=0.15,
    )
    assert uncertain_first == uncertain_second
    assert uncertain_first["uncertainty_policy"] == "persistent_team_logit_shock_per_simulated_season"
    assert uncertain_first["team_strength_uncertainty_sd"] == 0.15

    aligned = _score_distribution({
        "expected_home_goals": 1.7, "expected_away_goals": 0.9,
        "home_win_probability": 0.60, "draw_probability": 0.25,
        "away_win_probability": 0.15,
    }, 10)
    masses = [
        sum(probability for home, away, probability in aligned if home > away),
        sum(probability for home, away, probability in aligned if home == away),
        sum(probability for home, away, probability in aligned if home < away),
    ]
    assert all(abs(actual - wanted) < 1e-12 for actual, wanted in zip(masses, (0.60, 0.25, 0.15)))

    table = {row["team"]: copy.deepcopy(row) for row in standings}
    for row in table.values():
        row["goal_difference"] = row["goals_for"] - row["goals_against"]
    apply_result(table, "B", "A", 1, 1)
    assert table["A"]["points"] == 4 and table["B"]["points"] == 1
    assert ranked_table(table, ("points", "goal_difference", "goals_for"))[0]["team"] == "A"

    tied = {
        "A": {"team": "A", "points": 10, "goal_difference": 1, "goals_for": 8},
        "B": {"team": "B", "points": 10, "goal_difference": 5, "goals_for": 12},
    }
    h2h = [{"home_team": "A", "away_team": "B", "home_goals": 2, "away_goals": 0}]
    assert ranked_head_to_head(tied, h2h)[0]["team"] == "A", "overall GD incorrectly overrode H2H"

    tied_title = [
        {"team": "A", "played": 1, "wins": 0, "draws": 1, "losses": 0, "goals_for": 1, "goals_against": 1, "points": 1},
        {"team": "B", "played": 1, "wins": 0, "draws": 1, "losses": 0, "goals_for": 1, "goals_against": 1, "points": 1},
    ]
    serie_a = simulate_league(
        tied_title, [], simulations=2_000, seed=9,
        head_to_head=True, serie_a_playoffs=True,
    )
    assert serie_a["special_playoff_modelled"]
    assert serie_a["special_playoff_policy"] == "neutral_50_50_prior_after_regular_head_to_head_ordering"
    a_title = next(row for row in serie_a["teams"] if row["team"] == "A")["champion_probability"]
    assert 0.45 < a_title < 0.55, "tied title playoff should use the disclosed neutral prior"

    expect_error(
        lambda: simulate_league(standings, [{"home_team": "A", "away_team": "C", "expected_home_goals": 1, "expected_away_goals": 1}]),
        "invalid fixture",
    )
    expect_error(
        lambda: simulate_league(standings, [{"home_team": "A", "away_team": "B", "score_probabilities": [{"home_goals": 1, "away_goals": 0, "probability": 0.8}]}]),
        "sum to 1",
    )
    expect_error(
        lambda: simulate_league(standings, [{"home_team": "A", "away_team": "B", "expected_home_goals": 1, "expected_away_goals": 1, "home_win_probability": 0.5}]),
        "all three",
    )
    expect_error(lambda: simulate_league(standings, fixtures, team_strength_uncertainty_sd=-0.1), "non-negative")
    print("League-table simulator checks passed")


if __name__ == "__main__":
    main()
