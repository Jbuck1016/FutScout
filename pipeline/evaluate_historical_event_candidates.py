#!/usr/bin/env python3
"""Private, point-in-time trials of newly backfilled event and carry signals.

Match observations are turned into rolling pre-match features in memory. The
database is read only; no model is registered, promoted, or published.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import analyze_match_feature_families as families
import evaluate_multiseason_model as multi
import train_match_baselines as baseline


SEASONS = ("2324", "2425", "2526")
EVENT_FIELDS = (
    "completed_progressive_passes", "completed_final_third_entries",
    "completed_box_entries", "pass_xt_positive", "high_ball_recoveries",
    "high_defensive_actions", "non_penalty_shots", "non_penalty_box_shots",
    "non_penalty_big_chances", "non_penalty_mean_shot_distance_m",
)
CARRY_FIELDS = ("progressive_carries", "carry_box_entries", "carry_xt_positive")
ROLLING_FIELDS = (
    "completed_progressive_passes", "completed_final_third_entries",
    "completed_box_entries", "pass_xt_positive", "high_ball_recoveries",
    "high_defensive_actions", *CARRY_FIELDS,
)
GROUPS = {
    "progression": ("completed_progressive_passes", "completed_final_third_entries",
                    "completed_box_entries", "pass_xt_positive"),
    "pressing": ("high_ball_recoveries", "high_defensive_actions"),
    "carry": CARRY_FIELDS,
    "quality": ("npxg_per_shot", "box_shot_share", "big_chance_rate", "mean_shot_distance_m"),
}


def fetch_source(db, table: str, fields: tuple[str, ...]) -> pd.DataFrame:
    rows = baseline.fetch_pages(
        db.table(table)
        .select("game_id,team,season," + ",".join(fields))
        .in_("season", list(SEASONS))
        .order("season").order("game_id").order("team")
    )
    frame = pd.DataFrame(rows)
    if frame.empty or frame.duplicated(["game_id", "team"]).any():
        raise RuntimeError(f"{table}: empty or duplicate game/team rows")
    return frame


def load_side_observations(db, matches: pd.DataFrame) -> pd.DataFrame:
    outcomes = baseline.fetch_pages(
        db.table("v_ml_team_match_outcomes")
        .select("game_id,team,match_date,season")
        .in_("season", list(SEASONS))
        .in_("league", list(baseline.TOP_FIVE))
        .order("season").order("game_id").order("team")
    )
    sides = pd.DataFrame(outcomes)
    wanted = set(matches.game_id.astype(str))
    sides = sides[sides.game_id.astype(str).isin(wanted)].copy()
    if len(sides) != 2 * len(matches) or sides.duplicated(["game_id", "team"]).any():
        raise RuntimeError("outcome sides are not exactly two per evaluated match")
    event = fetch_source(db, "ml_historical_event_candidates", EVENT_FIELDS)
    carry = fetch_source(db, "ml_historical_carry_candidates", CARRY_FIELDS)
    keys = ["game_id", "team", "season"]
    sides = sides.merge(event[keys + list(EVENT_FIELDS)], on=keys, how="left", validate="one_to_one", indicator=True)
    if not sides._merge.eq("both").all():
        raise RuntimeError("historical event candidate coverage is incomplete")
    sides = sides.drop(columns="_merge")
    sides = sides.merge(carry[keys + list(CARRY_FIELDS)], on=keys, how="left", validate="one_to_one", indicator=True)
    if not sides._merge.eq("both").all():
        raise RuntimeError("historical carry candidate coverage is incomplete")
    sides = sides.drop(columns="_merge")
    xg_rows = baseline.fetch_pages(
        db.table("ml_team_match_observations")
        .select("game_id,team,season,npxg_for,non_penalty_shot_count")
        .in_("season", list(SEASONS))
        .eq("observation_schema_version", 2)
        .order("season").order("game_id").order("team")
    )
    xg = pd.DataFrame(xg_rows)
    if xg.empty or xg.duplicated(["game_id", "team"]).any():
        raise RuntimeError("historical shot-quality observations are empty or duplicated")
    sides = sides.merge(xg, on=keys, how="left", validate="one_to_one", indicator=True)
    if not sides._merge.eq("both").all():
        raise RuntimeError("historical shot-quality observation coverage is incomplete")
    sides = sides.drop(columns="_merge")
    sides["match_date"] = pd.to_datetime(sides.match_date)
    for field in (*EVENT_FIELDS, *CARRY_FIELDS, "npxg_for", "non_penalty_shot_count"):
        sides[field] = pd.to_numeric(sides[field], errors="coerce")
    if sides[list(ROLLING_FIELDS) + ["non_penalty_shots", "non_penalty_box_shots",
                                    "non_penalty_big_chances", "npxg_for",
                                    "non_penalty_shot_count"]].isna().any().any():
        raise RuntimeError("required event/carry observations contain nulls")
    if not sides.non_penalty_shots.eq(sides.non_penalty_shot_count).all():
        raise RuntimeError("event and v2 non-penalty shot denominators disagree")
    return sides.sort_values(["team", "match_date", "game_id"])


def summarize(history: list[dict], window: int) -> dict[str, float]:
    previous = history[-window:]
    if not previous:
        return {}
    result = {
        field: float(np.mean([row[field] for row in previous]))
        for field in ROLLING_FIELDS
    }
    shots = sum(row["non_penalty_shots"] for row in previous)
    result["npxg_per_shot"] = float(
        (sum(row["npxg_for"] for row in previous) + 0.1) / (shots + 1)
    )
    result["box_shot_share"] = float(
        (sum(row["non_penalty_box_shots"] for row in previous) + 1) / (shots + 2)
    )
    result["big_chance_rate"] = float(
        (sum(row["non_penalty_big_chances"] for row in previous) + 0.5) / (shots + 1)
    )
    distance_rows = [row for row in previous if pd.notna(row["non_penalty_mean_shot_distance_m"])
                     and row["non_penalty_shots"] > 0]
    if distance_rows:
        result["mean_shot_distance_m"] = float(
            sum(row["non_penalty_mean_shot_distance_m"] * row["non_penalty_shots"]
                for row in distance_rows)
            / sum(row["non_penalty_shots"] for row in distance_rows)
        )
    return result


def rolling_features(sides: pd.DataFrame, windows: tuple[int, ...] = (5, 10)) -> dict[tuple[str, str], dict[str, float]]:
    """Freeze each date before adding any of that date's observations."""
    result: dict[tuple[str, str], dict[str, float]] = {}
    for _, team_rows in sides.groupby("team", sort=False):
        history: list[dict] = []
        for _, same_date in team_rows.groupby("match_date", sort=True):
            for row in same_date.to_dict("records"):
                features = {}
                for window in windows:
                    features.update({f"{name}_{window}": value
                                     for name, value in summarize(history, window).items()})
                result[(str(row["game_id"]), row["team"])] = features
            history.extend(same_date.to_dict("records"))
    return result


