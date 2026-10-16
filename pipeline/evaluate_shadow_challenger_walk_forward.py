#!/usr/bin/env python3
"""Compare the frozen-slate model recipes on identical out-of-season fixtures.

Read-only against Supabase. Every fold fits both Poisson regressions using
earlier complete seasons only. This is research, not a model lifecycle action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import evaluate_multiseason_model as multi
import evaluate_v2_feature_candidates as candidates
import model_artifact
import test_rich_calibration_interactions as interactions
import train_match_baselines as baseline


ROOT = Path(__file__).resolve().parents[1]
SEASONS = ("2324", "2425", "2526")
FOLDS = (
    ("2324_to_2425", ("2324",), "2425"),
    ("2324_2425_to_2526", ("2324", "2425"), "2526"),
)
PRIMARY = ROOT / "artifacts/models/v2-field-tilt-box-entries-poisson-2324-2425-2526-20260914t205131z.pkl"
RESEARCH = ROOT / "artifacts/model_reports/shadow_research_challenger_artifacts.json"
MODELS = ("primary", "compact_control", "compact_xt_5", "box_sequences_5", "territory_elo_interactions")


def date_batched_pre_match_elo(frame: pd.DataFrame, k: float = 20.0,
                               home_advantage: float = 55.0) -> pd.DataFrame:
    """Update ratings only after every fixture on a date has been rated.

    Historical features contain a match date, not a guaranteed kickoff instant.
    Treating same-day fixtures as simultaneous avoids game-ID-order leakage.
    """
    result = frame.sort_values(["date", "game_id"]).copy().reset_index(drop=True)
    ratings: defaultdict[str, float] = defaultdict(lambda: 1500.0)
    for column in ("elo_home", "elo_away", "elo_diff"):
        result[column] = np.nan
    for _, group in result.groupby(result["date"].dt.normalize(), sort=True):
        changes: defaultdict[str, float] = defaultdict(float)
        for index, row in group.iterrows():
            home, away = ratings[str(row["home_team"])], ratings[str(row["away_team"])]
            result.at[index, "elo_home"] = home
            result.at[index, "elo_away"] = away
            result.at[index, "elo_diff"] = home + home_advantage - away
            expected = 1.0 / (1.0 + 10.0 ** (-((home + home_advantage - away) / 400.0)))
            home_goals, away_goals = int(row["home_goals"]), int(row["away_goals"])
            actual = 1.0 if home_goals > away_goals else 0.5 if home_goals == away_goals else 0.0
            margin = math.log1p(abs(home_goals - away_goals)) if home_goals != away_goals else 1.0
            change = k * margin * (actual - expected)
            changes[str(row["home_team"])] += change
            changes[str(row["away_team"])] -= change
        for team, change in changes.items():
            ratings[team] += change
    return result


def contracts(primary_path: Path, research_path: Path) -> tuple[dict[str, list[str]], dict]:
    primary = model_artifact.load_artifact(primary_path)
    reviewed = json.loads(research_path.read_text(encoding="utf-8"))
    if reviewed.get("purpose") != "private_research_only_unregistered_not_active":
        raise RuntimeError("challenger manifest is not private research only")
    paths = {"primary": primary_path} | {
        name: Path(reviewed["artifacts"][name]["path"]) for name in MODELS[1:]
    }
    columns = {}
    sources = {}
    for name, path in paths.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if name != "primary" and digest != reviewed["artifacts"][name]["sha256"]:
            raise RuntimeError(f"reviewed {name} artifact changed")
        artifact = primary if name == "primary" else model_artifact.load_artifact(path)
        if artifact["feature_schema_version"] != 2:
            raise RuntimeError(f"{name} is not a schema-v2 artifact")
        columns[name] = list(artifact["numeric_columns"])
        sources[name] = {"path": str(path), "sha256": digest,
                         "feature_count": len(columns[name]),
                         "trained_through": artifact["trained_through"]}
    return columns, sources


def availability(frame: pd.DataFrame, columns: list[str]) -> dict:
    missing = {column: int(frame[column].isna().sum()) for column in columns
               if frame[column].isna().any()}
    return {
        "matches": len(frame),
        "fixtures_with_any_missing_input": int(frame[columns].isna().any(axis=1).sum()),
        "missing_values_by_feature": missing,
    }


def metrics_for(test: pd.DataFrame, probabilities: np.ndarray,
                home_goals: np.ndarray, away_goals: np.ndarray) -> dict:
    output = baseline.score(
        test["result"].to_numpy(), probabilities,
        test["home_goals"].to_numpy(), test["away_goals"].to_numpy(),
        home_goals, away_goals,
    )
    return output | {"matches": len(test)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-artifact", type=Path, default=PRIMARY)
    parser.add_argument("--research-artifacts", type=Path, default=RESEARCH)
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts/model_reports/shadow_challenger_walk_forward_20260922.json")
    parser.add_argument("--fixture-predictions", type=Path, default=ROOT / "artifacts/model_reports/shadow_challenger_walk_forward_20260922.csv")
    args = parser.parse_args()
    candidates.coverage_reports(ROOT)
    columns, sources = contracts(args.primary_artifact, args.research_artifacts)
    db = baseline.db_client()
    seasons = []
    for season in SEASONS:
        part = baseline.load_matches(db, season, 2)
        part["season"] = season
        seasons.append(part)
    combined = pd.concat(seasons, ignore_index=True)
    if combined["game_id"].duplicated().any() or len(combined) != 5255:
        raise RuntimeError("historical match population changed; review its coverage before comparing")
    combined = interactions.interaction_frame(date_batched_pre_match_elo(combined))
    feature_union = set().union(*columns.values())
    missing_columns = sorted(feature_union - set(combined.columns))
    if missing_columns:
        raise RuntimeError(f"model contract missing historical inputs: {missing_columns}")
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "private_research_only_no_registration_or_promotion",
        "method": "fit each model on complete prior season(s); score identical later-season fixtures",
        "elo_policy": "same-date results cannot influence another fixture on that date",
        "selection_bias_warning": (
            "These exact feature contracts were influenced by earlier 2425 and 2526 holdout "
            "experiments. The folds test chronological fitting and stability, but are not "
            "untouched confirmation of a winning candidate. A new live frozen cohort is required."
        ),
        "prediction_time_warning": (
            "Historical feature rows are pre-match rolling snapshots, not archived Thursday "
            "captures. This evaluates match-time information and cannot reproduce the exact "
            "information set available on each Thursday."
        ),
        "sources": sources,
        "source_match_counts": {season: int(combined.season.eq(season).sum()) for season in SEASONS},
        "folds": {},
    }
    fixture_outputs = []
    pooled = {name: {"probabilities": [], "home": [], "away": []} for name in MODELS}
    pooled_tests = []
    for fold_name, train_seasons, test_season in FOLDS:
        train = combined[combined.season.isin(train_seasons)].copy()
        test = combined[combined.season.eq(test_season)].copy()
        if train.empty or test.empty or train.date.max() >= test.date.min():
            raise RuntimeError(f"invalid chronological fold: {fold_name}")
        fold = {
            "train_seasons": list(train_seasons), "test_season": test_season,
            "train_matches": len(train), "test_matches": len(test),
            "train_through": train.date.max().date().isoformat(),
            "test_from": test.date.min().date().isoformat(),
            "models": {},
        }
        results = {}
        for name in MODELS:
            metrics, probabilities, home, away = multi.model_metrics(train, test, columns[name])
            results[name] = (probabilities, home, away)
            fold["models"][name] = {
                "metrics": {key: value for key, value in metrics.items()
                            if key not in ("probability_bands", "by_league")},
                "by_league": metrics["by_league"],
                "availability_train": availability(train, columns[name]),
                "availability_test": availability(test, columns[name]),
                "feature_count": len(columns[name]),
            }
            pooled[name]["probabilities"].append(probabilities)
            pooled[name]["home"].append(home)
            pooled[name]["away"].append(away)
        control = results["primary"][0]
        for name in MODELS[1:]:
            fold["models"][name]["paired_vs_primary"] = candidates.week_blocked_delta(
                test, results[name][0], control,
            )
            fold["models"][name]["paired_by_league"] = {
                league: candidates.week_blocked_delta(
                    test[test.league.eq(league)].copy(),
                    results[name][0][test.league.eq(league).to_numpy()],
                    control[test.league.eq(league).to_numpy()],
                )
                for league in baseline.TOP_FIVE if test.league.eq(league).any()
            }
        report["folds"][fold_name] = fold
        fixture = test[["game_id", "date", "season", "league", "home_team", "away_team",
                        "home_goals", "away_goals", "result"]].copy()
        for name, (probabilities, home, away) in results.items():
            for index, label in enumerate(baseline.CLASS_ORDER):
                fixture[f"{name}_p_{label}"] = probabilities[:, index]
            fixture[f"{name}_home_xg"] = home
            fixture[f"{name}_away_xg"] = away
        fixture_outputs.append(fixture)
        pooled_tests.append(test)
        print(f"{fold_name}: {len(test)} identical fixtures scored by {len(MODELS)} models")
    pooled_test = pd.concat(pooled_tests, ignore_index=True)
    report["pooled"] = {}
    control = np.concatenate(pooled["primary"]["probabilities"])
    for name in MODELS:
        probabilities = np.concatenate(pooled[name]["probabilities"])
        home = np.concatenate(pooled[name]["home"])
        away = np.concatenate(pooled[name]["away"])
        report["pooled"][name] = {
            "metrics": metrics_for(pooled_test, probabilities, home, away),
            "by_league": {},
        }
        for league in baseline.TOP_FIVE:
            mask = pooled_test.league.eq(league).to_numpy()
            report["pooled"][name]["by_league"][league] = metrics_for(
                pooled_test.loc[mask], probabilities[mask], home[mask], away[mask]
            )
        if name != "primary":
            report["pooled"][name]["paired_vs_primary"] = candidates.week_blocked_delta(
                pooled_test, probabilities, control,
            )
    fixture_output = pd.concat(fixture_outputs, ignore_index=True)
    args.fixture_predictions.parent.mkdir(parents=True, exist_ok=True)
    fixture_output.to_csv(args.fixture_predictions, index=False, float_format="%.9f")
    report["fixture_predictions"] = str(args.fixture_predictions)
    report["fixture_predictions_sha256"] = hashlib.sha256(args.fixture_predictions.read_bytes()).hexdigest()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Report: {args.report}")
    print("Read-only Supabase analysis; no model lifecycle or live predictions changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
