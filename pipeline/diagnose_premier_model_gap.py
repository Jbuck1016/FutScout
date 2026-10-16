#!/usr/bin/env python3
"""Explain the historical Premier League control-vs-primary log-loss gap.

Uses the saved same-fixture export only. Descriptive decompositions are not
causal evidence that shooting or territory is intrinsically better.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "artifacts/model_reports/shadow_challenger_walk_forward_20260922.json"
EXPORT = ROOT / "artifacts/model_reports/shadow_challenger_walk_forward_20260922.csv"
OUTPUT = ROOT / "artifacts/model_reports/premier_model_gap_diagnostic_20260922.json"
LEAGUE = "ENG-Premier League"
SEED = 20260922


def grouped_contributions(frame: pd.DataFrame, column: str) -> dict:
    total = len(frame)
    return {
        str(group): {
            "fixtures": len(rows),
            "mean_delta_log_loss": float(rows.delta_loss.mean()),
            "additive_contribution_to_overall_mean": float(rows.delta_loss.sum() / total),
            "primary_log_loss": float(rows.primary_loss.mean()),
            "control_log_loss": float(rows.control_loss.mean()),
        }
        for group, rows in frame.groupby(column, sort=True, observed=True)
    }


def weekly_block_interval(frame: pd.DataFrame, draws: int = 5000) -> dict:
    if frame.empty:
        raise ValueError("at least one resolved fixture is required")
    week = frame.date.dt.to_period("W-SUN").astype(str)
    sums = frame.groupby(week).delta_loss.sum().to_numpy(dtype=float)
    counts = frame.groupby(week).size().to_numpy(dtype=int)
    rng = np.random.default_rng(SEED)
    selected = rng.integers(0, len(sums), size=(draws, len(sums)))
    samples = sums[selected].sum(axis=1) / counts[selected].sum(axis=1)
    return {
        "calendar_week_blocks": len(sums),
        "resamples": draws,
        "ci_95": [float(value) for value in np.quantile(samples, [0.025, 0.975])],
    }


def league_context(all_rows: pd.DataFrame) -> dict:
    output = {}
    for league, group in all_rows.groupby("league", sort=True):
        primary = group[["primary_p_H", "primary_p_D", "primary_p_A"]].to_numpy(dtype=float)
        control = group[["compact_control_p_H", "compact_control_p_D", "compact_control_p_A"]].to_numpy(dtype=float)
        labels = group.result.map({"H": 0, "D": 1, "A": 2}).to_numpy(dtype=int)
        index = np.arange(len(group))
        delta = np.log(np.clip(primary[index, labels], 1e-12, 1.0)) - np.log(
            np.clip(control[index, labels], 1e-12, 1.0)
        )
        home_favorite = (primary.argmax(axis=1) == 0) & (primary[:, 0] >= 0.55)
        output[league] = {
            "fixtures": len(group),
            "mean_delta_log_loss": float(delta.mean()),
            "strong_home_favorite_fixtures": int(home_favorite.sum()),
            "strong_home_favorite_observed_home_win_rate": float((labels[home_favorite] == 0).mean()),
            "strong_home_favorite_primary_mean_home_win_probability": float(primary[home_favorite, 0].mean()),
            "strong_home_favorite_control_mean_home_win_probability": float(control[home_favorite, 0].mean()),
        }
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    parser.add_argument("--export", type=Path, default=EXPORT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    digest = hashlib.sha256(args.export.read_bytes()).hexdigest()
    if digest != reference["fixture_predictions_sha256"]:
        raise RuntimeError("same-fixture export changed after the original comparison")
    all_rows = pd.read_csv(args.export, dtype={"game_id": str})
    if len(all_rows) != 3504 or all_rows.game_id.duplicated().any():
        raise RuntimeError("historical fixture population changed")
    frame = all_rows.loc[all_rows.league.eq(LEAGUE)].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    if len(frame) != 760 or set(frame.season.astype(str)) != {"2425", "2526"}:
        raise RuntimeError("expected 380 same-fixture Premier League games in each holdout")
    labels = frame.result.to_numpy()
    for name in ("primary", "compact_control"):
        probabilities = frame[[f"{name}_p_{label}" for label in ("H", "D", "A")]].to_numpy(dtype=float)
        if not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-6):
            raise RuntimeError(f"invalid {name} probability triples")
        actual = np.asarray([frame[f"{name}_p_{label}"].to_numpy(dtype=float)[index]
                             for index, label in enumerate(labels)])
        frame[f"{name}_loss"] = -np.log(np.clip(actual, 1e-12, 1.0))
    frame["control_loss"] = frame["compact_control_loss"]
    frame["delta_loss"] = frame.control_loss - frame.primary_loss
    frame["outcome"] = frame.result.map({"H": "home_win", "D": "draw", "A": "away_win"})
    primary_probabilities = frame[["primary_p_H", "primary_p_D", "primary_p_A"]].to_numpy(dtype=float)
    primary_pick = np.asarray(["H", "D", "A"])[primary_probabilities.argmax(axis=1)]
    home_favorite_mask = (primary_pick == "H") & (primary_probabilities.max(axis=1) >= 0.55)
    frame["home_favorite_away_win"] = np.where(
        home_favorite_mask & frame.result.eq("A").to_numpy(),
        "home_favorite_lost", "all_other_fixtures",
    )
    frame["primary_favorite_band"] = pd.cut(
        primary_probabilities.max(axis=1),
        bins=[0, 0.45, 0.55, 0.65, 1.0],
        labels=["below_45", "45_to_55", "55_to_65", "65_plus"],
        include_lowest=True,
    )
    if abs(float(frame.primary_loss.mean()) - reference["pooled"]["primary"]["by_league"][LEAGUE]["log_loss"]) > 1e-8:
        raise RuntimeError("Premier primary loss does not reconcile to the original report")
    if abs(float(frame.control_loss.mean()) - reference["pooled"]["compact_control"]["by_league"][LEAGUE]["log_loss"]) > 1e-8:
        raise RuntimeError("Premier control loss does not reconcile to the original report")
    outcome = grouped_contributions(frame, "outcome")
    season = grouped_contributions(frame, "season")
    bands = grouped_contributions(frame, "primary_favorite_band")
    home_favorite_upsets = grouped_contributions(frame, "home_favorite_away_win")
    if not np.isclose(sum(group["additive_contribution_to_overall_mean"] for group in outcome.values()),
                      frame.delta_loss.mean()):
        raise RuntimeError("outcome decomposition does not sum to the total gap")
    sorted_rows = frame.sort_values("delta_loss")
    changes = np.abs(primary_probabilities - frame[[
        "compact_control_p_H", "compact_control_p_D", "compact_control_p_A"
    ]].to_numpy(dtype=float))
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "historical_2425_2526_premier_only_research_not_lifecycle_change",
        "source_export_sha256": digest,
        "comparison": "compact_control_minus_primary_log_loss; negative favors compact control",
        "fixtures": len(frame),
        "primary_log_loss": float(frame.primary_loss.mean()),
        "compact_control_log_loss": float(frame.control_loss.mean()),
        "mean_delta_log_loss": float(frame.delta_loss.mean()),
        "weekly_block_uncertainty": weekly_block_interval(frame),
        "by_season": season,
        "by_outcome": outcome,
        "by_primary_favorite_band": bands,
        "home_favorite_away_win_split": home_favorite_upsets,
        "all_strong_home_favorites": {
            "fixtures": int(home_favorite_mask.sum()),
            "observed_away_wins": int((frame.result.eq("A").to_numpy() & home_favorite_mask).sum()),
            "observed_away_win_rate": float(frame.loc[home_favorite_mask, "result"].eq("A").mean()),
            "observed_home_win_rate": float(frame.loc[home_favorite_mask, "result"].eq("H").mean()),
            "primary_mean_home_win_probability": float(frame.loc[home_favorite_mask, "primary_p_H"].mean()),
            "control_mean_home_win_probability": float(frame.loc[home_favorite_mask, "compact_control_p_H"].mean()),
            "primary_mean_away_win_probability": float(frame.loc[home_favorite_mask, "primary_p_A"].mean()),
            "control_mean_away_win_probability": float(frame.loc[home_favorite_mask, "compact_control_p_A"].mean()),
            "mean_delta_log_loss": float(frame.loc[home_favorite_mask, "delta_loss"].mean()),
        },
        "tail_sensitivity": {
            str(size): {
                "largest_control_wins_contribution_to_overall_mean": float(sorted_rows.head(size).delta_loss.sum() / len(frame)),
                "mean_after_removing_largest_control_wins": float(sorted_rows.iloc[size:].delta_loss.mean()),
                "mean_after_removing_largest_primary_wins": float(sorted_rows.iloc[:-size].delta_loss.mean()),
                "mean_after_removing_both_tails": float(sorted_rows.iloc[size:-size].delta_loss.mean()),
            }
            for size in (5, 10, 20)
        },
        "probability_shift": {
            "mean_absolute_percentage_points_by_outcome": {
                label: float(changes[:, index].mean() * 100)
                for index, label in enumerate(("home_win", "draw", "away_win"))
            },
            "fixtures_with_any_shift_at_least_1_percentage_point": int((changes >= 0.01).any(axis=1).sum()),
            "fixtures_with_any_shift_at_least_2_percentage_points": int((changes >= 0.02).any(axis=1).sum()),
        },
        "cross_league_context": league_context(all_rows),
        "largest_control_wins": [
            {"game_id": str(row.game_id), "season": str(row.season),
             "home_team": row.home_team, "away_team": row.away_team,
             "outcome": row.outcome, "delta_log_loss": float(row.delta_loss),
             "primary_probability_of_actual_result": float(getattr(row, f"primary_p_{row.result}")),
             "control_probability_of_actual_result": float(getattr(row, f"compact_control_p_{row.result}"))}
            for row in sorted_rows.head(10).itertuples()
        ],
        "limitations": [
            "The same historical holdouts influenced candidate selection and cannot confirm a winning model.",
            "Outcome and favorite-band decompositions are descriptive, not causes of prediction accuracy.",
            "These are match-time historical features, not archived Thursday input snapshots.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Premier gap: {report['mean_delta_log_loss']:+.6f} across {len(frame)} fixtures")
    print(f"Report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