def add_candidate_features(matches: pd.DataFrame, sides: pd.DataFrame) -> pd.DataFrame:
    history = rolling_features(sides)
    rows = []
    for row in matches.itertuples(index=False):
        home = history[(str(row.game_id), row.home_team)]
        away = history[(str(row.game_id), row.away_team)]
        rows.append({
            **{f"candidate.team.{key}": value for key, value in home.items()},
            **{f"candidate.opponent.{key}": value for key, value in away.items()},
        })
    extra = pd.DataFrame(rows, index=matches.index)
    return pd.concat([matches, extra], axis=1)


def candidate_columns(frame: pd.DataFrame) -> dict[str, list[str]]:
    base = [column for column in frame if not column.startswith("candidate.")]
    core = multi.select_features(frame[base], "core")
    shooting = multi.select_features(frame[base], "core_shooting")
    grouped = families.family_columns(multi.select_features(frame[base], "all"))
    def group(name: str) -> set[str]:
        return {column for column in frame if column.startswith("candidate.")
                and any(f".{field}_" in column for field in GROUPS[name])}
    progress, press, carry, quality = (group(name) for name in GROUPS)
    xg_per_shot = {column for column in quality if ".npxg_per_shot_5" in column}
    territory = {column for column in grouped["territory"]
                 if any(token in column for token in ("field_tilt_pct_5", "box_entries_pass_5"))}
    threat = {column for column in grouped["expected_threat"]
              if any(token in column for token in ("xt_created_5", "xt_conceded_5"))}
    sets = {
        "shooting_control": set(shooting),
        "shooting_plus_progression": set(shooting) | progress,
        "shooting_plus_pressing": set(shooting) | press,
        "shooting_plus_carry": set(shooting) | carry,
        "shooting_plus_quality": set(shooting) | quality,
        "shooting_plus_xg_per_shot": set(shooting) | xg_per_shot,
        "shooting_plus_all_candidates": set(shooting) | progress | press | carry | quality,
        "territory_threat_no_shots": set(core) | territory | threat,
        "territory_plus_events_no_shots": set(core) | territory | threat | progress | press | carry,
        "territory_plus_quality_no_shots": set(core) | territory | threat | progress | carry | quality,
        "territory_plus_xg_per_shot_no_shots": set(core) | territory | threat | xg_per_shot,
    }
    if any(not columns for columns in (progress, press, carry, quality, xg_per_shot, territory, threat)):
        raise RuntimeError("a required experimental feature group was empty")
    return {name: sorted(columns) for name, columns in sets.items()}


