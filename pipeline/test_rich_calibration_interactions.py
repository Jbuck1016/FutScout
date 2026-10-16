#!/usr/bin/env python3
"""Research-only chronological tests of goal calibration and tactical interactions.

Reads existing schema-v2 snapshots. The final season of each fold is never used
to fit offsets or select interaction terms. Does not register or activate models.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import evaluate_multiseason_model as multi
import evaluate_v2_feature_candidates as candidates
import train_match_baselines as baseline


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "artifacts" / "model_reports" / "v2_feature_candidate_audit.json"
OUTPUT = ROOT / "artifacts" / "model_reports" / "rich_calibration_interaction_trials.json"
INNER_CALIBRATION_FRACTION = 0.20
GLOBAL_PRIOR_MATCHES = 40.0
LEAGUE_PRIOR_MATCHES = 100.0
GOAL_PSEUDOCOUNT = 1.0


def inner_split(train: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    dates = pd.DatetimeIndex(train["date"].drop_duplicates().sort_values())
    if len(dates) < 5:
        raise RuntimeError("too few training dates for an inner chronological split")
    split_at = min(len(dates) - 1, max(1, int(len(dates) * (1 - INNER_CALIBRATION_FRACTION))))
    calibration_start = pd.Timestamp(dates[split_at])
    fit = train[train.date < calibration_start].copy()
    calibration = train[train.date >= calibration_start].copy()
    if fit.empty or calibration.empty or fit.date.max() >= calibration.date.min():
        raise RuntimeError("inner chronological split is invalid")
    return fit, calibration, calibration_start.isoformat()


def goal_offsets(calibration: pd.DataFrame, home: np.ndarray, away: np.ndarray) -> dict:
    """Shrunk log-rate residuals; every input comes from pre-holdout rows."""
    if len(calibration) != len(home) or len(home) != len(away):
        raise ValueError("calibration prediction shape mismatch")
    global_offsets = {}
    league_offsets = {}
    for side, expected in (("home", home), ("away", away)):
        actual = calibration[f"{side}_goals"].to_numpy(dtype=float)
        prior = GLOBAL_PRIOR_MATCHES * float(np.mean(expected))
        global_offsets[side] = math.log((float(actual.sum()) + prior) /
                                        (float(expected.sum()) + prior))
        for league in baseline.TOP_FIVE:
            mask = calibration.league.eq(league).to_numpy()
            if not mask.any():
                continue
            raw = math.log((float(actual[mask].sum()) + GOAL_PSEUDOCOUNT) /
                           (float(expected[mask].sum()) + GOAL_PSEUDOCOUNT))
            weight = int(mask.sum()) / (int(mask.sum()) + LEAGUE_PRIOR_MATCHES)
            league_offsets.setdefault(league, {})[side] = (
                global_offsets[side] + weight * (raw - global_offsets[side])
            )
    return {
        "global": global_offsets,
        "by_league": league_offsets,
        "calibration_matches": len(calibration),
        "league_calibration_matches": {
            league: int(calibration.league.eq(league).sum()) for league in baseline.TOP_FIVE
        },
    }


def adjusted_predictions(
    test: pd.DataFrame, home: np.ndarray, away: np.ndarray, offsets: dict, mode: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if mode not in {"global", "league"}:
        raise ValueError(mode)
    if mode == "global":
        home_log = np.full(len(test), offsets["global"]["home"])
        away_log = np.full(len(test), offsets["global"]["away"])
    else:
        home_log = np.array([
            offsets["by_league"].get(league, offsets["global"])["home"]
            for league in test.league
        ])
        away_log = np.array([
            offsets["by_league"].get(league, offsets["global"])["away"]
            for league in test.league
        ])
    home_adjusted = np.clip(home * np.exp(home_log), 0.05, 6.0)
    away_adjusted = np.clip(away * np.exp(away_log), 0.05, 6.0)
    return (baseline.poisson_result_probabilities(home_adjusted, away_adjusted),
            home_adjusted, away_adjusted)


def interaction_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Predeclared interactions of pre-match inputs, no outcome-derived columns."""
    result = frame.copy()
    tilt = pd.to_numeric(result["team.field_tilt_pct_5"], errors="coerce") - pd.to_numeric(
        result["opponent.field_tilt_pct_5"], errors="coerce"
    )
    boxes = pd.to_numeric(result["team.box_entries_pass_5"], errors="coerce") - pd.to_numeric(
        result["opponent.box_entries_pass_5"], errors="coerce"
    )
    shots = pd.to_numeric(result["team.shots_5"], errors="coerce") - pd.to_numeric(
        result["opponent.shots_5"], errors="coerce"
    )
    elo = pd.to_numeric(result["elo_diff"], errors="coerce")
    result["interaction.elo_x_tilt_5"] = elo * tilt
    result["interaction.elo_x_boxes_5"] = elo * boxes
    result["interaction.shots_x_tilt_5"] = shots * tilt
    result["interaction.shots_x_boxes_5"] = shots * boxes
    return result


