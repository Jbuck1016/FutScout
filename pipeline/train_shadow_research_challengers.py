#!/usr/bin/env python3
"""Train local, unregistered shadow challengers from the reviewed v2 contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

import evaluate_v2_feature_candidates as candidates
import model_artifact
import test_rich_calibration_interactions as interactions
import train_match_baselines as baseline


ROOT = Path(__file__).resolve().parents[1]
RUN_NAME = "research-2324-2425-2526-20260922"
CONTRACTS = {
    "compact_control": ("current_compact_control", []),
    "compact_xt_5": ("xt_difference_5", []),
    "box_sequences_5": ("box_entry_sequences_5", []),
    "territory_elo_interactions": (
        "field_tilt_box_entries",
        ["interaction.elo_x_tilt_5", "interaction.elo_x_boxes_5"],
    ),
}


def main() -> int:
    candidates.coverage_reports(ROOT)
    audit_path = ROOT / "artifacts" / "model_reports" / "v2_feature_candidate_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    db = baseline.db_client()
    parts = []
    for season in ("2324", "2425", "2526"):
        frame = baseline.load_matches(db, season, 2)
        frame["season"] = season
        parts.append(frame)
    frame = pd.concat(parts, ignore_index=True).sort_values(["date", "game_id"]).reset_index(drop=True)
    if len(frame) != 5255 or frame.game_id.duplicated().any():
        raise RuntimeError("three-season training population changed; review before retraining")
    baseline.add_pre_match_elo(frame)
    frame = interactions.interaction_frame(frame)
    output = {
        "created_at": datetime.now(UTC).isoformat(),
        "purpose": "private_research_only_unregistered_not_active",
        "training_matches": len(frame),
        "training_seasons": ["2324", "2425", "2526"],
        "source_contract": str(audit_path),
        "artifacts": {},
    }
    reviewed = audit["folds"]["2324_2425_to_2526"]
    for name, (candidate, extra) in CONTRACTS.items():
        columns = reviewed[candidate]["columns"] + extra
        path = ROOT / "artifacts" / "models" / f"{name}-{RUN_NAME}.pkl"
        if path.exists():
            artifact = model_artifact.load_artifact(path)
            if artifact["numeric_columns"] != columns or artifact["training_match_count"] != len(frame):
                raise RuntimeError(f"existing research artifact has a different contract: {path}")
            digest = model_artifact.hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            artifact = model_artifact.train_poisson(frame, 2, columns, name)
            digest = model_artifact.save_artifact(artifact, path)
            path.with_suffix(".json").write_text(
                json.dumps(model_artifact.metadata_json(artifact, digest), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        output["artifacts"][name] = {
            "path": str(path), "sha256": digest, "feature_count": len(columns),
            "trained_through": artifact["trained_through"],
        }
        print(f"{name}: {len(columns)} inputs; {path}")
    report_path = ROOT / "artifacts" / "model_reports" / "shadow_research_challenger_artifacts.json"
    report_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Unregistered research artifact manifest: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
