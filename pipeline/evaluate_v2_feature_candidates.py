#!/usr/bin/env python3
"""Evaluate schema-v2 feature families on chronological season holdouts.

This command is read-only with respect to Supabase and writes a local report.
It refuses to evaluate a feature family unless every requested season's v2
coverage report marks that family eligible.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import analyze_match_feature_families as families
import evaluate_multiseason_model as multi
import train_match_baselines as baseline


SEASONS = ["2324", "2425", "2526"]
CANDIDATES = {
    "current_compact_control": (),
    "field_tilt_box_entries": ("territory",),
    "attacking_touch_volume": ("territory",),
    "territory_differentials": ("territory",),
    "compact_territory_v2": ("territory",),
    "territory_v2": ("territory",),
    "expected_threat": ("expected_threat",),
    "xt_difference_5": ("expected_threat",),
    "xt_created_conceded_5": ("expected_threat",),
    "possession_sequences": ("possession_sequences",),
    "box_entry_sequences_5": ("possession_sequences",),
    "territory_plus_threat": ("territory", "expected_threat"),
    "territory_threat_sequences": (
        "territory", "expected_threat", "possession_sequences",
    ),
    "chance_quality": ("chance_quality",),
    "npxg_difference_5": ("chance_quality",),
    "field_tilt_xt_compact": ("territory", "expected_threat"),
    "rich_attack": (
        "territory", "expected_threat", "possession_sequences",
        "chance_quality", "progression",
    ),
    "rich_attack_context": (
        "territory", "expected_threat", "possession_sequences",
        "chance_quality", "progression", "possession",
        "pressing_defense", "availability_context",
    ),
    "territory_threat_no_shots": ("territory", "expected_threat"),
    "tactical_no_shots": (
        "territory", "expected_threat", "progression", "pressing_defense",
    ),
    "quality_no_shots": (
        "territory", "expected_threat", "chance_quality",
    ),
    "tactical_compact_no_shots": ("territory", "expected_threat"),
    "balanced_rich_no_shots": (
        "territory", "expected_threat", "chance_quality",
        "possession_sequences", "progression", "pressing_defense",
    ),
}

NO_SHOTS_CANDIDATES = {
    "territory_threat_no_shots", "tactical_no_shots",
    "quality_no_shots", "balanced_rich_no_shots", "tactical_compact_no_shots",
}
QUALITY_FAMILY_NAMES = {"expected_threat": "threat"}

TERRITORY_TOKEN_FILTERS = {
    "field_tilt_box_entries": (".field_tilt_pct_", ".box_entries_pass_"),
    "attacking_touch_volume": (".final_third_touches_", ".penalty_area_touches_"),
    "territory_differentials": (
        ".final_third_touch_difference_",
        ".penalty_area_touch_difference_",
    ),
    "compact_territory_v2": (
        ".field_tilt_pct_",
        ".box_entries_pass_",
        ".final_third_touch_difference_",
        ".penalty_area_touch_difference_",
    ),
    "xt_difference_5": (".xt_difference_5",),
    "xt_created_conceded_5": (".xt_created_5", ".xt_conceded_5"),
    "box_entry_sequences_5": (".box_entry_sequences_5",),
    "npxg_difference_5": (".npxg_difference_5",),
    "field_tilt_xt_compact": (
        ".field_tilt_pct_5", ".box_entries_pass_5", ".xt_difference_5",
    ),
    "tactical_compact_no_shots": (
        ".field_tilt_pct_5", ".box_entries_pass_5", ".xt_difference_5",
    ),
}


def coverage_reports(root: Path) -> dict[str, dict]:
    reports = {}
    for season in SEASONS:
        path = root / "artifacts" / "data_quality" / f"model_data_quality_v2_{season}.json"
        if not path.is_file():
            raise RuntimeError(f"missing v2 coverage gate for {season}: {path}")
        report = json.loads(path.read_text(encoding="utf-8"))
        if not report.get("release_ready_for_core_v2_experiments"):
            raise RuntimeError(f"{season} is not release-ready for core v2 experiments")
        reports[season] = report
    return reports


def week_blocked_delta(
    test: pd.DataFrame,
    probabilities: np.ndarray,
    control_probabilities: np.ndarray,
) -> dict[str, object]:
    """Paired log-loss uncertainty with whole calendar weeks resampled."""
    labels = np.asarray([baseline.CLASS_ORDER.index(value) for value in test["result"]])
    indices = np.arange(len(test))
    per_match = -np.log(np.clip(probabilities[indices, labels], 1e-12, 1.0)) + np.log(
        np.clip(control_probabilities[indices, labels], 1e-12, 1.0)
    )
    week = test["date"].dt.to_period("W-SUN").astype(str).to_numpy()
    blocks = sorted(set(week))
    sums = np.asarray([per_match[week == block].sum() for block in blocks])
    counts = np.asarray([(week == block).sum() for block in blocks])
    rng = np.random.default_rng(20260922)
    draws = rng.integers(0, len(blocks), size=(2000, len(blocks)))
    sampled = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    low, high = np.quantile(sampled, [0.025, 0.975])
    return {
        "delta_log_loss": float(per_match.mean()),
        "week_blocks": len(blocks),
        "week_block_bootstrap_ci_95": [float(low), float(high)],
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    coverage = coverage_reports(root)
    eligible_families = set.intersection(*(
        set(report["eligible_optional_families"]) for report in coverage.values()
    ))
    db = baseline.db_client()
    parts = []
    for season in SEASONS:
        frame = baseline.load_matches(db, season, 2)
        frame["season"] = season
        parts.append(frame)
    combined = pd.concat(parts, ignore_index=True).sort_values(["date", "game_id"]).reset_index(drop=True)
    baseline.add_pre_match_elo(combined)
    numeric = multi.select_features(combined, "all")
    current = multi.select_features(combined, "core_shooting")
    grouped = families.family_columns(numeric)
    folds = [
        ("2324_to_2425", combined[combined.season.eq("2324")], combined[combined.season.eq("2425")]),
        (
            "2324_2425_to_2526",
            combined[combined.season.isin(["2324", "2425"])],
            combined[combined.season.eq("2526")],
        ),
    ]
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "feature_schema_version": 2,
        "purpose": "Private chronological research; candidate ranking is not a promotion decision",
        "promotion_decision": "research_only_no_lifecycle_change",
        "evidence_limit": (
            "Two out-of-season holdouts and many compared candidates cannot establish "
            "a durable improvement from a tiny log-loss difference. Review paired "
            "uncertainty, per-league results, and real frozen-slate scores before promotion."
        ),
        "eligible_families_all_seasons": sorted(eligible_families),
        "available_numeric_features": len(numeric),
        "family_columns": grouped,
        "folds": {},
        "skipped_candidates": {},
    }
    control_by_fold: dict[str, np.ndarray] = {}
    for candidate, requested in CANDIDATES.items():
        gated = set(requested) & {"territory", "expected_threat", "possession_sequences", "chance_quality"}
        missing = sorted(
            family for family in gated
            if QUALITY_FAMILY_NAMES.get(family, family) not in eligible_families
        )
        if missing:
            report["skipped_candidates"][candidate] = {
                "reason": "feature family failed coverage gate",
                "families": missing,
            }
            continue
        requested_columns = {
            column for family in requested for column in grouped.get(family, [])
        }
        if candidate in TERRITORY_TOKEN_FILTERS:
            tokens = TERRITORY_TOKEN_FILTERS[candidate]
            requested_columns = {
                column for column in requested_columns if any(token in column for token in tokens)
            }
        foundation = multi.select_features(combined, "core") if candidate in NO_SHOTS_CANDIDATES else current
        columns = sorted(set(foundation) | requested_columns)
        if candidate in NO_SHOTS_CANDIDATES and any(
            column in grouped.get("shooting", []) for column in columns
        ):
            raise RuntimeError(f"{candidate} unexpectedly includes a shooting feature")
        for fold_name, train, test in folds:
            metrics, probabilities, *_ = multi.model_metrics(train, test, columns)
            if candidate == "current_compact_control":
                control_by_fold[fold_name] = probabilities
            report["folds"].setdefault(fold_name, {})[candidate] = {
                "families": list(requested),
                "columns": columns,
                "column_count": len(columns),
                "log_loss": metrics["log_loss"],
                "brier": metrics["brier"],
                "calibration_error": metrics["calibration_error"],
                "home_goals_mae": metrics["home_goals_mae"],
                "away_goals_mae": metrics["away_goals_mae"],
                "by_league": metrics["by_league"],
                "paired_vs_control": week_blocked_delta(
                    test, probabilities, control_by_fold[fold_name],
                ),
            }
            print(f"{fold_name} {candidate}: {metrics['log_loss']:.4f} ({len(columns)} fields)")

    evaluated = sorted(set.intersection(*(
        set(fold) for fold in report["folds"].values()
    )))
    summary = {}
    for candidate in evaluated:
        values = [report["folds"][fold_name][candidate]["log_loss"] for fold_name, *_ in folds]
        control_values = [
            report["folds"][fold_name]["current_compact_control"]["log_loss"]
            for fold_name, *_ in folds
        ]
        summary[candidate] = {
            "mean_log_loss": sum(values) / len(values),
            "beats_control_both_holdouts": all(
                value < control for value, control in zip(values, control_values)
            ) if candidate != "current_compact_control" else True,
        }
    report["summary"] = summary
    report["ranking"] = sorted(summary, key=lambda name: summary[name]["mean_log_loss"])
    report["decision"] = (
        "v2_challenger_available"
        if any(value["beats_control_both_holdouts"] for key, value in summary.items()
               if key != "current_compact_control")
        else "retain_control_and_continue_v2_experiments"
    )
    output = root / "artifacts" / "model_reports" / "v2_feature_candidate_audit.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Decision: {report['decision']}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
