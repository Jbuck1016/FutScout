#!/usr/bin/env python3
"""Score eligible same-cutoff shadow candidates without changing their lifecycle."""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

import audit_frozen_tournament
import frozen_slate_contract as contract
import score_prediction_snapshot as snapshot_score
import train_match_baselines as baseline


MODELS = (
    "primary", "compact_control", "compact_xt_5", "box_sequences_5",
    "territory_elo_interactions",
)
PL_STRONG_HOME_FAVORITE_THRESHOLD = 0.55


def premier_home_favorite_monitor(chosen: dict, canonical: dict) -> dict:
    """Predeclared PL diagnostic on resolved, same-fixture frozen calls only."""
    fields = {"H": "home_win_probability", "D": "draw_probability", "A": "away_win_probability"}
    rows = []
    for game_id in sorted(set(chosen["primary"]) & set(chosen["compact_control"]) & set(canonical)):
        primary = chosen["primary"][game_id]
        control = chosen["compact_control"][game_id]
        if primary["league"] != "ENG-Premier League" or control["league"] != "ENG-Premier League":
            continue
        actual = canonical[game_id]
        hg, ag = int(actual["home_score"]), int(actual["away_score"])
        result = "H" if hg > ag else "D" if hg == ag else "A"
        home_probability = float(primary["home_win_probability"])
        strong_favorite = (
            home_probability >= PL_STRONG_HOME_FAVORITE_THRESHOLD
            and home_probability >= float(primary["draw_probability"])
            and home_probability >= float(primary["away_win_probability"])
        )
        field = fields[result]
        delta = -math.log(float(control[field])) + math.log(float(primary[field]))
        rows.append((result, strong_favorite, home_probability,
                     float(control["home_win_probability"]), delta))

    favorites = [row for row in rows if row[1]]
    away_upsets = [row for row in favorites if row[0] == "A"]
    return {
        "status": "scored" if rows else "awaiting_premier_league_results",
        "definition": (
            "Before kickoff, primary home-win probability is at least 0.55 "
            "and is its largest result probability; fixed before live scoring."
        ),
        "threshold": PL_STRONG_HOME_FAVORITE_THRESHOLD,
        "scope": "verified frozen Thursday calls; research only; no automatic tuning or promotion",
        "premier_league_resolved": len(rows),
        "paired_mean_delta_log_loss_control_vs_primary": (
            float(np.mean([row[4] for row in rows])) if rows else None
        ),
        "strong_home_favorites": {
            "matches": len(favorites),
            "observed_home_wins": sum(row[0] == "H" for row in favorites),
            "observed_draws": sum(row[0] == "D" for row in favorites),
            "observed_away_wins": len(away_upsets),
            "observed_home_win_rate": (
                sum(row[0] == "H" for row in favorites) / len(favorites) if favorites else None
            ),
            "mean_primary_home_win_probability": (
                float(np.mean([row[2] for row in favorites])) if favorites else None
            ),
            "mean_control_home_win_probability": (
                float(np.mean([row[3] for row in favorites])) if favorites else None
            ),
            "paired_mean_delta_log_loss_control_vs_primary": (
                float(np.mean([row[4] for row in favorites])) if favorites else None
            ),
            "away_upset_log_loss_delta_sum": float(sum(row[4] for row in away_upsets)),
        },
        "delta_interpretation": "negative favors compact control; descriptive until enough live calls resolve",
    }


def score_rows(rows: list[dict], actual: dict[str, dict]) -> dict:
    resolved = []
    for row in rows:
        outcome = actual.get(str(row["game_id"]))
        if outcome is None:
            continue
        hg, ag = int(outcome["home_score"]), int(outcome["away_score"])
        resolved.append((row, hg, ag))
    if not resolved:
        return {"matches": 0, "status": "awaiting_results"}
    labels = np.asarray(["H" if hg > ag else "D" if hg == ag else "A" for _, hg, ag in resolved])
    probabilities = np.asarray([
        [float(row[field]) for field in (
            "home_win_probability", "draw_probability", "away_win_probability"
        )]
        for row, _, _ in resolved
    ])
    result = baseline.score(
        labels, probabilities,
        np.asarray([hg for _, hg, _ in resolved]),
        np.asarray([ag for _, _, ag in resolved]),
        np.asarray([float(row["home_expected_goals"]) for row, _, _ in resolved]),
        np.asarray([float(row["away_expected_goals"]) for row, _, _ in resolved]),
    )
    result["matches"] = len(resolved)
    result["by_league"] = {}
    for league in baseline.TOP_FIVE:
        league_rows = [row for row, _, _ in resolved if row["league"] == league]
        result["by_league"][league] = {"matches": len(league_rows)}
        if league_rows:
            league_ids = {str(row["game_id"]) for row in league_rows}
            filtered = [(row, hg, ag) for row, hg, ag in resolved if str(row["game_id"]) in league_ids]
            indices = np.array([index for index, (row, _, _) in enumerate(resolved)
                                if str(row["game_id"]) in league_ids])
            result["by_league"][league] = baseline.score(
                labels[indices], probabilities[indices],
                np.asarray([hg for _, hg, _ in filtered]),
                np.asarray([ag for _, _, ag in filtered]),
                np.asarray([float(row["home_expected_goals"]) for row, _, _ in filtered]),
                np.asarray([float(row["away_expected_goals"]) for row, _, _ in filtered]),
            ) | {"matches": len(filtered)}
    return result


