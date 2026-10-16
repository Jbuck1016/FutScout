#!/usr/bin/env python3
"""Train and walk-forward evaluate leakage-safe match prediction baselines.

The command reads service-only feature snapshots, evaluates four increasingly
capable approaches on strictly later date blocks, and writes a reproducible
JSON report.  Registration is opt-in and never promotes a model to shadow or
active status; one-season benchmarks are recorded as ``training`` runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import httpx
from dotenv import load_dotenv
from score_probabilities import MINIMUM_SCORE, result_masses, score_matrix
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.metrics import accuracy_score, log_loss, mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from supabase import Client, create_client
from postgrest.exceptions import APIError


CLASS_ORDER = ("H", "D", "A")
TOP_FIVE = (
    "ENG-Premier League",
    "ESP-La Liga",
    "ITA-Serie A",
    "GER-Bundesliga",
    "FRA-Ligue 1",
)


def db_client() -> Client:
    repo_root = Path(__file__).resolve().parents[1]
    load_dotenv(repo_root / ".env")
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY are required")
    warm_rest_schema(url, key)
    return create_client(url, key)


def warm_rest_schema(url: str, key: str, attempts: int = 4) -> None:
    """Establish the PostgREST schema contract before paginated model reads."""
    endpoint = f"{url.rstrip('/')}/rest/v1/"
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    for attempt in range(attempts):
        response = httpx.get(endpoint, headers=headers, timeout=20)
        if response.status_code == 200:
            return
        if response.status_code not in (502, 503, 504) or attempt == attempts - 1:
            response.raise_for_status()
        time.sleep(0.75 * (2 ** attempt))


def execute_with_retry(query: Any, attempts: int = 4) -> Any:
    """Execute a query with bounded retries while PostgREST warms its schema cache."""
    for attempt in range(attempts):
        try:
            return query.execute()
        except APIError as exc:
            payload = exc.args[0] if exc.args and isinstance(exc.args[0], dict) else {}
            code = str(getattr(exc, "code", "") or payload.get("code", ""))
            if code != "PGRST002" or attempt == attempts - 1:
                raise
            time.sleep(0.75 * (2 ** attempt))
    raise RuntimeError("unreachable PostgREST retry state")


def fetch_pages(query: Any, page_size: int = 1000) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page = execute_with_retry(query.range(offset, offset + page_size - 1)).data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def load_matches(db: Client, season: str, schema_version: int) -> pd.DataFrame:
    outcomes = fetch_pages(
        db.table("v_ml_team_match_outcomes")
        .select("game_id,season,league,match_date,team,opponent,is_home,goals_for,goals_against,result")
        .eq("season", season)
        .eq("is_home", True)
        .in_("league", list(TOP_FIVE))
        .order("match_date")
        .order("game_id")
    )
    game_ids = sorted({str(row["game_id"]) for row in outcomes})
    features: list[dict] = []
    for offset in range(0, len(game_ids), 100):
        features.extend(fetch_pages(
            db.table("ml_team_match_features")
            .select("game_id,team,target_match_date,source_match_count,features")
            .eq("feature_schema_version", schema_version)
            .in_("game_id", game_ids[offset:offset + 100])
            .order("target_match_date")
            .order("game_id"),
            page_size=200,
        ))
    feature_by_key = {
        (str(row["game_id"]), row["team"]): row
        for row in features
    }
    records: list[dict] = []
    for outcome in outcomes:
        key = (str(outcome["game_id"]), outcome["team"])
        feature = feature_by_key.get(key)
        if feature is None:
            continue
        payload = feature["features"]
        record: dict[str, Any] = {
            "game_id": key[0],
            "date": outcome["match_date"],
            "league": outcome["league"],
            "home_team": outcome["team"],
            "away_team": outcome["opponent"],
            "home_goals": int(outcome["goals_for"]),
            "away_goals": int(outcome["goals_against"]),
            "result": {"W": "H", "D": "D", "L": "A"}[outcome["result"]],
            "source_match_count": int(feature["source_match_count"]),
        }
        flatten_numeric(payload, "", record)
        records.append(record)
    frame = pd.DataFrame(records)
    if frame.empty:
        raise RuntimeError("no joined home-side feature/outcome rows found")
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values(["date", "game_id"]).reset_index(drop=True)
    if frame["game_id"].duplicated().any():
        raise RuntimeError("duplicate home-side game rows found")
    return frame


def flatten_numeric(value: Any, prefix: str, target: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            flatten_numeric(child, f"{prefix}.{key}" if prefix else key, target)
    elif value is None or isinstance(value, (int, float)) and not isinstance(value, bool):
        target[prefix] = value


def add_pre_match_elo(frame: pd.DataFrame, k: float = 20.0, home_advantage: float = 55.0) -> None:
    ratings: defaultdict[str, float] = defaultdict(lambda: 1500.0)
    home_ratings: list[float] = []
    away_ratings: list[float] = []
    for row in frame.itertuples(index=False):
        home = ratings[row.home_team]
        away = ratings[row.away_team]
        home_ratings.append(home)
        away_ratings.append(away)
        expected = 1.0 / (1.0 + 10.0 ** (-((home + home_advantage) - away) / 400.0))
        actual = 1.0 if row.home_goals > row.away_goals else 0.5 if row.home_goals == row.away_goals else 0.0
        margin = math.log1p(abs(row.home_goals - row.away_goals)) if row.home_goals != row.away_goals else 1.0
        change = k * margin * (actual - expected)
        ratings[row.home_team] += change
        ratings[row.away_team] -= change
    frame["elo_home"] = home_ratings
    frame["elo_away"] = away_ratings
    frame["elo_diff"] = frame["elo_home"] + home_advantage - frame["elo_away"]


def date_folds(frame: pd.DataFrame, folds: int, initial_fraction: float) -> list[tuple[np.ndarray, np.ndarray]]:
    dates = pd.DatetimeIndex(frame["date"].drop_duplicates().sort_values())
    initial = max(1, int(len(dates) * initial_fraction))
    remaining = dates[initial:]
    blocks = [block for block in np.array_split(remaining, folds) if len(block)]
    result = []
    for block in blocks:
        train = np.flatnonzero((frame["date"] < pd.Timestamp(block[0])).to_numpy())
        test = np.flatnonzero(frame["date"].isin(pd.DatetimeIndex(block)).to_numpy())
        if len(train) and len(test):
            result.append((train, test))
    return result


def aligned_probabilities(model: Any, values: pd.DataFrame) -> np.ndarray:
    raw = model.predict_proba(values)
    aligned = np.zeros((len(values), len(CLASS_ORDER)))
    for index, label in enumerate(model.classes_):
        aligned[:, CLASS_ORDER.index(label)] = raw[:, index]
    return aligned


def prior_predictions(train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    counts = train.groupby(["league", "result"]).size().unstack(fill_value=0)
    global_counts = train["result"].value_counts()
    probabilities = []
    home_xg = []
    away_xg = []
    league_goal_means = train.groupby("league")[["home_goals", "away_goals"]].mean()
    global_goals = train[["home_goals", "away_goals"]].mean()
    for row in test.itertuples(index=False):
        league_counts = counts.loc[row.league] if row.league in counts.index else global_counts
        values = np.array([float(league_counts.get(label, 0)) + 2.0 for label in CLASS_ORDER])
        probabilities.append(values / values.sum())
        means = league_goal_means.loc[row.league] if row.league in league_goal_means.index else global_goals
        home_xg.append(float(means["home_goals"]))
        away_xg.append(float(means["away_goals"]))
    return np.asarray(probabilities), np.asarray(home_xg), np.asarray(away_xg)


def preprocessing(numeric: list[str], categorical: list[str]) -> ColumnTransformer:
    return ColumnTransformer(
        [
            ("numeric", Pipeline([
                ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                ("scale", StandardScaler()),
            ]), numeric),
            ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical),
        ]
    )


def result_model(numeric: list[str]) -> Pipeline:
    return Pipeline([
        ("prepare", preprocessing(numeric, ["league"])),
        ("model", LogisticRegression(C=0.25, max_iter=3000, class_weight="balanced")),
    ])


def poisson_model(numeric: list[str]) -> Pipeline:
    return Pipeline([
        ("prepare", preprocessing(numeric, ["league"])),
        ("model", PoissonRegressor(alpha=1.0, max_iter=2000)),
    ])


def poisson_result_probabilities(home_rate: np.ndarray, away_rate: np.ndarray,
                                 maximum: int = MINIMUM_SCORE) -> np.ndarray:
    home_rate, away_rate = np.asarray(home_rate), np.asarray(away_rate)
    if home_rate.ndim != 1 or home_rate.shape != away_rate.shape:
        raise ValueError("home and away rates must be equal-length one-dimensional arrays")
    return np.asarray([result_masses(score_matrix(float(h), float(a), maximum))
                       for h, a in zip(home_rate, away_rate)]).reshape(-1, 3)


def calibration_error(actual: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    predicted = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    correct = predicted == actual
    total = len(actual)
    error = 0.0
    for low in np.linspace(0.0, 1.0, bins, endpoint=False):
        mask = (confidence >= low) & (confidence < low + 1.0 / bins)
        if mask.any():
            error += mask.sum() / total * abs(float(correct[mask].mean()) - float(confidence[mask].mean()))
    return error


def score(actual_labels: np.ndarray, probabilities: np.ndarray, home_actual: np.ndarray,
          away_actual: np.ndarray, home_xg: np.ndarray, away_xg: np.ndarray) -> dict[str, float]:
    actual = np.array([CLASS_ORDER.index(label) for label in actual_labels])
    one_hot = np.eye(len(CLASS_ORDER))[actual]
    clipped = np.clip(probabilities, 1e-9, 1.0)
    clipped /= clipped.sum(axis=1, keepdims=True)
    return {
        "log_loss": float(log_loss(actual, clipped, labels=[0, 1, 2])),
        "brier": float(np.mean(np.sum((clipped - one_hot) ** 2, axis=1))),
        "accuracy": float(accuracy_score(actual, clipped.argmax(axis=1))),
        "calibration_error": float(calibration_error(actual, clipped)),
        "home_goals_mae": float(mean_absolute_error(home_actual, home_xg)),
        "away_goals_mae": float(mean_absolute_error(away_actual, away_xg)),
    }


def aggregate(fold_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    keys = [key for key in fold_metrics[0] if isinstance(fold_metrics[0][key], float)]
    return {
        "folds": fold_metrics,
        "mean": {key: float(np.mean([fold[key] for fold in fold_metrics])) for key in keys},
        "std": {key: float(np.std([fold[key] for fold in fold_metrics])) for key in keys},
    }


def probability_bands(actual_labels: np.ndarray, probabilities: np.ndarray) -> list[dict[str, Any]]:
    actual = np.array([CLASS_ORDER.index(label) for label in actual_labels])
    predicted = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    bands = []
    for low, high in ((0.0, 0.45), (0.45, 0.55), (0.55, 0.65), (0.65, 0.75), (0.75, 1.01)):
        mask = (confidence >= low) & (confidence < high)
        if mask.any():
            bands.append({
                "from": low,
                "to": min(high, 1.0),
                "matches": int(mask.sum()),
                "mean_confidence": float(confidence[mask].mean()),
                "accuracy": float((predicted[mask] == actual[mask]).mean()),
            })
    return bands


def evaluate(frame: pd.DataFrame, folds: int, initial_fraction: float) -> dict[str, Any]:
    metadata = {"game_id", "date", "league", "home_team", "away_team", "home_goals", "away_goals", "result"}
    numeric = [column for column in frame.columns if column not in metadata]
    strength_numeric = ["elo_diff"]
    fold_results: dict[str, list[dict[str, Any]]] = {name: [] for name in ("league_prior", "elo_strength", "poisson_goals", "direct_result")}
    out_of_fold: dict[str, list[dict[str, Any]]] = {name: [] for name in fold_results}

    def keep_predictions(name: str, test: pd.DataFrame, probabilities: np.ndarray,
                         home_xg: np.ndarray, away_xg: np.ndarray) -> None:
        for index, (_, row) in enumerate(test.iterrows()):
            out_of_fold[name].append({
                "league": row["league"], "result": row["result"],
                "home_goals": row["home_goals"], "away_goals": row["away_goals"],
                "probabilities": probabilities[index],
                "home_xg": home_xg[index], "away_xg": away_xg[index],
            })

    for number, (train_idx, test_idx) in enumerate(date_folds(frame, folds, initial_fraction), start=1):
        train = frame.iloc[train_idx]
        test = frame.iloc[test_idx]
        y_train = train["result"].to_numpy()
        y_test = test["result"].to_numpy()
        common = {
            "fold": number,
            "train_through": str(train["date"].max().date()),
            "test_from": str(test["date"].min().date()),
            "test_through": str(test["date"].max().date()),
            "train_matches": int(len(train)),
            "test_matches": int(len(test)),
        }

        prior_prob, prior_home, prior_away = prior_predictions(train, test)
        fold_results["league_prior"].append(common | score(y_test, prior_prob, test["home_goals"], test["away_goals"], prior_home, prior_away))
        keep_predictions("league_prior", test, prior_prob, prior_home, prior_away)

        strength = result_model(strength_numeric).fit(train, y_train)
        strength_prob = aligned_probabilities(strength, test)
        fold_results["elo_strength"].append(common | score(y_test, strength_prob, test["home_goals"], test["away_goals"], prior_home, prior_away))
        keep_predictions("elo_strength", test, strength_prob, prior_home, prior_away)

        home_model = poisson_model(numeric).fit(train, train["home_goals"])
        away_model = poisson_model(numeric).fit(train, train["away_goals"])
        home_rate = np.clip(home_model.predict(test), 0.05, 6.0)
        away_rate = np.clip(away_model.predict(test), 0.05, 6.0)
        poisson_prob = poisson_result_probabilities(home_rate, away_rate)
        fold_results["poisson_goals"].append(common | score(y_test, poisson_prob, test["home_goals"], test["away_goals"], home_rate, away_rate))
        keep_predictions("poisson_goals", test, poisson_prob, home_rate, away_rate)

        direct = result_model(numeric).fit(train, y_train)
        direct_prob = aligned_probabilities(direct, test)
        fold_results["direct_result"].append(common | score(y_test, direct_prob, test["home_goals"], test["away_goals"], prior_home, prior_away))
        keep_predictions("direct_result", test, direct_prob, prior_home, prior_away)
        print(f"Completed fold {number}: train={len(train)} test={len(test)} through={common['test_through']}")
    summaries = {name: aggregate(values) for name, values in fold_results.items()}
    for name, rows in out_of_fold.items():
        labels = np.asarray([row["result"] for row in rows])
        probabilities = np.asarray([row["probabilities"] for row in rows])
        summaries[name]["probability_bands"] = probability_bands(labels, probabilities)
        summaries[name]["by_league"] = {}
        for league in TOP_FIVE:
            subset = [row for row in rows if row["league"] == league]
            if not subset:
                continue
            summaries[name]["by_league"][league] = score(
                np.asarray([row["result"] for row in subset]),
                np.asarray([row["probabilities"] for row in subset]),
                np.asarray([row["home_goals"] for row in subset]),
                np.asarray([row["away_goals"] for row in subset]),
                np.asarray([row["home_xg"] for row in subset]),
                np.asarray([row["away_xg"] for row in subset]),
            ) | {"matches": len(subset)}
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2526")
    parser.add_argument("--feature-schema-version", type=int, default=1)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--initial-fraction", type=float, default=0.50)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--register", action="store_true", help="Register a preliminary training run; never promotes it")
    args = parser.parse_args()
    if not 0.25 <= args.initial_fraction <= 0.80:
        raise ValueError("--initial-fraction must be between 0.25 and 0.80")

    db = db_client()
    frame = load_matches(db, args.season, args.feature_schema_version)
    add_pre_match_elo(frame)
    folds = date_folds(frame, args.folds, args.initial_fraction)
    if len(folds) < 2:
        raise RuntimeError("insufficient unique dates for walk-forward evaluation")
    print(f"Loaded {len(frame)} matches across {frame['league'].nunique()} leagues and {frame['date'].nunique()} dates")
    metrics = evaluate(frame, args.folds, args.initial_fraction)
    winner = min(metrics, key=lambda name: metrics[name]["mean"]["log_loss"])
    prior_loss = metrics["league_prior"]["mean"]["log_loss"]
    winner_loss = metrics[winner]["mean"]["log_loss"]
    report = {
        "report_schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "season": args.season,
        "feature_schema_version": args.feature_schema_version,
        "dataset": {
            "matches": int(len(frame)),
            "leagues": sorted(frame["league"].unique()),
            "first_match_date": str(frame["date"].min().date()),
            "last_match_date": str(frame["date"].max().date()),
            "cold_start_matches": int((frame["source_match_count"] == 0).sum()),
        },
        "validation": {
            "method": "grouped-date rolling-origin walk-forward",
            "fold_count": len(folds),
            "initial_train_fraction": args.initial_fraction,
            "random_split": False,
        },
        "models": metrics,
        "best_by_log_loss": winner,
        "best_log_loss_improvement_over_prior": float(prior_loss - winner_loss),
        "promotion_decision": "training_only_one_season",
        "notes": "Do not promote until at least one earlier season supplies a genuine out-of-season test.",
    }
    output_dir = args.output_dir or Path(__file__).resolve().parents[1] / "artifacts" / "model_reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"match_baselines_{args.season}_{stamp}.json"
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    output_path.write_text(serialized, encoding="utf-8")
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    print(f"Best model: {winner}; log loss={winner_loss:.4f}; prior={prior_loss:.4f}")
    print(f"Report: {output_path} sha256={digest}")

    if args.register:
        model_version = f"preliminary-{args.season}-{stamp.lower()}"
        row = {
            "model_key": "domestic_match_baseline",
            "model_version": model_version,
            "status": "training",
            "algorithm": winner,
            "feature_schema_version": args.feature_schema_version,
            "trained_through": report["dataset"]["last_match_date"],
            "hyperparameters": {
                "folds": args.folds,
                "initial_train_fraction": args.initial_fraction,
                "class_order": list(CLASS_ORDER),
                "one_season_only": True,
            },
            "metrics": {
                "all_models": {name: value["mean"] for name, value in metrics.items()},
                "best_by_log_loss": winner,
                "improvement_over_prior": report["best_log_loss_improvement_over_prior"],
                "report_sha256": digest,
            },
            "notes": report["notes"],
        }
        result = db.table("ml_model_runs").insert(row).execute().data or []
        if len(result) != 1:
            raise RuntimeError("model registry insert did not return exactly one row")
        print(f"Registered training-only model run id={result[0]['id']} version={model_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
