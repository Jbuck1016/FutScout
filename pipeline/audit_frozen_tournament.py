#!/usr/bin/env python3
"""Validate fixture completeness, source identity, and real cutoff provenance."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import frozen_slate_contract as contract
import model_artifact


def audit(tournament_path: Path) -> dict:
    tournament = json.loads(tournament_path.read_text(encoding="utf-8"))
    as_of = contract.instant(tournament["as_of"])
    through = contract.instant(tournament["evaluation_through"])
    manifest_path = Path(tournament["fixture_manifest"])
    manifest = contract.load_manifest(manifest_path, tournament["season"], as_of, strict_capture=True)
    bundle_path = Path(tournament["feature_input_bundle"])
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    from freeze_shadow_tournament import canonical_digest  # import without running the CLI
    checks = {}
    checks["thursday_cutoff"] = as_of.weekday() == 3
    checks["manifest_immutable"] = (
        contract.sha256(manifest_path) == tournament["fixture_manifest_sha256"]
    )
    checks["bundle_immutable"] = (
        canonical_digest(bundle) == tournament["feature_input_bundle_sha256"]
    )
    checks["bundle_identity"] = (
        bundle["season"] == tournament["season"]
        and contract.instant(bundle["as_of"]) == as_of
        and bundle["fixture_manifest_sha256"] == tournament["fixture_manifest_sha256"]
        and bundle["source_provenance"]["source_rows_sha256"] == tournament["source_rows_sha256"]
    )
    checks["bundle_captured_at_cutoff"] = (
        as_of <= contract.instant(bundle["captured_at"]) <= as_of + contract.MAX_FREEZE_DELAY
    )
    last_match = bundle["source_provenance"].get("latest_eligible_match_kickoff")
    checks["no_future_match_inputs"] = not last_match or contract.instant(last_match) <= as_of
    horizon_rows = [row for row in bundle["feature_rows"]
                    if as_of < contract.instant(row["date"]) <= through]
    paths = {"primary": Path(tournament["primary"])} | {
        name: Path(path) for name, path in tournament["challengers"].items()
    }
    scores = {}
    snapshot_identities = set()
    for name, path in paths.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        snapshot_identities.add((payload["as_of"], payload["evaluation_through"], payload["season"],
                                 payload["feature_input_bundle_sha256"], payload["fixture_manifest_sha256"]))
        created = contract.instant(payload["generated_at"])
        artifact_path = Path(payload["artifact"])
        checks[f"{name}_created_at_cutoff"] = as_of <= created <= as_of + contract.MAX_FREEZE_DELAY
        checks[f"{name}_artifact_precedes_cutoff"] = payload["trained_through"] < as_of.date().isoformat()
        checks[f"{name}_artifact_immutable"] = (
            contract.sha256(artifact_path) == payload.get("artifact_sha256")
        )
        artifact = model_artifact.load_artifact(artifact_path)
        columns = list(artifact["numeric_columns"])
        missing = {
            column: sum(row.get(column) is None for row in horizon_rows)
            for column in columns
            if any(row.get(column) is None for row in horizon_rows)
        }
        checks[f"{name}_feature_availability_reconciles"] = (
            bundle.get("feature_availability", {}).get(name) == {
                "fixtures": len(horizon_rows), "feature_count": len(columns),
                "missing_values_by_feature": missing,
                "fixtures_with_any_missing_input": sum(
                    any(row.get(column) is None for column in columns)
                    for row in horizon_rows
                ),
            }
        )
        checks[f"{name}_same_input_provenance"] = (
            payload.get("source_rows_sha256") == tournament["source_rows_sha256"]
        )
        scores[name] = contract.validate_week(manifest, payload["predictions"], as_of, through)
        checks[f"{name}_complete_provider_week"] = scores[name]["passed"]
    checks["all_snapshots_same_cutoff_and_inputs"] = len(snapshot_identities) == 1
    checks["five_model_contract"] = set(paths) == {
        "primary", "compact_control", "compact_xt_5", "box_sequences_5",
        "territory_elo_interactions",
    }
    return {
        "audited_at": datetime.now(UTC).isoformat(),
        "tournament": str(tournament_path.resolve()),
        "as_of": as_of.isoformat(),
        "checks": checks,
        "feature_availability": bundle.get("feature_availability", {}),
        "provider_week": scores,
        "passed": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tournament", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.tournament)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Frozen tournament audit: {'PASS' if report['passed'] else 'BLOCK'}")
    for name, passed in report["checks"].items():
        if not passed:
            print(f"BLOCK {name}")
    print(f"Report: {args.output}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
