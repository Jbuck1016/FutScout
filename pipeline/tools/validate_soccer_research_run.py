"""Independently reconcile saved research metrics, identities and model reloads."""
from pathlib import Path
import argparse
import hashlib
import json
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research_soccer_forecasts as research
import evaluate_multiseason_model as multi


def validate(source: Path, output: Path) -> dict:
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    predictions = pd.read_csv(output / "historical_predictions.csv", dtype={"game_id": str, "fold": str})
    assert not predictions.duplicated(["candidate", "fold", "game_id"]).any()
    assert set(predictions.evidence_type) == {"historical_reconstruction"}
    snapshot = source / "artifacts/training_snapshots/top_five_2324_2526_v1.jsonl"
    frame = research.add_schedule_context(research.load_snapshot(snapshot))
    reference = json.loads((source / "artifacts/model_reports/v2_field_tilt_box_entries_validation.json").read_text(encoding="utf-8"))
    validations = {}
    for fold in ("2425", "2526"):
        control_ids = set(predictions.loc[(predictions.fold == fold) & (predictions.candidate == "baseline29"), "game_id"])
        expected_ids = set(frame.loc[frame.season == fold, "game_id"])
        assert control_ids == expected_ids
        for name in research.CANDIDATES:
            rows = predictions[(predictions.fold == fold) & (predictions.candidate == name)]
            assert set(rows.game_id) == expected_ids
            assert len(rows) == 1752
            p = rows[["p_home", "p_draw", "p_away"]].to_numpy()
            assert np.isfinite(p).all() and (p >= 0).all()
            np.testing.assert_allclose(p.sum(axis=1), 1, atol=1e-14)
            actual = np.array([{"H": 0, "D": 1, "A": 2}[value] for value in rows.result])
            loss = float(-np.log(p[np.arange(len(rows)), actual]).mean())
            brier = float(np.mean(np.sum((p-np.eye(3)[actual])**2, axis=1)))
            metrics = report["folds"][fold]["candidates"][name]
            assert abs(loss - metrics["log_loss"]) < 1e-12
            assert abs(brier - metrics["brier"]) < 1e-12
        reference_fold = "2324_to_2425" if fold == "2425" else "2324_2425_to_2526"
        expected = reference["folds"][reference_fold]["candidate"]["log_loss"]
        reproduced = report["folds"][fold]["candidates"]["baseline29"]["legacy_grid12_log_loss"]
        assert abs(expected-reproduced) < 1e-12
        validations[fold] = {"population_matches": len(expected_ids), "legacy_reference_log_loss": expected,
                             "reproduced_legacy_log_loss": reproduced, "absolute_difference": abs(expected-reproduced)}
    # Check existing trusted model digest before deserialization.
    name = "v2-field-tilt-box-entries-poisson-2324-2425-2526-20260914t205131z"
    old_path = source / f"artifacts/models/{name}.pkl"
    old_meta = json.loads(old_path.with_suffix('.json').read_text(encoding='utf-8'))
    assert research.sha256(old_path) == old_meta['artifact_sha256']
    old = pickle.loads(old_path.read_bytes())
    sample = frame.iloc[::37]
    reloads = {}
    for candidate, meta in report["models"].items():
        path = output / f"{candidate}.pkl"
        assert research.sha256(path) == meta["sha256"]
        artifact = pickle.loads(path.read_bytes())
        p, h, a, _ = research.predict_candidate(artifact, sample)
        assert np.isfinite(p).all()
        np.testing.assert_allclose(p.sum(axis=1), 1, atol=1e-14)
        reloads[candidate] = {"matches": len(sample), "sha256": meta["sha256"], "passed": True}
        if candidate == 'baseline29':
            original_h = np.clip(old['home_model'].predict(multi.normalize_model_features(sample)), .05, 6)
            original_a = np.clip(old['away_model'].predict(multi.normalize_model_features(sample)), .05, 6)
            delta = float(max(np.max(abs(original_h-h)), np.max(abs(original_a-a))))
            assert delta < 1e-12
            reloads[candidate]['maximum_goal_rate_difference_from_existing_model'] = delta
    code_paths = ["pipeline/research_soccer_forecasts.py", "pipeline/score_probabilities.py",
                  "pipeline/train_match_baselines.py", "pipeline/evaluate_multiseason_model.py",
                  "pipeline/model_artifact.py", "pipeline/simulate_league_table.py",
                  "pipeline/generate_match_predictions.py",
                  "pipeline/soccer_metric_contracts.py"]
    root = Path(__file__).resolve().parents[2]
    checks = {"status": "passed", "prediction_rows": len(predictions), "folds": validations,
              "model_reloads": reloads, "source_snapshot_sha256": research.sha256(snapshot),
              "code_sha256": {path: research.sha256(root/path) for path in code_paths},
              "files_sha256": {path.name: research.sha256(path) for path in output.iterdir()
                               if path.is_file() and path.name != "validation.json"}}
    (output / "validation.json").write_text(json.dumps(checks, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in checks.items() if k in ("status", "prediction_rows", "folds", "model_reloads")}, indent=2))
    return checks


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    validate(args.source, args.output)
