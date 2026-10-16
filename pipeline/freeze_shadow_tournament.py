#!/usr/bin/env python3
"""Freeze one complete Thursday slate and four unregistered same-input challengers.

All models receive one materialized pre-match feature frame. Nothing here
registers, promotes, persists, or publishes a challenger in Supabase.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

import frozen_slate_contract as contract
import generate_match_predictions as generator
import model_artifact
import train_match_baselines as baseline


ROOT = Path(__file__).resolve().parents[1]
CHALLENGERS = (
    "compact_control", "compact_xt_5", "box_sequences_5", "territory_elo_interactions",
)


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    if path.exists():
        raise RuntimeError(f"refusing to overwrite an immutable research output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    if temporary.exists():
        raise RuntimeError(f"prior interrupted write needs attention: {temporary}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def checked_artifact(path: Path, as_of: datetime) -> dict:
    artifact = model_artifact.load_artifact(path)
    if int(artifact["feature_schema_version"]) != 2:
        raise RuntimeError(f"challenger is not schema-v2: {path}")
    if pd.Timestamp(artifact["trained_through"]).date() >= as_of.date():
        raise RuntimeError(f"artifact contains training on/after the forecast cutoff: {path}")
    return artifact


def fetch_inputs(db, season: str, as_of: datetime, manifest: dict) -> tuple[list, list, list, dict]:
    leagues = list(baseline.TOP_FIVE)
    matches = baseline.fetch_pages(
        db.table("matches")
        .select("game_id,season,league,date,kickoff_at,home_team,away_team,home_score,away_score")
        .in_("league", leagues).order("date").order("game_id")
    )
    current = [row for row in matches if str(row["season"]) == season]
    provider_ids = {str(row["game_id"]) for row in manifest["fixtures"]
                    if row.get('provider_status') not in {'POSTPONED','SUSPENDED','CANCELLED'}}
    provider_ids.update(str(row["game_id"]) for row in manifest.get("completed_fixtures", []))
    fixtures = generator.select_fixtures(current, as_of, provider_ids)
    observations = baseline.fetch_pages(
        db.table("ml_team_match_observations")
        .select(",".join(("game_id", "team", "season", "league", "match_date") +
                         model_artifact.observation_metrics(2)))
        .eq("observation_schema_version", 2)
        .in_("league", leagues).order("match_date").order("game_id")
    )
    eligible_matches = [
        row for row in matches
        if row.get("home_score") is not None and row.get("away_score") is not None
        and contract.fixture_instant(row) <= as_of
    ]
    eligible_ids = {str(row["game_id"]) for row in eligible_matches}
    eligible_observations = [row for row in observations if str(row["game_id"]) in eligible_ids]
    current_completed = {
        str(row["game_id"]) for row in eligible_matches if str(row["season"]) == season
    }
    current_observed = {
        str(row["game_id"]) for row in eligible_observations if str(row["season"]) == season
    }
    if current_completed - current_observed:
        raise RuntimeError(
            f"{len(current_completed - current_observed)} completed current-season games lack observations"
        )
    gaps = generator.provider_completion_gaps(
        list(manifest.get("completed_fixtures", [])), current, current_observed, as_of
    )
    if gaps:
        raise RuntimeError(f"provider/current-form mismatch: {'; '.join(gaps[:4])}")
    provenance = {
        "eligible_match_count": len(eligible_matches),
        "eligible_observation_count": len(eligible_observations),
        "latest_eligible_match_kickoff": max(
            (contract.fixture_instant(row).isoformat() for row in eligible_matches), default=None
        ),
        "source_rows_sha256": canonical_digest({
            "matches": eligible_matches, "observations": eligible_observations,
        }),
    }
    return fixtures, eligible_observations, eligible_matches, provenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2627")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--fixtures-file", type=Path, required=True)
    parser.add_argument("--primary-artifact", type=Path, required=True)
    parser.add_argument("--research-artifacts", type=Path, default=ROOT / "artifacts/model_reports/shadow_research_challenger_artifacts.json")
    parser.add_argument("--prediction-output", type=Path, required=True)
    parser.add_argument("--research-dir", type=Path, default=ROOT / "artifacts/predictions/research")
    args = parser.parse_args()
    as_of = contract.instant(args.as_of)
    contract.require_real_cutoff(as_of)
    through = as_of + timedelta(days=7)
    manifest = contract.load_manifest(args.fixtures_file, args.season, as_of, strict_capture=True)
    manifest_hash = contract.sha256(args.fixtures_file)
    primary = checked_artifact(args.primary_artifact, as_of)
    reviewed = json.loads(args.research_artifacts.read_text(encoding="utf-8"))
    if reviewed.get("purpose") != "private_research_only_unregistered_not_active":
        raise RuntimeError("research artifact manifest has not passed the private-scope contract")
    artifact_paths = {name: Path(reviewed["artifacts"][name]["path"]) for name in CHALLENGERS}
    for name, path in artifact_paths.items():
        if contract.sha256(path) != reviewed["artifacts"][name]["sha256"]:
            raise RuntimeError(f"reviewed challenger artifact changed after training: {name}")
    challenger_models = {name: checked_artifact(path, as_of) for name, path in artifact_paths.items()}
    stamp = as_of.strftime("%Y%m%dT%H%M%SZ")
    base = f"{args.season}_{stamp}"
    bundle_path = args.research_dir / f"{base}_feature_inputs.json"
    tournament_path = args.research_dir / f"{base}_tournament.json"
    challenger_paths = {name: args.research_dir / f"{base}_{name}.json" for name in CHALLENGERS}
    for path in (args.prediction_output, bundle_path, tournament_path, *challenger_paths.values()):
        if path.exists():
            raise RuntimeError(f"immutable snapshot already exists; refusing recomputation: {path}")
    db = baseline.db_client()
    fixtures, observations, matches, provenance = fetch_inputs(db, args.season, as_of, manifest)
    if not fixtures:
        raise RuntimeError("canonical database contains no future five-league fixtures")
    frame = model_artifact.build_fixture_frame(fixtures, observations, matches, as_of, 2)
    feature_rows = json.loads(frame.to_json(orient="records", date_format="iso", double_precision=15))
    contract.require_real_cutoff(as_of)
    # Score the exact stored feature values, not a slightly different in-memory frame.
    frame = pd.DataFrame(feature_rows)
    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    horizon = frame[(frame.date > pd.Timestamp(as_of)) &
                    (frame.date <= pd.Timestamp(through))].copy()
    availability = {}
    for name, artifact in {"primary": primary, **challenger_models}.items():
        columns = list(artifact["numeric_columns"])
        absent = sorted(set(columns) - set(horizon.columns))
        if absent:
            raise RuntimeError(f"{name} feature frame is missing columns: {absent}")
        missing = {
            column: int(horizon[column].isna().sum())
            for column in columns if horizon[column].isna().any()
        }
        availability[name] = {
            "fixtures": len(horizon), "feature_count": len(columns),
            "missing_values_by_feature": missing,
            "fixtures_with_any_missing_input": int(horizon[columns].isna().any(axis=1).sum()),
        }
    bundle = {
        "schema_version": 1,
        "as_of": as_of.isoformat(),
        "season": args.season,
        "captured_at": datetime.now(UTC).isoformat(),
        "fixture_manifest_sha256": manifest_hash,
        "source_provenance": provenance,
        "feature_availability": availability,
        "feature_rows": feature_rows,
    }
    primary_rows = model_artifact.predict_feature_frame(primary, frame)
    completeness = contract.validate_week(manifest, primary_rows, as_of, through)
    if not completeness["passed"] or completeness["expected"] == 0:
        raise RuntimeError(f"frozen provider-week coverage failed: {completeness}")
    bundle_hash = canonical_digest(bundle)
    now = datetime.now(UTC).isoformat()
    common = {
        "as_of": as_of.isoformat(),
        "evaluation_through": through.isoformat(),
        "forecast_kind": "thursday_frozen",
        "season": args.season,
        "generated_at": now,
        "fixture_manifest": str(args.fixtures_file.resolve()),
        "fixture_manifest_sha256": manifest_hash,
        "feature_input_bundle": str(bundle_path.resolve()),
        "feature_input_bundle_sha256": bundle_hash,
        "source_rows_sha256": provenance["source_rows_sha256"],
    }
    primary_payload = common | {
        "artifact": str(args.primary_artifact.resolve()),
        "artifact_sha256": contract.sha256(args.primary_artifact),
        "model_version": args.primary_artifact.stem,
        "feature_schema_version": 2,
        "algorithm": primary["algorithm"],
        "trained_through": primary["trained_through"],
        "feature_count": len(primary["numeric_columns"]),
        "predictions": primary_rows,
    }
    tournament = {
        "schema_version": 1,
        "scope": "private_research_only_no_challenger_registration_or_promotion",
        **common,
        "primary": str(args.prediction_output.resolve()),
        "challengers": {name: str(path.resolve()) for name, path in challenger_paths.items()},
        "provider_week_coverage": completeness,
    }
    challenger_payloads = {}
    for name, artifact in challenger_models.items():
        rows = model_artifact.predict_feature_frame(artifact, horizon, include_scorelines=False)
        check = contract.validate_week(manifest, rows, as_of, through)
        if not check["passed"] or check["expected"] != completeness["expected"]:
            raise RuntimeError(f"{name} does not predict the identical complete slate: {check}")
        challenger_payloads[name] = common | {
            "research_only": True,
            "artifact": str(artifact_paths[name].resolve()),
            "artifact_sha256": contract.sha256(artifact_paths[name]),
            "model_version": artifact_paths[name].stem,
            "feature_schema_version": 2,
            "algorithm": artifact["algorithm"],
            "trained_through": artifact["trained_through"],
            "feature_count": len(artifact["numeric_columns"]),
            "predictions": rows,
        }
    contract.require_real_cutoff(as_of)
    atomic_json(bundle_path, bundle)
    atomic_json(args.prediction_output, primary_payload)
    for name, path in challenger_paths.items():
        atomic_json(path, challenger_payloads[name])
    atomic_json(tournament_path, tournament)
    print(f"Frozen {completeness['expected']} same-cutoff fixtures across five models")
    print(f"Research-only tournament: {tournament_path}")
    print("No Supabase model lifecycle or challenger predictions were written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