def cumulative(season: str, research_dir: Path, matches: list[dict]) -> dict:
    tournament_paths = sorted(research_dir.glob(f"{season}_*_tournament.json"))
    canonical = {
        str(row["game_id"]): row for row in matches
        if row.get("home_score") is not None and row.get("away_score") is not None
    }
    chosen = {model: {} for model in MODELS}
    weeks = []
    for path in tournament_paths:
        verification = audit_frozen_tournament.audit(path)
        if not verification["passed"]:
            raise RuntimeError(f"refusing to score unverified frozen tournament: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        as_of = contract.instant(payload["as_of"])
        through = contract.instant(payload["evaluation_through"])
        snapshots = {"primary": Path(payload["primary"])} | {
            name: Path(location) for name, location in payload["challengers"].items()
        }
        expected = set(contract.expected_week(
            contract.load_manifest(Path(payload["fixture_manifest"]), season, as_of, strict_capture=True),
            as_of, through,
        ))
        for model in MODELS:
            snapshot = json.loads(snapshots[model].read_text(encoding="utf-8"))
            eligible, _ = snapshot_score.evaluation_predictions(snapshot)
            for row in eligible:
                chosen[model].setdefault(str(row["game_id"]), row)
        canonical_window = {
            str(row["game_id"])
            for row in matches
            if row.get("home_score") is not None and row.get("away_score") is not None
            and as_of < contract.fixture_instant(row) <= through
        }
        completed = expected & canonical_window
        omitted = canonical_window - expected
        weeks.append({
            "as_of": as_of.isoformat(),
            "expected_calls": len(expected),
            "resolved_calls": len(completed),
            "pending_calls": len(expected - completed),
            "later_verified_omitted_fixture_ids": sorted(omitted),
            "complete_result_window": len(completed) == len(expected) and not omitted,
            "tournament": str(path),
        })
    ids = set(chosen["primary"])
    if any(set(chosen[model]) != ids for model in MODELS):
        raise RuntimeError("tournament models do not share the exact same cumulative fixture population")
    scored_ids = ids & set(canonical)
    metrics = {model: score_rows(
        [chosen[model][game_id] for game_id in sorted(ids)], canonical
    ) for model in MODELS}
    comparisons = {}
    actual_labels = {
        game_id: ("H" if canonical[game_id]["home_score"] > canonical[game_id]["away_score"]
                  else "D" if canonical[game_id]["home_score"] == canonical[game_id]["away_score"] else "A")
        for game_id in scored_ids
    }
    fields = {"H": "home_win_probability", "D": "draw_probability", "A": "away_win_probability"}
    for model in MODELS[1:]:
        deltas = []
        for game_id in sorted(scored_ids):
            field = fields[actual_labels[game_id]]
            primary_probability = float(chosen["primary"][game_id][field])
            challenger_probability = float(chosen[model][game_id][field])
            deltas.append(-math.log(challenger_probability) + math.log(primary_probability))
        comparisons[model] = {
            "paired_matches": len(deltas),
            "mean_delta_log_loss_vs_primary": float(np.mean(deltas)) if deltas else None,
            "interpretation": "negative favors challenger; research only",
        }
    by_league = metrics["primary"].get("by_league", {})
    sample_ready = (
        len(scored_ids) >= 100
        and all(by_league.get(league, {}).get("matches", 0) >= 20 for league in baseline.TOP_FIVE)
        and sum(week["complete_result_window"] for week in weeks) >= 3
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "season": season,
        "scope": "private_research_only_no_automatic_promotion",
        "verified_tournaments": len(weeks),
        "weeks": weeks,
        "same_fixture_calls": len(ids),
        "scored_same_fixture_calls": len(scored_ids),
        "metrics": metrics,
        "paired_comparisons": comparisons,
        "premier_home_favorite_monitor": premier_home_favorite_monitor(chosen, canonical),
        "review_gate": {
            "minimum_scored": 100, "minimum_per_league": 20,
            "minimum_complete_windows": 3,
            "ready_for_human_review": sample_ready,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2627")
    parser.add_argument("--research-dir", type=Path, default=Path("artifacts/predictions/research"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/model_reports/shadow_tournament_scorecard.json"))
    args = parser.parse_args()
    paths = list(args.research_dir.glob(f"{args.season}_*_tournament.json"))
    if paths:
        db = baseline.db_client()
        matches = baseline.fetch_pages(
            db.table("matches")
            .select("game_id,season,league,date,kickoff_at,home_score,away_score")
            .eq("season", args.season)
            .in_("league", list(baseline.TOP_FIVE))
            .order("game_id")
        )
        report = cumulative(args.season, args.research_dir, matches)
    else:
        report = {
            "generated_at": datetime.now(UTC).isoformat(),
            "season": args.season,
            "scope": "private_research_only_no_automatic_promotion",
            "verified_tournaments": 0,
            "status": "awaiting_first_real_thursday_tournament",
            "review_gate": {"ready_for_human_review": False},
            "premier_home_favorite_monitor": premier_home_favorite_monitor(
                {"primary": {}, "compact_control": {}}, {}
            ),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Tournament scorecard: {report.get('status', 'scored')} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