def scored(
    test: pd.DataFrame, probabilities: np.ndarray, home: np.ndarray, away: np.ndarray,
    control_probabilities: np.ndarray,
) -> dict:
    metrics = baseline.score(
        test.result.to_numpy(), probabilities,
        test.home_goals.to_numpy(), test.away_goals.to_numpy(), home, away,
    )
    metrics["matches"] = len(test)
    metrics["paired_vs_control"] = candidates.week_blocked_delta(
        test, probabilities, control_probabilities,
    )
    metrics["by_league"] = {}
    for league in baseline.TOP_FIVE:
        mask = test.league.eq(league).to_numpy()
        if not mask.any():
            continue
        league_metrics = baseline.score(
            test.loc[mask, "result"].to_numpy(), probabilities[mask],
            test.loc[mask, "home_goals"].to_numpy(), test.loc[mask, "away_goals"].to_numpy(),
            home[mask], away[mask],
        )
        league_metrics["matches"] = int(mask.sum())
        league_metrics["mean_predicted_home_win"] = float(probabilities[mask, 0].mean())
        league_metrics["observed_home_win"] = float(test.loc[mask, "result"].eq("H").mean())
        metrics["by_league"][league] = league_metrics
    return metrics


def main() -> int:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    if audit["feature_schema_version"] != 2:
        raise RuntimeError("schema-v2 candidate audit required")
    candidates.coverage_reports(ROOT)
    db = baseline.db_client()
    parts = []
    for season in ("2324", "2425", "2526"):
        frame = baseline.load_matches(db, season, 2)
        frame["season"] = season
        parts.append(frame)
    combined = pd.concat(parts, ignore_index=True).sort_values(["date", "game_id"]).reset_index(drop=True)
    baseline.add_pre_match_elo(combined)
    combined = interaction_frame(combined)
    definitions = {
        "compact_control": ("current_compact_control", []),
        "territory": ("field_tilt_box_entries", []),
        "rich_attack": ("rich_attack", []),
        "territory_elo_interactions": (
            "field_tilt_box_entries", ["interaction.elo_x_tilt_5", "interaction.elo_x_boxes_5"]
        ),
        "territory_shot_interactions": (
            "field_tilt_box_entries", ["interaction.shots_x_tilt_5", "interaction.shots_x_boxes_5"]
        ),
        "territory_all_interactions": (
            "field_tilt_box_entries", [
                "interaction.elo_x_tilt_5", "interaction.elo_x_boxes_5",
                "interaction.shots_x_tilt_5", "interaction.shots_x_boxes_5",
            ]
        ),
    }
    folds = (
        ("2324_to_2425", ("2324",), "2425"),
        ("2324_2425_to_2526", ("2324", "2425"), "2526"),
    )
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "purpose": "research_only_no_lifecycle_change",
        "seasons": ["2324", "2425", "2526"],
        "inner_calibration_fraction": INNER_CALIBRATION_FRACTION,
        "offset_policy": {
            "global_prior_matches": GLOBAL_PRIOR_MATCHES,
            "league_prior_matches": LEAGUE_PRIOR_MATCHES,
            "goal_pseudocount": GOAL_PSEUDOCOUNT,
            "description": "Calibrate on the last 20% of pre-holdout training dates; refit base model on all pre-holdout rows; never fit offsets to the holdout.",
        },
        "interaction_definitions": {
            "elo_x_tilt_5": "elo_diff × (team field tilt 5 - opponent field tilt 5)",
            "elo_x_boxes_5": "elo_diff × (team box entries 5 - opponent box entries 5)",
            "shots_x_tilt_5": "(team shots 5 - opponent shots 5) × field tilt difference 5",
            "shots_x_boxes_5": "(team shots 5 - opponent shots 5) × box entries difference 5",
        },
        "folds": {},
    }
    for fold_name, train_seasons, test_season in folds:
        train = combined[combined.season.isin(train_seasons)].copy()
        test = combined[combined.season.eq(test_season)].copy()
        if train.empty or test.empty or train.date.max() >= test.date.min():
            raise RuntimeError(f"{fold_name}: chronology invalid")
        fit, calibration, calibration_start = inner_split(train)
        fold = {
            "train_seasons": list(train_seasons),
            "test_season": test_season,
            "calibration_start": calibration_start,
            "train_matches": len(train),
            "test_matches": len(test),
            "variants": {},
            "offsets": {},
        }
        control_cols = audit["folds"][fold_name]["current_compact_control"]["columns"]
        control_raw, control_prob, control_home, control_away = multi.model_metrics(
            train, test, control_cols
        )
        reference = audit["folds"][fold_name]["current_compact_control"]["log_loss"]
        if not math.isclose(control_raw["log_loss"], reference, abs_tol=1e-10):
            raise RuntimeError(f"{fold_name}: control did not reproduce")
        fold["variants"]["compact_control"] = scored(
            test, control_prob, control_home, control_away, control_prob
        )
        for name, (base, extra) in definitions.items():
            if name == "compact_control":
                columns = control_cols
                probabilities, home, away = control_prob, control_home, control_away
            else:
                columns = audit["folds"][fold_name][base]["columns"] + extra
                _, probabilities, home, away = multi.model_metrics(train, test, columns)
            if name != "compact_control":
                fold["variants"][name] = scored(test, probabilities, home, away, control_prob)
            fold["variants"][name]["columns"] = columns
            if name not in {"compact_control", "territory", "rich_attack"}:
                continue
            _, _, inner_home, inner_away = multi.model_metrics(fit, calibration, columns)
            offsets = goal_offsets(calibration, inner_home, inner_away)
            fold["offsets"][name] = offsets
            for mode in ("global", "league"):
                adjusted, new_home, new_away = adjusted_predictions(
                    test, home, away, offsets, mode
                )
                fold["variants"][f"{name}_{mode}_offset"] = scored(
                    test, adjusted, new_home, new_away, control_prob
                )
            print(f"{fold_name} {name}: {fold['variants'][name]['log_loss']:.5f}")
        for name in definitions:
            if "interactions" in name:
                print(f"{fold_name} {name}: {fold['variants'][name]['log_loss']:.5f}")
        report["folds"][fold_name] = fold
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Report: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
