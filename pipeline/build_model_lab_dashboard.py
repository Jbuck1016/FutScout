#!/usr/bin/env python3
"""Build a key-free, read-only model investigation payload from reviewed artifacts."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import model_artifact


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "artifacts" / "models" / "v2-field-tilt-box-entries-poisson-2324-2425-2526-20260914t205131z.pkl"


def load_json(path: Path, required: bool = True) -> dict[str, Any]:
    if not path.is_file():
        if required:
            raise RuntimeError(f"missing model-lab source: {path}")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def newest_audit_path(base: Path) -> Path:
    """Prefer the newest dated coverage audit over a stale legacy alias."""
    candidates = [path for path in (base, *base.parent.glob(f"{base.stem}_20*.json")) if path.is_file()]
    if not candidates:
        return base
    return max(candidates, key=lambda path: (load_json(path).get("created_at", ""), str(path)))


def parse_utc_datetime(value: Any) -> datetime:
    """Normalize provider timestamps before comparing frozen forecast windows."""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def feature_family(name: str) -> str:
    if name.startswith("context."):
        return "schedule"
    if name.startswith("elo_"):
        return "team strength"
    if "field_tilt" in name or "box_entries" in name:
        return "territory"
    if "shots_against" in name:
        return "shot suppression"
    if "shots" in name:
        return "shot creation"
    return "other"


def coefficients(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for side in ("home", "away"):
        pipeline = artifact[f"{side}_model"]
        names = pipeline.named_steps["prepare"].get_feature_names_out()
        values = pipeline.named_steps["model"].coef_
        for raw_name, value in zip(names, values, strict=True):
            name = str(raw_name).split("__", 1)[-1]
            row = rows.setdefault(name, {"feature": name, "family": feature_family(name)})
            row[f"{side}_goal_coefficient"] = float(value)
    for row in rows.values():
        row["magnitude"] = max(
            abs(float(row.get("home_goal_coefficient", 0))),
            abs(float(row.get("away_goal_coefficient", 0))),
        )
    return sorted(rows.values(), key=lambda row: row["magnitude"], reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--validation-report", type=Path, default=ROOT / "artifacts" / "model_reports" / "v2_field_tilt_box_entries_validation.json")
    parser.add_argument("--candidate-report", type=Path, default=ROOT / "artifacts" / "model_reports" / "v2_feature_candidate_audit.json")
    parser.add_argument("--tournament-report", type=Path, default=ROOT / "artifacts" / "model_reports" / "model_philosophy_tournament.json")
    parser.add_argument("--legitimacy-report", type=Path, default=ROOT / "artifacts" / "model_reports" / "model_legitimacy_suite.json")
    parser.add_argument("--stability-report", type=Path, default=ROOT / "artifacts" / "model_reports" / "cross_season_feature_stability.json")
    parser.add_argument("--drift-report", type=Path, default=ROOT / "artifacts" / "data_quality" / "model_feature_drift_2627.json")
    parser.add_argument("--shadow-report", type=Path, default=ROOT / "artifacts" / "model_reports" / "shadow_history_2627.json")
    parser.add_argument("--predictions-file", type=Path, required=True)
    parser.add_argument("--challenger-predictions-file", type=Path)
    parser.add_argument("--comparison-report", type=Path, default=ROOT / "artifacts" / "model_reports" / "live_challenger_comparison.json")
    parser.add_argument("--nonlinear-report", type=Path, default=ROOT / "artifacts" / "model_reports" / "nonlinear_challenger_tournament.json")
    parser.add_argument("--coverage-report", type=Path, default=newest_audit_path(ROOT / "artifacts" / "data_quality" / "rich_feature_coverage_decision.json"))
    parser.add_argument("--league-coverage-report", type=Path, default=newest_audit_path(ROOT / "artifacts" / "data_quality" / "rich_feature_coverage_by_league.json"))
    parser.add_argument("--table-uncertainty-report", type=Path, default=ROOT / "artifacts" / "model_reports" / "table_uncertainty_calibration.json")
    parser.add_argument("--scoring-readiness-report", type=Path, default=ROOT / "artifacts" / "model_reports" / "shadow_scoring_readiness.json")
    parser.add_argument("--operations-freshness-report", type=Path, default=ROOT / "artifacts" / "data_quality" / "model_operations_freshness.json")
    parser.add_argument("--output", type=Path, default=ROOT / "dashboard" / "model-lab-data.js")
    args = parser.parse_args()

    artifact = model_artifact.load_artifact(args.artifact)
    sidecar = load_json(args.artifact.with_suffix(".json"))
    validation = load_json(args.validation_report)
    candidates = load_json(args.candidate_report)
    tournament = load_json(args.tournament_report)
    legitimacy = load_json(args.legitimacy_report)
    stability = load_json(args.stability_report)
    bookmaker_path = ROOT / "artifacts" / "model_reports" / "bookmaker_benchmark.json"
    if bookmaker_path.is_file():
        legitimacy["external_and_live"]["bookmaker_benchmark"] = {
            "status": "available",
            "path": str(bookmaker_path),
            **load_json(bookmaker_path),
        }
    schema_catalog = load_json(ROOT / "pipeline" / "model_feature_schema_v2.json")
    drift = load_json(args.drift_report)
    shadow = load_json(args.shadow_report, required=False)
    prediction_payload = load_json(args.predictions_file)
    challenger_predictions = (
        load_json(args.challenger_predictions_file)
        if args.challenger_predictions_file else {}
    )
    comparison = (
        load_json(args.comparison_report, required=False)
        if args.challenger_predictions_file else {}
    )
    nonlinear = load_json(args.nonlinear_report, required=False)
    coverage = load_json(args.coverage_report, required=False)
    league_coverage = load_json(args.league_coverage_report, required=False)
    table_uncertainty = load_json(args.table_uncertainty_report, required=False)
    scoring_readiness = load_json(args.scoring_readiness_report, required=False)
    operations_freshness = load_json(args.operations_freshness_report, required=False)
    prediction_model = prediction_payload.get("model_version")
    if prediction_model and prediction_model != sidecar["model_version"]:
        raise RuntimeError(
            f"prediction model {prediction_model} does not match lab artifact {sidecar['model_version']}"
        )

    folds = []
    for name, fold in validation["folds"].items():
        folds.append({
            "name": name,
            "candidate": {key: fold["candidate"][key] for key in ("log_loss", "brier", "calibration_error", "home_goals_mae", "away_goals_mae")},
            "control": {key: fold["control"][key] for key in ("log_loss", "brier", "calibration_error", "home_goals_mae", "away_goals_mae")},
            "by_league": fold["candidate"]["by_league"],
            "log_loss_improvement": fold["log_loss_improvement"],
        })

    candidate_rows = []
    for rank, name in enumerate(candidates["ranking"], start=1):
        summary = candidates["summary"][name]
        candidate_rows.append({"rank": rank, "name": name, **summary})

    drift_rows = []
    for name, metric in drift.get("features", {}).items():
        drift_rows.append({"feature": name, **metric})
    drift_rows.sort(key=lambda row: (0 if row["severity"] == "severe" else 1 if row["severity"] == "moderate" else 2, row["feature"]))

    as_of = parse_utc_datetime(prediction_payload["as_of"])
    evaluation_through = parse_utc_datetime(
        prediction_payload.get("evaluation_through") or (as_of + timedelta(days=7)).isoformat()
    )
    predictions = []
    for row in prediction_payload.get("predictions", []):
        if not row.get("explanation"):
            continue
        kickoff = parse_utc_datetime(row["date"])
        if not as_of < kickoff <= evaluation_through:
            continue
        predictions.append({key: row[key] for key in (
            "game_id", "date", "league", "home_team", "away_team",
            "home_expected_goals", "away_expected_goals", "home_win_probability",
            "draw_probability", "away_win_probability", "explanation",
        )})

    payload = {
        "generated_from": str(args.predictions_file),
        "as_of": prediction_payload["as_of"],
        "model": {
            "model_version": artifact["model_key"] + " · " + str(sidecar["model_version"]),
            "display_version": sidecar["model_version"],
            "status": "shadow",
            "algorithm": artifact["algorithm"],
            "feature_schema_version": artifact["feature_schema_version"],
            "training_seasons": artifact["training_seasons"],
            "training_match_count": artifact["training_match_count"],
            "trained_through": artifact["trained_through"],
            "feature_count": len(artifact["numeric_columns"]),
            "decision": validation["shadow_review_decision"],
            "decision_basis": validation["decision_basis"],
            "mean_log_loss": sidecar["holdout_mean_log_loss"],
            "control_mean_log_loss": sidecar["control_mean_log_loss"],
        },
        "features": [
            {"feature": name, "family": feature_family(name)}
            for name in artifact["numeric_columns"]
        ],
        "coefficients": coefficients(artifact),
        "validation_folds": folds,
        "candidate_ranking": candidate_rows,
        "model_tournament": {
            "created_at": tournament.get("created_at"),
            "purpose": tournament["purpose"],
            "winner": tournament["winner"],
            "interpretation_rule": tournament["interpretation_rule"],
            "summary": tournament["summary"],
            "unavailable_families": tournament.get("unavailable_families", {}),
            "folds": {
                name: {
                    "train_seasons": fold["train_seasons"],
                    "test_season": fold["test_season"],
                    "models": {
                        model_name: {
                            key: model[key]
                            for key in (
                                "label", "idea", "families", "column_count",
                                "matches", "log_loss", "brier", "accuracy",
                                "calibration_error", "home_goals_mae",
                                "away_goals_mae", "by_league",
                            )
                        }
                        for model_name, model in fold["models"].items()
                    },
                }
                for name, fold in tournament["folds"].items()
            },
        },
        "legitimacy": legitimacy,
        "feature_stability": stability,
        "research_queue": {
            "eligible_families": candidates.get("eligible_families_all_seasons", []),
            "blocked_candidates": candidates.get("skipped_candidates", {}),
            "catalog": schema_catalog.get("families", {}),
        },
        "drift": {
            "checked_at": drift.get("checked_at"),
            "decision": drift.get("decision", "unavailable"),
            "sample_ready": drift.get("sample_ready", False),
            "current_matches": drift.get("current_matches", 0),
            "current_matches_by_league": drift.get("current_matches_by_league", {}),
            "features": drift_rows,
        },
        "shadow": shadow or {
            "resolved": 0,
            "pending": 0,
            "overall": {"status": "waiting_for_first_frozen_slate"},
            "by_league": {},
            "sample_gate": {"decision": "collect_more_results", "ready": False},
        },
        "predictions": predictions,
        "challenger_research": {
            "comparison": comparison,
            "nonlinear": nonlinear,
            "coverage": coverage,
            "league_coverage": league_coverage,
            "table_uncertainty": table_uncertainty,
            "scoring_readiness": scoring_readiness,
            "operations_freshness": operations_freshness,
            "challenger_predictions_file": str(args.challenger_predictions_file) if args.challenger_predictions_file else None,
            "challenger_model_version": challenger_predictions.get("model_version"),
        },
        "guardrails": {
            "read_only": True,
            "can_promote": False,
            "can_activate": False,
            "note": "The lab visualizes immutable artifacts. Lifecycle changes remain separate reviewed commands.",
        },
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).replace("<", "\\u003c")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Keep the generated one-line bundle LF-terminated on Windows so Git's
    # whitespace checks do not interpret the carriage return as trailing data.
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(f"window.MODEL_LAB_DATA={encoded};\n")
    print(f"Model lab bundle: predictions={len(predictions)} features={len(payload['features'])} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