def paired_delta_ci(actual: np.ndarray, challenger: np.ndarray, control: np.ndarray) -> dict[str, float]:
    labels = np.array([baseline.CLASS_ORDER.index(value) for value in actual])
    idx = np.arange(len(labels))
    difference = -np.log(np.clip(challenger[idx, labels], 1e-12, 1)) + np.log(
        np.clip(control[idx, labels], 1e-12, 1))
    rng = np.random.default_rng(20260922)
    draws = rng.integers(0, len(labels), size=(1000, len(labels)))
    low, high = np.quantile(difference[draws].mean(axis=1), [0.025, 0.975])
    return {"delta_log_loss": float(difference.mean()), "bootstrap_ci_95": [float(low), float(high)]}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    for season in SEASONS:
        gate = json.loads((root / "artifacts" / "data_quality" /
                           f"model_data_quality_v2_{season}.json").read_text(encoding="utf-8"))
        if not gate["release_ready_for_core_v2_experiments"]:
            raise RuntimeError(f"{season}: v2 quality gate failed")
    db = baseline.db_client()
    frames = []
    for season in SEASONS:
        part = baseline.load_matches(db, season, 2)
        part["season"] = season
        frames.append(part)
    matches = pd.concat(frames, ignore_index=True).sort_values(["date", "game_id"]).reset_index(drop=True)
    if len(matches) != 5255:
        raise RuntimeError(f"expected 5255 historical fixtures, got {len(matches)}")
    baseline.add_pre_match_elo(matches)
    sides = load_side_observations(db, matches)
    matches = add_candidate_features(matches, sides)
    columns = candidate_columns(matches)
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "purpose": "Private event/carry feature-family trials; no lifecycle change",
        "fixtures": len(matches), "source_sides": len(sides),
        "feature_contract": columns,
        "rolling_rule": "Only earlier calendar dates; 5/10 prior team matches; cross-season history allowed",
        "folds": {}, "decision": "research_only_no_lifecycle_change",
    }
    for name, train_seasons, test_season in (
        ("2324_to_2425", ("2324",), "2425"),
        ("2324_2425_to_2526", ("2324", "2425"), "2526"),
    ):
        train = matches[matches.season.isin(train_seasons)]
        test = matches[matches.season.eq(test_season)]
        if train.date.max() >= test.date.min():
            raise RuntimeError(f"{name}: non-chronological holdout")
        scored = {}
        control_probabilities = None
        for candidate, selected in columns.items():
            metrics, probabilities, _, _ = multi.model_metrics(train, test, selected)
            if candidate == "shooting_control":
                control_probabilities = probabilities
            scored[candidate] = {
                "columns": selected, "column_count": len(selected),
                **{key: metrics[key] for key in (
                    "matches", "log_loss", "brier", "accuracy", "calibration_error",
                    "home_goals_mae", "away_goals_mae", "by_league")},
                "paired_vs_shooting": paired_delta_ci(
                    test.result.to_numpy(), probabilities, control_probabilities),
            }
            print(f"{name} {candidate}: {metrics['log_loss']:.5f}", flush=True)
        report["folds"][name] = scored
    summary = []
    for candidate in columns:
        values = [fold[candidate]["log_loss"] for fold in report["folds"].values()]
        controls = [fold["shooting_control"]["log_loss"] for fold in report["folds"].values()]
        summary.append({"candidate": candidate, "mean_log_loss": sum(values) / len(values),
                        "holdout_log_loss": values,
                        "beats_control_both_holdouts": all(value < control for value, control in zip(values, controls))})
    report["summary"] = sorted(summary, key=lambda row: row["mean_log_loss"])
    output = root / "artifacts" / "model_reports" / "historical_event_candidate_trials.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
