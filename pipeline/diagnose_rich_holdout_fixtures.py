#!/usr/bin/env python3
"""Reproduce 2025/26 holdout errors by fixture without touching live models."""

from __future__ import annotations

import csv
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import evaluate_multiseason_model as multi
import train_match_baselines as baseline


ROOT = Path(__file__).resolve().parents[1]
FOLD = "2324_2425_to_2526"
CANDIDATES = (
    "current_compact_control", "field_tilt_box_entries", "xt_difference_5",
    "box_entry_sequences_5", "expected_threat", "rich_attack",
)
DIAGNOSTIC_INPUTS = (
    "elo_diff", "team.shots_5", "opponent.shots_5",
    "team.field_tilt_pct_5", "opponent.field_tilt_pct_5",
    "team.box_entries_pass_5", "opponent.box_entries_pass_5",
    "team.xt_difference_5", "opponent.xt_difference_5",
    "team.npxg_difference_5", "opponent.npxg_difference_5",
)
FOCUS_LEAGUES = ("ENG-Premier League", "ESP-La Liga")


def contribution(rows: list[dict], candidate: str) -> dict:
    deltas = [row[f"{candidate}_minus_control_log_loss"] for row in rows]
    return {
        "fixtures": len(rows),
        "mean_delta_log_loss": float(np.mean(deltas)),
        "sum_delta_log_loss": float(np.sum(deltas)),
        "worse_fixture_count": sum(delta > 0 for delta in deltas),
        "better_fixture_count": sum(delta < 0 for delta in deltas),
        "positive_loss_sum": float(sum(max(delta, 0) for delta in deltas)),
        "negative_loss_sum": float(sum(min(delta, 0) for delta in deltas)),
    }


def fixture_view(row: dict, candidate: str) -> dict:
    fields = (
        "game_id", "date", "league", "home_team", "away_team", "score",
        "actual_result", "current_compact_control_actual_probability",
        f"{candidate}_actual_probability", f"{candidate}_minus_control_log_loss",
    )
    return {key: row[key] for key in fields}


def frozen_snapshot_context() -> dict:
    path = ROOT / "artifacts" / "model_reports" / "shadow_weekend_review_20260917.json"
    if not path.exists():
        return {"status": "unavailable", "reason": "17 September frozen review not found"}
    review = json.loads(path.read_text(encoding="utf-8"))
    rows = [row for row in review["all_matches"] if row["league"] in FOCUS_LEAGUES]
    return {
        "status": "descriptive_only_no_same_fixture_challenger",
        "source": str(path),
        "model_version": review["model_version"],
        "snapshot_as_of": review["as_of"],
        "generated_at": review["generated_at"],
        "covered_matches": len(review["all_matches"]),
        "missing_completed_fixtures": len(review["coverage"]["missing_completed_fixtures"]),
        "by_league": {
            league: {
                "matches": len(selected),
                "log_loss": float(np.mean([row["log_loss"] for row in selected])),
                "high_loss_fixtures": [
                    {"home_team": row["home_team"], "away_team": row["away_team"],
                     "score": f"{row['home_score']}-{row['away_score']}",
                     "log_loss": row["log_loss"], "actual_probability": row["actual_probability"]}
                    for row in sorted(selected, key=lambda row: row["log_loss"], reverse=True)[:5]
                ],
            }
            for league in FOCUS_LEAGUES
            if (selected := [row for row in rows if row["league"] == league])
        },
        "caveat": (
            "Only the registered shadow model had genuine frozen Thursday calls. "
            "Historical challengers cannot be retroactively frozen on these fixtures; "
            "this section does not compare their live predictive performance."
        ),
    }


