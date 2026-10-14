"""Monte Carlo league-table simulator for versioned match predictions.

The simulator is deliberately independent of Supabase and the training pipeline. It
accepts a frozen standings snapshot plus remaining fixtures whose score distribution
comes from a model version, then returns an auditable distribution of final tables.

Input fixture example (Poisson score model):
    {"home_team": "Arsenal", "away_team": "Chelsea",
     "expected_home_goals": 1.8, "expected_away_goals": 1.1}

An explicit score distribution can be supplied instead:
    {"home_team": "Arsenal", "away_team": "Chelsea",
     "score_probabilities": [
       {"home_goals": 1, "away_goals": 0, "probability": 0.2}, ...]}

Spain and Italy use completed plus simulated head-to-head results for regular table
ordering. Serie A's tied-points title and 17th/18th playoffs use a disclosed neutral
50/50 prior until a separately validated hypothetical-match model is available.
"""

from __future__ import annotations

import argparse
import bisect
import copy
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from score_probabilities import score_matrix


STANDARD_FIELDS = ("played", "wins", "draws", "losses", "goals_for", "goals_against", "points")
LEAGUE_RULES = {
    "ENG-Premier League": ("points", "goal_difference", "goals_for"),
    "GER-Bundesliga": ("points", "goal_difference", "goals_for"),
    "FRA-Ligue 1": ("points", "goal_difference", "goals_for"),
    "ESP-La Liga": ("points", "goal_difference", "goals_for"),
    "ITA-Serie A": ("points", "goal_difference", "goals_for"),
}
HEAD_TO_HEAD_LEAGUES = {"ESP-La Liga", "ITA-Serie A"}


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def validate_standings(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if len(rows) < 2:
        raise ValueError("standings must contain at least two teams")
    table: dict[str, dict[str, Any]] = {}
    for raw in rows:
        team = str(raw.get("team", "")).strip()
        if not team or team in table:
            raise ValueError("every standings row must have a unique non-empty team")
        row = {"team": team}
        for field in STANDARD_FIELDS:
            row[field] = _nonnegative_int(raw.get(field, 0), f"{team}.{field}")
        if row["played"] != row["wins"] + row["draws"] + row["losses"]:
            raise ValueError(f"{team}: played must equal wins + draws + losses")
        if row["points"] != 3 * row["wins"] + row["draws"]:
            raise ValueError(f"{team}: points must equal 3*wins + draws")
        row["goal_difference"] = row["goals_for"] - row["goals_against"]
        table[team] = row
    return table


def _score_distribution(fixture: dict[str, Any], max_goals: int) -> list[tuple[int, int, float]]:
    explicit = fixture.get("score_probabilities")
    if explicit is not None:
        if not isinstance(explicit, list) or not explicit:
            raise ValueError("score_probabilities must be a non-empty list")
        scores: list[tuple[int, int, float]] = []
        for item in explicit:
            home = _nonnegative_int(item.get("home_goals"), "home_goals")
            away = _nonnegative_int(item.get("away_goals"), "away_goals")
            probability = float(item.get("probability", -1))
            if not math.isfinite(probability) or probability < 0:
                raise ValueError("score probabilities must be finite and non-negative")
            scores.append((home, away, probability))
        total = sum(item[2] for item in scores)
        if total <= 0 or abs(total - 1.0) > 1e-6:
            raise ValueError("score probabilities must sum to 1")
        return _align_result_probabilities(scores, fixture)

    if "expected_home_goals" not in fixture or "expected_away_goals" not in fixture:
        raise ValueError("fixture needs expected goals or an explicit score distribution")
    matrix = score_matrix(float(fixture["expected_home_goals"]),
                          float(fixture["expected_away_goals"]), max_goals)
    scores = [
        (home, away, float(matrix[home, away]))
        for home in range(len(matrix)) for away in range(len(matrix))
    ]
    return _align_result_probabilities(scores, fixture)


def _align_result_probabilities(
    scores: list[tuple[int, int, float]], fixture: dict[str, Any]
) -> list[tuple[int, int, float]]:
    """Reweight scorelines so their H/D/A mass equals the published forecast.

    Relative probabilities within home-win, draw, and away-win scorelines remain
    unchanged. Fixtures without result probabilities keep their original score
    model for backwards compatibility.
    """
    keys = ("home_win_probability", "draw_probability", "away_win_probability")
    supplied = [key in fixture for key in keys]
    if not any(supplied):
        return scores
    if not all(supplied):
        raise ValueError("fixture must provide all three result probabilities")
    target = [float(fixture[key]) for key in keys]
    if any(not math.isfinite(value) or value < 0 for value in target):
        raise ValueError("result probabilities must be finite and non-negative")
    target_total = sum(target)
    if target_total <= 0 or abs(target_total - 1.0) > 1e-5:
        raise ValueError("result probabilities must sum to 1")
    target = [value / target_total for value in target]

    def outcome(home: int, away: int) -> int:
        return 0 if home > away else 1 if home == away else 2

    source = [0.0, 0.0, 0.0]
    for home, away, probability in scores:
        source[outcome(home, away)] += probability
    if any(wanted > 0 and available <= 0 for wanted, available in zip(target, source)):
        raise ValueError("score distribution has no support for a requested result")
    aligned = [
        (home, away, probability * target[outcome(home, away)] / source[outcome(home, away)])
        if source[outcome(home, away)] > 0 else (home, away, 0.0)
        for home, away, probability in scores
    ]
    total = sum(item[2] for item in aligned)
    return [(home, away, probability / total) for home, away, probability in aligned]


def prepare_fixtures(
    fixtures: list[dict[str, Any]], teams: set[str], max_goals: int = 10
) -> list[dict[str, Any]]:
    if max_goals < 1:
        raise ValueError("max_goals must be at least 1")
    prepared = []
    for fixture in fixtures:
        home = str(fixture.get("home_team", "")).strip()
        away = str(fixture.get("away_team", "")).strip()
        if home == away or home not in teams or away not in teams:
            raise ValueError(f"invalid fixture: {home!r} vs {away!r}")
        distribution = _score_distribution(fixture, max_goals)
        cumulative: list[float] = []
        running = 0.0
        for _, _, probability in distribution:
            running += probability
            cumulative.append(running)
        cumulative[-1] = 1.0
        prepared.append(
            {
                "home_team": home,
                "away_team": away,
                "scores": [(h, a) for h, a, _ in distribution],
                "cumulative": cumulative,
                "outcome_scores": {
                    outcome: [(h, a) for h, a, probability in distribution
                              if (0 if h > a else 1 if h == a else 2) == outcome]
                    for outcome in range(3)
                },
                "outcome_cumulative": {
                    outcome: _conditional_cumulative([
                        probability for h, a, probability in distribution
                        if (0 if h > a else 1 if h == a else 2) == outcome
                    ])
                    for outcome in range(3)
                },
                "result_probabilities": [
                    sum(probability for h, a, probability in distribution
                        if (0 if h > a else 1 if h == a else 2) == outcome)
                    for outcome in range(3)
                ],
            }
        )
    return prepared


def _conditional_cumulative(probabilities: list[float]) -> list[float]:
    total = sum(probabilities)
    if total <= 0:
        return []
    cumulative: list[float] = []
    running = 0.0
    for probability in probabilities:
        running += probability / total
        cumulative.append(running)
    cumulative[-1] = 1.0
    return cumulative


def _sample_with_strength_uncertainty(
    fixture: dict[str, Any], team_shocks: dict[str, float], rng: random.Random
) -> tuple[int, int]:
    """Sample a score after one persistent team-strength shock per season draw."""
    delta = team_shocks[fixture["home_team"]] - team_shocks[fixture["away_team"]]
    base = fixture["result_probabilities"]
    weights = [base[0] * math.exp(delta), base[1], base[2] * math.exp(-delta)]
    total = sum(weights)
    probabilities = [weight / total for weight in weights]
    draw = rng.random()
    outcome = 0 if draw < probabilities[0] else 1 if draw < probabilities[0] + probabilities[1] else 2
    conditional = fixture["outcome_cumulative"][outcome]
    index = bisect.bisect_left(conditional, rng.random())
    return fixture["outcome_scores"][outcome][index]


def apply_result(table: dict[str, dict[str, Any]], home: str, away: str, home_goals: int, away_goals: int) -> None:
    home_row, away_row = table[home], table[away]
    home_row["played"] += 1
    away_row["played"] += 1
    home_row["goals_for"] += home_goals
    home_row["goals_against"] += away_goals
    away_row["goals_for"] += away_goals
    away_row["goals_against"] += home_goals
    if home_goals > away_goals:
        home_row["wins"] += 1
        away_row["losses"] += 1
        home_row["points"] += 3
    elif home_goals < away_goals:
        away_row["wins"] += 1
        home_row["losses"] += 1
        away_row["points"] += 3
    else:
        home_row["draws"] += 1
        away_row["draws"] += 1
        home_row["points"] += 1
        away_row["points"] += 1
    home_row["goal_difference"] = home_row["goals_for"] - home_row["goals_against"]
    away_row["goal_difference"] = away_row["goals_for"] - away_row["goals_against"]


def ranked_table(table: dict[str, dict[str, Any]], ranking_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in ranking_keys:
        if key not in STANDARD_FIELDS and key != "goal_difference":
            raise ValueError(f"unsupported ranking key: {key}")
    return sorted(
        table.values(),
        key=lambda row: tuple([-row[key] for key in ranking_keys] + [row["team"]]),
    )


def ranked_head_to_head(table: dict[str, dict[str, Any]], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank equal-points groups by H2H points/GD, then overall GD/GF."""
    by_points: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in table.values():
        by_points[row["points"]].append(row)
    ranked: list[dict[str, Any]] = []
    for points in sorted(by_points, reverse=True):
        tied = by_points[points]
        if len(tied) == 1:
            ranked.extend(tied)
            continue
        names = {row["team"] for row in tied}
        mini = {team: {"points": 0, "goal_difference": 0} for team in names}
        for result in results:
            home, away = result["home_team"], result["away_team"]
            if home not in names or away not in names:
                continue
            hg, ag = int(result["home_goals"]), int(result["away_goals"])
            mini[home]["goal_difference"] += hg - ag
            mini[away]["goal_difference"] += ag - hg
            if hg > ag:
                mini[home]["points"] += 3
            elif ag > hg:
                mini[away]["points"] += 3
            else:
                mini[home]["points"] += 1
                mini[away]["points"] += 1
        ranked.extend(sorted(tied, key=lambda row: (
            -mini[row["team"]]["points"],
            -mini[row["team"]]["goal_difference"],
            -row["goal_difference"],
            -row["goals_for"],
            row["team"],
        )))
    return ranked


def apply_serie_a_playoffs(
    ordered: list[dict[str, Any]], rng: random.Random
) -> dict[str, bool]:
    """Resolve the two Serie A special boundaries after regular-table ordering.

    The regular tiebreak mini-table identifies the two clubs at each boundary when
    more than two clubs share the same points. The playoff itself is treated as a
    neutral coin flip. This is intentionally less precise than reusing home/away
    league expected goals for a hypothetical neutral-site match.
    """
    applied = {"title": False, "relegation_17_18": False}
    if len(ordered) >= 2 and ordered[0]["points"] == ordered[1]["points"]:
        applied["title"] = True
        if rng.random() < 0.5:
            ordered[0], ordered[1] = ordered[1], ordered[0]
    if len(ordered) >= 18 and ordered[16]["points"] == ordered[17]["points"]:
        applied["relegation_17_18"] = True
        if rng.random() < 0.5:
            ordered[16], ordered[17] = ordered[17], ordered[16]
    return applied


def simulate_league(
    standings: list[dict[str, Any]],
    fixtures: list[dict[str, Any]],
    simulations: int = 10_000,
    seed: int = 2026,
    ranking_keys: tuple[str, ...] = ("points", "goal_difference", "goals_for"),
    max_goals: int = 10,
    completed_results: list[dict[str, Any]] | None = None,
    head_to_head: bool = False,
    serie_a_playoffs: bool = False,
    team_strength_uncertainty_sd: float = 0.0,
) -> dict[str, Any]:
    if simulations < 1:
        raise ValueError("simulations must be at least 1")
    if not math.isfinite(team_strength_uncertainty_sd) or team_strength_uncertainty_sd < 0:
        raise ValueError("team_strength_uncertainty_sd must be finite and non-negative")
    initial = validate_standings(standings)
    prepared = prepare_fixtures(fixtures, set(initial), max_goals=max_goals)
    remaining_by_team: Counter[str] = Counter()
    for fixture in prepared:
        remaining_by_team[fixture["home_team"]] += 1
        remaining_by_team[fixture["away_team"]] += 1
    rng = random.Random(seed)
    positions: dict[str, Counter[int]] = defaultdict(Counter)
    points: dict[str, list[int]] = defaultdict(list)
    playoff_counts = Counter()

    for _ in range(simulations):
        table = copy.deepcopy(initial)
        results = list(completed_results or [])
        team_shocks = {
            team: rng.gauss(0.0, team_strength_uncertainty_sd) for team in initial
        }
        for fixture in prepared:
            if team_strength_uncertainty_sd:
                home_goals, away_goals = _sample_with_strength_uncertainty(
                    fixture, team_shocks, rng
                )
            else:
                index = bisect.bisect_left(fixture["cumulative"], rng.random())
                home_goals, away_goals = fixture["scores"][index]
            apply_result(table, fixture["home_team"], fixture["away_team"], home_goals, away_goals)
            results.append({
                "home_team": fixture["home_team"], "away_team": fixture["away_team"],
                "home_goals": home_goals, "away_goals": away_goals,
            })
        ordered = ranked_head_to_head(table, results) if head_to_head else ranked_table(table, ranking_keys)
        if serie_a_playoffs:
            applied = apply_serie_a_playoffs(ordered, rng)
            playoff_counts.update(name for name, used in applied.items() if used)
        for position, row in enumerate(ordered, start=1):
            positions[row["team"]][position] += 1
            points[row["team"]].append(row["points"])

    team_count = len(initial)
    relegation_places = min(3, team_count)
    summary = []
    for team in initial:
        current_played = int(initial[team]["played"])
        current_points = int(initial[team]["points"])
        scheduled_matches = current_played + remaining_by_team[team]
        current_ppg = current_points / current_played if current_played else None
        current_pace = current_ppg * scheduled_matches if current_ppg is not None else None
        expected_final_points = sum(points[team]) / simulations
        position_probabilities = {
            str(position): positions[team][position] / simulations
            for position in range(1, team_count + 1)
        }
        summary.append(
            {
                "team": team,
                "current_played": current_played,
                "current_points": current_points,
                "current_points_per_match": current_ppg,
                "current_points_pace": current_pace,
                "projected_remaining_points": expected_final_points - current_points,
                "expected_position": sum(p * probability for p, probability in ((int(k), v) for k, v in position_probabilities.items())),
                "expected_points": expected_final_points,
                "champion_probability": position_probabilities["1"],
                "top_four_probability": sum(position_probabilities[str(p)] for p in range(1, min(4, team_count) + 1)),
                "relegation_probability": sum(
                    position_probabilities[str(p)]
                    for p in range(team_count - relegation_places + 1, team_count + 1)
                ),
                "position_probabilities": position_probabilities,
            }
        )
    summary.sort(key=lambda row: (row["expected_position"], -row["expected_points"], row["team"]))
    return {
        "simulations": simulations,
        "seed": seed,
        "team_strength_uncertainty_sd": team_strength_uncertainty_sd,
        "uncertainty_policy": (
            "persistent_team_logit_shock_per_simulated_season"
            if team_strength_uncertainty_sd else "published_fixture_probabilities_only"
        ),
        "remaining_fixtures": len(fixtures),
        "ranking_keys": list(ranking_keys),
        "ranking_method": "head_to_head_mini_table" if head_to_head else "overall_table_keys",
        "special_playoff_modelled": serie_a_playoffs,
        "special_playoff_policy": (
            "neutral_50_50_prior_after_regular_head_to_head_ordering"
            if serie_a_playoffs else None
        ),
        "special_playoff_frequency": {
            name: playoff_counts[name] / simulations
            for name in ("title", "relegation_17_18")
        } if serie_a_playoffs else {},
        "teams": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON containing standings and fixtures")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--simulations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--max-goals", type=int, default=10)
    parser.add_argument("--team-strength-uncertainty-sd", type=float, default=0.0)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    league = payload.get("league")
    ranking_keys = tuple(payload.get("ranking_keys") or LEAGUE_RULES.get(league, LEAGUE_RULES["ENG-Premier League"]))
    result = simulate_league(
        payload["standings"],
        payload["fixtures"],
        simulations=args.simulations,
        seed=args.seed,
        ranking_keys=ranking_keys,
        max_goals=args.max_goals,
        completed_results=payload.get("completed_results", []),
        head_to_head=league in HEAD_TO_HEAD_LEAGUES,
        serie_a_playoffs=league == "ITA-Serie A",
        team_strength_uncertainty_sd=args.team_strength_uncertainty_sd,
    )
    result["league"] = league
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
