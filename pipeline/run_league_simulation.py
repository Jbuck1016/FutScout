#!/usr/bin/env python3
"""Build a league-table simulation from one frozen prediction version.

Dry-run is the default. ``--execute`` writes one versioned run plus team rows,
and is allowed only for validated, shadow, or active model runs.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import train_match_baselines as baseline
from simulate_league_table import HEAD_TO_HEAD_LEAGUES, LEAGUE_RULES, simulate_league


RULES_VERSION = 4
EXPECTED_2627_FIXTURES = {
    "ENG-Premier League": 380,
    "ESP-La Liga": 380,
    "ITA-Serie A": 380,
    "GER-Bundesliga": 306,
    "FRA-Ligue 1": 306,
}


def validate_schedule_identity(matches: list[dict[str, Any]], league: str, season: str) -> None:
    """Reject phantom fixtures before they can inflate expected points or positions."""
    directed_pairs = [(str(row["home_team"]), str(row["away_team"])) for row in matches]
    if len(set(directed_pairs)) != len(directed_pairs):
        raise RuntimeError(f"{league} {season} contains a duplicate home/away fixture")
    expected = EXPECTED_2627_FIXTURES.get(league) if season == "2627" else None
    if expected is not None and len(matches) != expected:
        raise RuntimeError(f"{league} {season} has {len(matches)} fixtures; expected {expected}")


def parse_instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--as-of must include a timezone")
    return parsed.astimezone(UTC)


def match_instant(row: dict[str, Any]) -> datetime:
    value = row.get("kickoff_at") or f"{row['date']}T12:00:00+00:00"
    return parse_instant(value)


def build_snapshot(matches: list[dict[str, Any]], predictions: list[dict[str, Any]], as_of: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    standings, fixtures, _ = build_snapshot_with_results(matches, predictions, as_of)
    return standings, fixtures


def build_snapshot_with_results(matches: list[dict[str, Any]], predictions: list[dict[str, Any]], as_of: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    teams = sorted({row["home_team"] for row in matches} | {row["away_team"] for row in matches})
    table = {
        team: {"team": team, "played": 0, "wins": 0, "draws": 0, "losses": 0, "goals_for": 0, "goals_against": 0, "points": 0}
        for team in teams
    }
    future: list[dict[str, Any]] = []
    completed_results: list[dict[str, Any]] = []
    for row in sorted(matches, key=lambda item: (match_instant(item), str(item["game_id"]))):
        before_cutoff = match_instant(row) <= as_of
        scored = row.get("home_score") is not None and row.get("away_score") is not None
        if before_cutoff:
            if not scored:
                raise RuntimeError(f"fixture {row['game_id']} is before as_of but has no final score")
            home, away = table[row["home_team"]], table[row["away_team"]]
            hg, ag = int(row["home_score"]), int(row["away_score"])
            completed_results.append({
                "home_team": row["home_team"], "away_team": row["away_team"],
                "home_goals": hg, "away_goals": ag,
            })
            home["played"] += 1; away["played"] += 1
            home["goals_for"] += hg; home["goals_against"] += ag
            away["goals_for"] += ag; away["goals_against"] += hg
            if hg > ag:
                home["wins"] += 1; away["losses"] += 1; home["points"] += 3
            elif hg < ag:
                away["wins"] += 1; home["losses"] += 1; away["points"] += 3
            else:
                home["draws"] += 1; away["draws"] += 1; home["points"] += 1; away["points"] += 1
        else:
            future.append(row)

    prediction_by_game = {str(row["game_id"]): row for row in predictions}
    missing = [str(row["game_id"]) for row in future if str(row["game_id"]) not in prediction_by_game]
    extras = sorted(set(prediction_by_game) - {str(row["game_id"]) for row in future})
    if missing or extras:
        raise RuntimeError(f"prediction/fixture mismatch: missing={len(missing)} extras={len(extras)}")
    fixtures = []
    for row in future:
        prediction = prediction_by_game[str(row["game_id"])]
        fixture = {
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "expected_home_goals": float(prediction["home_expected_goals"]),
            "expected_away_goals": float(prediction["away_expected_goals"]),
            "home_win_probability": float(prediction["home_win_probability"]),
            "draw_probability": float(prediction["draw_probability"]),
            "away_win_probability": float(prediction["away_win_probability"]),
        }
        explicit = prediction.get("scoreline_distribution")
        if explicit:
            fixture["score_probabilities"] = [
                {
                    "home_goals": int(score.split("-", 1)[0]),
                    "away_goals": int(score.split("-", 1)[1]),
                    "probability": float(probability),
                }
                for score, probability in explicit.items()
            ]
        fixtures.append(fixture)
    return list(table.values()), fixtures, completed_results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-run-id", type=int)
    parser.add_argument("--predictions-file", type=Path)
    parser.add_argument("--league", choices=tuple(LEAGUE_RULES), required=True)
    parser.add_argument("--season", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--forecast-kind", choices=("thursday_frozen", "latest", "confirmed_lineup"), default="thursday_frozen")
    parser.add_argument("--simulations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--team-strength-uncertainty-sd", type=float, default=0.0,
                        help="persistent per-team uncertainty applied within each simulated season")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.execute and args.model_run_id is None:
        raise ValueError("--execute requires --model-run-id")
    if args.predictions_file is None and args.model_run_id is None:
        raise ValueError("provide --predictions-file for a dry run or --model-run-id")
    as_of = parse_instant(args.as_of)
    db = baseline.db_client()
    model = {"model_version": "local-review", "status": "training"}
    if args.model_run_id is not None:
        model_rows = db.table("ml_model_runs").select("id,status,model_key,model_version").eq("id", args.model_run_id).execute().data or []
        if len(model_rows) != 1:
            raise RuntimeError("model run not found")
        model = model_rows[0]
        if args.execute and model["status"] not in {"validated", "shadow", "active"}:
            raise RuntimeError(f"cannot persist a simulation for model status {model['status']!r}")

    matches = baseline.fetch_pages(
        db.table("matches")
        .select("game_id,date,kickoff_at,home_team,away_team,home_score,away_score")
        .eq("season", args.season).eq("league", args.league)
        .eq("is_live_scope", True).order("date").order("game_id")
    )
    validate_schedule_identity(matches, args.league, args.season)
    if args.predictions_file is not None:
        payload = json.loads(args.predictions_file.read_text(encoding="utf-8"))
        if payload.get("season") != args.season or payload.get("forecast_kind") != args.forecast_kind:
            raise RuntimeError("prediction file season or forecast kind does not match simulation arguments")
        if parse_instant(str(payload.get("as_of"))) != as_of:
            raise RuntimeError("prediction file as_of does not match simulation arguments")
        predictions = [
            row for row in payload.get("predictions", []) if row.get("league") == args.league
        ]
        model["model_version"] = Path(str(payload.get("artifact") or "local-review")).stem
        prediction_ids = {str(row["game_id"]) for row in predictions}
        matches = [
            row for row in matches
            if match_instant(row) <= as_of or str(row["game_id"]) in prediction_ids
        ]
    else:
        # The saved grid is the forecast's own score distribution; rebuilding
        # it from the stored four-decimal rates would simulate a different model.
        predictions = baseline.fetch_pages(
            db.table("ml_match_predictions")
            .select(
                "game_id,home_expected_goals,away_expected_goals,home_win_probability,"
                "draw_probability,away_win_probability,scoreline_distribution"
            )
            .eq("model_run_id", args.model_run_id).eq("forecast_kind", args.forecast_kind).eq("as_of", as_of.isoformat())
            .order("game_id")
        )
    standings, fixtures, completed_results = build_snapshot_with_results(matches, predictions, as_of)
    result = simulate_league(
        standings, fixtures, simulations=args.simulations, seed=args.seed,
        ranking_keys=LEAGUE_RULES[args.league],
        completed_results=completed_results,
        head_to_head=args.league in HEAD_TO_HEAD_LEAGUES,
        serie_a_playoffs=args.league == "ITA-Serie A",
        team_strength_uncertainty_sd=args.team_strength_uncertainty_sd,
    )
    result.update({
        "league": args.league, "season": args.season, "as_of": as_of.isoformat(),
        "model_run_id": args.model_run_id, "model_version": model["model_version"],
        "forecast_kind": args.forecast_kind, "rules_version": RULES_VERSION,
        "team_strength_uncertainty_sd": args.team_strength_uncertainty_sd,
        "europe_probability_definition": "top-four finish proxy; exact UEFA/cup reallocation is outside rules version 4",
        "special_playoff_modelled": args.league == "ITA-Serie A",
        "rules_note": (
            "Serie A uses head-to-head regular ordering; tied-points title and 17th/18th playoffs use a disclosed neutral 50/50 prior."
            if args.league == "ITA-Serie A" else None
        ),
    })
    output = args.output or Path(__file__).resolve().parents[1] / "artifacts" / "simulations" / f"{args.league}_{args.season}_{args.forecast_kind}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Simulation dry-run built: teams={len(standings)} fixtures={len(fixtures)} output={output}")
    if not args.execute:
        print("No Supabase rows written; add --execute only after reviewing the artifact")
        return 0

    run_row = {
        "model_run_id": args.model_run_id, "league": args.league, "season": args.season,
        "as_of": as_of.isoformat(), "source_forecast_kind": args.forecast_kind,
        "simulation_count": args.simulations, "rules_version": RULES_VERSION, "status": "running",
    }
    created = db.table("ml_season_simulation_runs").upsert(
        run_row,
        on_conflict="model_run_id,league,season,as_of,source_forecast_kind",
    ).execute().data or []
    if len(created) != 1:
        raise RuntimeError("simulation run insert did not return one row")
    run_id = created[0]["id"]
    try:
        rows = [
            {
                "simulation_run_id": run_id,
                "team": team["team"],
                "expected_points": team["expected_points"],
                "expected_position": team["expected_position"],
                "finish_distribution": team["position_probabilities"],
                "title_probability": team["champion_probability"],
                "europe_probability": team["top_four_probability"],
                "relegation_probability": team["relegation_probability"],
            }
            for team in result["teams"]
        ]
        db.table("ml_season_simulation_teams").upsert(
            rows, on_conflict="simulation_run_id,team"
        ).execute()
        db.table("ml_season_simulation_runs").update({"status": "complete"}).eq("id", run_id).execute()
    except Exception:
        db.table("ml_season_simulation_runs").update({"status": "failed"}).eq("id", run_id).execute()
        raise
    print(f"Persisted simulation run id={run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
