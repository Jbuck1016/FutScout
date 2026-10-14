"""Offline, exploratory chronological soccer forecast comparisons.

No credentials, provider calls, database writes, registration or publication.
The already reused 2024/25 and 2025/26 seasons are development evaluations.
This script never reads 2026/27 outcomes or calls them an untouched test.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import pickle
import platform

import numpy as np
import pandas as pd
import scipy
from scipy.optimize import minimize_scalar
from scipy.stats import poisson
import sklearn
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline

import train_match_baselines as baseline
import evaluate_multiseason_model as multi
from score_probabilities import score_matrix, result_masses, SCORE_CONTRACT_VERSION

ADVANCED_METRICS = ("ppda", "progressive_passes", "defensive_height")
CANDIDATES = ("baseline29", "compact17", "raw_advanced35", "adjusted_advanced35",
              "decay365_baseline29", "dc_baseline29")
SEASONS = ("2324", "2425", "2526")
SEED = 20261014


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_snapshot(path: Path) -> pd.DataFrame:
    manifest = json.loads(path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    if sha256(path) != manifest["sha256"]:
        raise ValueError("snapshot SHA256 differs from its saved manifest")
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = json.loads(line)
        if raw["season"] not in SEASONS:
            raise ValueError("snapshot contains an unapproved/future season")
        row = dict(game_id=str(raw["game_id"]), date=raw["match_date"],
                   league=raw["league"], season=raw["season"], home_team=raw["team"],
                   away_team=raw["opponent"], home_goals=raw["goals_for"],
                   away_goals=raw["goals_against"],
                   result={"W": "H", "D": "D", "L": "A"}[raw["result"]],
                   source_match_count=raw["source_match_count"])
        baseline.flatten_numeric(raw["features"], "", row)
        records.append(row)
    frame = pd.DataFrame(records)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values(["date", "game_id"]).reset_index(drop=True)
    if len(frame) != manifest["row_count"] or frame.game_id.duplicated().any():
        raise ValueError("snapshot cardinality/identity violation")
    if (frame[["home_goals", "away_goals"]] < 0).any().any():
        raise ValueError("invalid outcomes")
    baseline.add_pre_match_elo(frame)
    return frame


def add_schedule_context(frame: pd.DataFrame) -> pd.DataFrame:
    """Last-five opponents' ratings *before those games*, never final ratings.

    All rows on a date are emitted before updating history. Only same-league
    matches in this snapshot count, matching the rolling metric population.
    """
    result = frame.copy()
    history = defaultdict(list)
    values = {}
    for _, day in result.sort_values(["date", "game_id"]).groupby("date", sort=True):
        for index, row in day.iterrows():
            values[index] = {}
            for side, team in (("team", row.home_team), ("opponent", row.away_team)):
                prior = history[(row.league, team)][-5:]
                values[index][f"{side}.schedule_elo_5"] = np.mean([p[0] for p in prior]) if prior else np.nan
                values[index][f"{side}.schedule_home_5"] = np.mean([p[1] for p in prior]) if prior else np.nan
                values[index][f"{side}.schedule_count_5"] = len(prior)
        for _, row in day.iterrows():
            history[(row.league, row.home_team)].append((row.elo_away, 1))
            history[(row.league, row.away_team)].append((row.elo_home, 0))
    return result.join(pd.DataFrame.from_dict(values, orient="index"))


def adjustment_context(frame: pd.DataFrame, side: str) -> pd.DataFrame:
    return pd.DataFrame({
        "league": frame.league,
        "own_strength": frame["elo_home" if side == "team" else "elo_away"] - 1500,
        "schedule_strength": frame[f"{side}.schedule_elo_5"] - 1500,
        "home_share": frame[f"{side}.schedule_home_5"],
        "shots": frame[f"{side}.shots_5"],
        "shots_against": frame[f"{side}.shots_against_5"],
    })


def metric_value(frame: pd.DataFrame, side: str, metric: str) -> pd.Series:
    value = pd.to_numeric(frame[f"{side}.{metric}_5"], errors="raise")
    if ((value.dropna() < 0).any() or not np.isfinite(value.dropna()).all()):
        raise ValueError(f"invalid {metric} values")
    if metric == "defensive_height":
        if (value.dropna() > 100).any():
            raise ValueError("defensive height exceeds coordinate scale")
        return value
    return np.log1p(value)


def fit_adjusters(train: pd.DataFrame) -> dict:
    context = pd.concat([adjustment_context(train, side) for side in ("team", "opponent")], ignore_index=True)
    adjusters = {}
    for metric in ADVANCED_METRICS:
        y = pd.concat([metric_value(train, side, metric) for side in ("team", "opponent")], ignore_index=True)
        valid = y.notna()
        model = Pipeline([
            ("prepare", baseline.preprocessing([c for c in context if c != "league"], ["league"])),
            ("model", Ridge(alpha=100.0)),
        ]).fit(context.loc[valid], y.loc[valid])
        adjusters[metric] = model
    return adjusters


def apply_adjusters(frame: pd.DataFrame, adjusters: dict) -> pd.DataFrame:
    result = frame.copy()
    for side in ("team", "opponent"):
        context = adjustment_context(frame, side)
        for metric, model in adjusters.items():
            result[f"{side}.adjusted_{metric}_5"] = metric_value(frame, side, metric) - model.predict(context)
    return result


def columns_for(candidate: str, baseline_columns: list[str]) -> list[str]:
    if candidate == "compact17":
        return [c for c in baseline_columns if "field_tilt" not in c and "box_entries" not in c]
    if candidate in ("raw_advanced35", "adjusted_advanced35"):
        prefix = "adjusted_" if candidate.startswith("adjusted") else ""
        return baseline_columns + [f"{side}.{prefix}{metric}_5"
                                   for side in ("team", "opponent") for metric in ADVANCED_METRICS]
    return baseline_columns


def fit_rates(train: pd.DataFrame, columns: list[str], decay: bool = False) -> tuple:
    prepared = multi.normalize_model_features(train)
    weights = np.ones(len(train))
    if decay:
        weights = np.exp(-np.log(2) * (train.date.max() - train.date).dt.days.to_numpy() / 365.0)
        weights /= weights.mean()
    return tuple(baseline.poisson_model(columns).fit(prepared, prepared[y], model__sample_weight=weights)
                 for y in ("home_goals", "away_goals"))


def rate_predictions(models: tuple, frame: pd.DataFrame) -> tuple:
    prepared = multi.normalize_model_features(frame)
    return tuple(np.clip(model.predict(prepared), 0.05, 6.0) for model in models)


def fit_dc(train: pd.DataFrame, columns: list[str]) -> tuple[float, dict]:
    dates = train.date.drop_duplicates().sort_values()
    cutoff = dates.iloc[int(len(dates) * 0.8)]
    fit, calibration = train[train.date < cutoff], train[train.date >= cutoff]
    h, a = rate_predictions(fit_rates(fit, columns), calibration)
    hg, ag = calibration.home_goals.to_numpy(), calibration.away_goals.to_numpy()

    def objective(rho):
        tau = np.ones(len(calibration))
        tau[(hg == 0) & (ag == 0)] = (1 - h * a * rho)[(hg == 0) & (ag == 0)]
        tau[(hg == 0) & (ag == 1)] = (1 + h * rho)[(hg == 0) & (ag == 1)]
        tau[(hg == 1) & (ag == 0)] = (1 + a * rho)[(hg == 1) & (ag == 0)]
        tau[(hg == 1) & (ag == 1)] = 1 - rho
        return float(-np.log(tau).mean())

    # Bounds valid for every production rate in [0.05, 6], fixed before evaluation.
    fit_rho = minimize_scalar(objective, bounds=(-0.15, 0.025), method="bounded")
    if not fit_rho.success:
        raise ValueError("DC calibration failed")
    return float(fit_rho.x), {"start": str(cutoff.date()), "matches": len(calibration),
                             "objective": "low-score joint likelihood on inner chronological calibration"}


def fit_candidate(name: str, train: pd.DataFrame, columns: list[str]) -> dict:
    adjusters = fit_adjusters(train) if name.startswith("adjusted") else {}
    fitted_frame = apply_adjusters(train, adjusters) if adjusters else train
    rho, calibration = fit_dc(train, columns) if name.startswith("dc_") else (0.0, None)
    models = fit_rates(fitted_frame, columns, name.startswith("decay365"))
    return {"candidate": name, "columns": columns, "models": models, "adjusters": adjusters,
            "rho": rho, "calibration": calibration, "training_matches": len(train),
            "trained_through": str(train.date.max().date()), "status": "offline_research_only",
            "score_contract": SCORE_CONTRACT_VERSION}


def predict_candidate(artifact: dict, frame: pd.DataFrame) -> tuple:
    prepared = apply_adjusters(frame, artifact["adjusters"]) if artifact["adjusters"] else frame
    h, a = rate_predictions(artifact["models"], prepared)
    matrices = [score_matrix(float(x), float(y), rho=artifact["rho"]) for x, y in zip(h, a)]
    return np.array([result_masses(m) for m in matrices]), h, a, matrices


def reliability(frame: pd.DataFrame, probabilities: np.ndarray) -> list:
    rows = []
    for index, label in enumerate(baseline.CLASS_ORDER):
        actual = frame.result.eq(label).to_numpy()
        for low in np.arange(0.0, 1.0, 0.1):
            mask = (probabilities[:, index] >= low) & (probabilities[:, index] < low + 0.1 + (1e-12 if low > .89 else 0))
            n = int(mask.sum())
            if not n:
                continue
            observed = float(actual[mask].mean())
            # Wilson interval is descriptive; dependence-aware inference is below.
            z = 1.96
            center = (observed + z*z/(2*n))/(1+z*z/n)
            half = z*np.sqrt(observed*(1-observed)/n+z*z/(4*n*n))/(1+z*z/n)
            rows.append({"class": label, "from": float(low), "to": float(low + .1), "n": n,
                         "predicted": float(probabilities[mask, index].mean()), "observed": observed,
                         "wilson95": [float(center-half), float(center+half)]})
    return rows


def evaluate_predictions(frame: pd.DataFrame, probabilities, h, a, matrices) -> dict:
    score = baseline.score(frame.result.to_numpy(), probabilities, frame.home_goals, frame.away_goals, h, a)
    actual = np.array([baseline.CLASS_ORDER.index(x) for x in frame.result])
    joint = [m[int(hg), int(ag)] if hg < len(m) and ag < len(m) else 1e-15
             for m, hg, ag in zip(matrices, frame.home_goals, frame.away_goals)]
    score["scoreline_log_loss"] = float(-np.log(np.clip(joint, 1e-15, 1)).mean())
    score["ranked_probability_score"] = float(np.mean(np.sum(
        (np.cumsum(probabilities, axis=1)[:, :2] - np.cumsum(np.eye(3)[actual], axis=1)[:, :2])**2, axis=1) / 2))
    score["reliability"] = reliability(frame, probabilities)
    score["goals_intervals90"] = {}
    for side, rates, outcomes in (("home", h, frame.home_goals), ("away", a, frame.away_goals)):
        lo, hi = poisson.ppf(.05, rates), poisson.ppf(.95, rates)
        score["goals_intervals90"][side] = {"coverage": float(np.mean((outcomes >= lo) & (outcomes <= hi))),
                                                    "mean_width": float(np.mean(hi-lo)),
                                                    "note": "discrete central intervals; coverage can exceed 90%"}
    score["by_league"] = {}
    for league in sorted(frame.league.unique()):
        mask = frame.league.eq(league).to_numpy()
        score["by_league"][league] = baseline.score(frame.loc[mask, "result"].to_numpy(), probabilities[mask],
            frame.loc[mask, "home_goals"], frame.loc[mask, "away_goals"], h[mask], a[mask]) | {"matches": int(mask.sum())}
    return score


def paired_interval(frame: pd.DataFrame, candidate: np.ndarray, control: np.ndarray) -> dict:
    actual = np.array([baseline.CLASS_ORDER.index(x) for x in frame.result])
    delta = -np.log(candidate[np.arange(len(actual)), actual]) + np.log(control[np.arange(len(actual)), actual])
    weekly = pd.DataFrame({"delta": delta, "week": frame.date.dt.to_period("W").astype(str).to_numpy()})
    grouped = weekly.groupby("week").delta.agg(["sum", "count"]).to_numpy()
    rng = np.random.default_rng(SEED)
    # Circular moving blocks of four observed weeks, preserving short-range dependence.
    samples = []
    for _ in range(2000):
        starts = rng.integers(len(grouped), size=int(np.ceil(len(grouped)/4)))
        selected = ((starts[:, None] + np.arange(4)) % len(grouped)).ravel()[:len(grouped)]
        samples.append(grouped[selected, 0].sum()/grouped[selected, 1].sum())
    return {"delta_log_loss": float(delta.mean()), "ci95": np.quantile(samples, [.025, .975]).tolist(),
            "method": "paired circular moving blocks of 4 observed calendar weeks, 2000 replicates",
            "weeks": len(grouped), "seed": SEED,
            "limitation": "exploratory, not multiplicity-adjusted; only two previously reused seasons"}


def run(source: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    snapshot = source / "artifacts/training_snapshots/top_five_2324_2526_v1.jsonl"
    model_metadata = source / "artifacts/models/v2-field-tilt-box-entries-poisson-2324-2425-2526-20260914t205131z.json"
    columns = json.loads(model_metadata.read_text(encoding="utf-8"))["numeric_columns"]
    protocol = {
        "created_at": datetime.now(UTC).isoformat(), "candidates": list(CANDIDATES),
        "snapshot_sha256": sha256(snapshot), "selection_metric": "paired result log loss",
        "historical_status": "exploratory development; both evaluation seasons already reused",
        "future_holdout": {"start": "2026-10-15T00:00:00Z", "minimum_matches": 500,
                           "minimum_frozen_weeks": 12, "status": "reserved, not collected or scored here",
                           "rule": "freeze same eligible fixtures/models/cutoff before kickoff; no promotion before paired review"},
        "promotion": "none", "market": "no odds read or used; closing odds are not decision-time comparators",
        "advanced": "training-only residualization of lagged PPDA/progressive passes/defensive height against prior opponent Elo, venue, own Elo and shooting",
        "time_decay": "fixed 365-day half-life; no tuning", "dc": "training-only last-20%-dates calibration",
    }
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2)+"\n", encoding="utf-8")
    frame = add_schedule_context(load_snapshot(snapshot))
    # Verify saved data-quality evidence for precisely these historical seasons.
    gates = {}
    for season in SEASONS:
        path = source / f"artifacts/data_quality/model_data_quality_{season}.json"
        gate = json.loads(path.read_text(encoding="utf-8"))
        if not gate.get("release_ready") or gate.get("feature_schema_version") != 1:
            raise ValueError(f"saved historical quality gate failed: {season}")
        gates[season] = {"path": str(path), "sha256": sha256(path), "release_ready": True}
    report = {"protocol": protocol, "data": {"matches": len(frame), "by_season": frame.season.value_counts().to_dict(),
              "first_date": str(frame.date.min().date()), "last_date": str(frame.date.max().date()),
              "snapshot": str(snapshot), "gates": gates}, "folds": {}, "models": {},
              "environment": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                              "scipy": scipy.__version__, "sklearn": sklearn.__version__}}
    report["advanced_coverage"] = {f"{side}.{metric}_5": {
        season: {"rows": int(frame.season.eq(season).sum()),
                 "nonmissing": int(frame.loc[frame.season.eq(season), f"{side}.{metric}_5"].notna().sum())}
        for season in SEASONS} for side in ("team", "opponent") for metric in ADVANCED_METRICS}
    all_predictions = []
    for evaluation_season in ("2425", "2526"):
        train = frame[frame.season < evaluation_season].copy()
        test = frame[frame.season == evaluation_season].copy()
        if train.date.max() >= test.date.min():
            raise ValueError("nonchronological fold")
        fold = {"train_matches": len(train), "test_matches": len(test),
                "train_through": str(train.date.max().date()), "test_from": str(test.date.min().date()),
                "test_through": str(test.date.max().date()), "candidates": {}}
        control = None
        for name in CANDIDATES:
            artifact = fit_candidate(name, train, columns_for(name, columns))
            prob, h, a, matrices = predict_candidate(artifact, test)
            metrics = evaluate_predictions(test, prob, h, a, matrices)
            if name == "baseline29":
                control = prob
                grid = np.arange(13)
                legacy = np.array([result_masses(np.outer(poisson.pmf(grid, x), poisson.pmf(grid, y)) /
                                    (poisson.cdf(12, x)*poisson.cdf(12, y))) for x, y in zip(h, a)])
                metrics["legacy_grid12_log_loss"] = baseline.score(test.result.to_numpy(), legacy, test.home_goals, test.away_goals, h, a)["log_loss"]
                metrics["maximum_probability_change_vs_grid12"] = float(np.max(abs(prob-legacy)))
            metrics["paired_vs_baseline"] = paired_interval(test, prob, control)
            metrics["columns"] = artifact["columns"]
            metrics["rho"] = artifact["rho"]
            metrics["dc_calibration"] = artifact["calibration"]
            fold["candidates"][name] = metrics
            for i, (_, row) in enumerate(test.iterrows()):
                all_predictions.append({"candidate": name, "fold": evaluation_season, "game_id": row.game_id,
                    "date": str(row.date.date()), "league": row.league, "result": row.result,
                    "home_goals": row.home_goals, "away_goals": row.away_goals,
                    "p_home": prob[i, 0], "p_draw": prob[i, 1], "p_away": prob[i, 2],
                    "home_rate": h[i], "away_rate": a[i], "evidence_type": "historical_reconstruction"})
            print(f"{evaluation_season} {name}: log_loss={metrics['log_loss']:.8f} delta={metrics['paired_vs_baseline']['delta_log_loss']:+.8f}", flush=True)
        report["folds"][evaluation_season] = fold
    # Full-history research artifacts are not written into the live model registry.
    for name in CANDIDATES:
        artifact = fit_candidate(name, frame, columns_for(name, columns))
        artifact["source_sha256"] = sha256(snapshot)
        path = output / f"{name}.pkl"
        path.write_bytes(pickle.dumps(artifact, protocol=5))
        report["models"][name] = {"path": str(path), "sha256": sha256(path), "training_matches": len(frame),
                                 "columns": artifact["columns"], "rho": artifact["rho"], "status": artifact["status"]}
    pd.DataFrame(all_predictions).to_csv(output / "historical_predictions.csv", index=False)
    report["decision"] = "retain_existing_model; exploratory candidates require prospective evidence and rights review"
    report["report_generated_at"] = datetime.now(UTC).isoformat()
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.source.resolve(), args.output.resolve())