def main() -> int:
    source_path = ROOT / "artifacts" / "model_reports" / "v2_feature_candidate_audit.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("feature_schema_version") != 2:
        raise RuntimeError("v2 feature report is required")
    db = baseline.db_client()
    parts = []
    for season in ("2324", "2425", "2526"):
        frame = baseline.load_matches(db, season, 2)
        frame["season"] = season
        parts.append(frame)
    combined = pd.concat(parts, ignore_index=True).sort_values(["date", "game_id"]).reset_index(drop=True)
    baseline.add_pre_match_elo(combined)
    train = combined[combined.season.isin(("2324", "2425"))]
    test = combined[combined.season.eq("2526")].reset_index(drop=True)
    if len(test) != 1752 or train.date.max() >= test.date.min():
        raise RuntimeError("2025/26 holdout count or chronology failed")
    labels = np.asarray([baseline.CLASS_ORDER.index(value) for value in test.result])
    indices = np.arange(len(test))
    rows = [
        {
            "game_id": str(row.game_id), "date": row.date.date().isoformat(),
            "league": row.league, "home_team": row.home_team,
            "away_team": row.away_team, "score": f"{row.home_goals}-{row.away_goals}",
            "actual_result": row.result,
        }
        for row in test.itertuples(index=False)
    ]
    for field in DIAGNOSTIC_INPUTS:
        if field in test:
            for row, value in zip(rows, test[field], strict=True):
                row[field] = None if pd.isna(value) else round(float(value), 5)
    outcomes = {}
    for candidate in CANDIDATES:
        selected = source["folds"][FOLD][candidate]["columns"]
        metrics, probabilities, home_goals, away_goals = multi.model_metrics(train, test, selected)
        expected = source["folds"][FOLD][candidate]["log_loss"]
        if not math.isclose(metrics["log_loss"], expected, abs_tol=1e-10):
            raise RuntimeError(f"{candidate}: holdout result did not reproduce")
        actual_probability = probabilities[indices, labels]
        outcome_loss = -np.log(np.clip(actual_probability, 1e-12, 1.0))
        outcomes[candidate] = outcome_loss
        for number, row in enumerate(rows):
            row[f"{candidate}_actual_probability"] = round(float(actual_probability[number]), 8)
            row[f"{candidate}_log_loss"] = float(outcome_loss[number])
            row[f"{candidate}_predicted_home_goals"] = round(float(home_goals[number]), 4)
            row[f"{candidate}_predicted_away_goals"] = round(float(away_goals[number]), 4)
            for label, value in zip(baseline.CLASS_ORDER, probabilities[number], strict=True):
                row[f"{candidate}_probability_{label}"] = round(float(value), 8)
    for candidate in CANDIDATES[1:]:
        difference = outcomes[candidate] - outcomes["current_compact_control"]
        for row, delta in zip(rows, difference, strict=True):
            row[f"{candidate}_minus_control_log_loss"] = float(delta)
    league_summary = {}
    for league in baseline.TOP_FIVE:
        selected = [row for row in rows if row["league"] == league]
        league_summary[league] = {candidate: contribution(selected, candidate)
                                  for candidate in CANDIDATES[1:]}
        for candidate in ("expected_threat", "rich_attack"):
            league_summary[league][candidate]["largest_worsened"] = [
                fixture_view(row, candidate) for row in sorted(
                    selected, key=lambda row: row[f"{candidate}_minus_control_log_loss"],
                    reverse=True)[:10]
            ]
            league_summary[league][candidate]["largest_improved"] = [
                fixture_view(row, candidate) for row in sorted(
                    selected, key=lambda row: row[f"{candidate}_minus_control_log_loss"])[:10]
            ]
    for candidate in CANDIDATES[1:]:
        actual = np.mean(outcomes[candidate] - outcomes["current_compact_control"])
        reconciled = sum(league_summary[league][candidate]["sum_delta_log_loss"]
                         for league in baseline.TOP_FIVE) / len(test)
        if not math.isclose(actual, reconciled, abs_tol=1e-12):
            raise RuntimeError(f"{candidate}: league decomposition did not reconcile")
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "historical_source": str(source_path),
        "population": "1752 completed top-five-league 2025/26 fixtures",
        "metric": "per-fixture negative log probability assigned to actual home/draw/away result",
        "comparison": "candidate minus compact shooting control; positive is worse",
        "league_summary": league_summary,
        "frozen_2627_context": frozen_snapshot_context(),
        "limitations": [
            "Largest fixture contributions are arithmetic drivers, not causal explanations.",
            "Historical trials are pre-match, not a frozen Thursday slate.",
            "The 2026/27 shadow snapshot has no same-fixture tactical challenger calls.",
        ],
    }
    output = ROOT / "artifacts" / "model_reports" / "historical_2526_fixture_diagnostic.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    csv_path = output.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Historical fixtures: {len(rows)}")
    print(f"Report: {output}")
    print(f"Fixture CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
