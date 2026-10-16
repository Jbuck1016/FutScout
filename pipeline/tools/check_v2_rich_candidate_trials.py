"""Check that the archived rich-feature trial actually exercised its contracts."""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evaluate_v2_feature_candidates as trial


def main() -> None:
    sample = pd.DataFrame({
        "date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-08"]),
        "result": ["H", "D", "A"],
    })
    probabilities = np.asarray([[0.6, 0.2, 0.2], [0.2, 0.6, 0.2], [0.2, 0.2, 0.6]])
    paired = trial.week_blocked_delta(sample, probabilities, probabilities)
    assert paired["delta_log_loss"] == 0
    assert paired["week_blocks"] == 2
    assert paired["week_block_bootstrap_ci_95"] == [0, 0]
    root = Path(__file__).resolve().parents[2]
    report = json.loads((root / "artifacts" / "model_reports" /
                         "v2_feature_candidate_audit.json").read_text(encoding="utf-8"))
    assert report["promotion_decision"] == "research_only_no_lifecycle_change"
    assert "expected_threat" not in report["skipped_candidates"]
    assert "xt_difference_5" not in report["skipped_candidates"]
    for fold in report["folds"].values():
        for name in ("territory_threat_no_shots", "tactical_compact_no_shots"):
            columns = fold[name]["columns"]
            assert columns and not any("shots_" in column for column in columns)
        assert fold["xt_difference_5"]["column_count"] == 19
        assert fold["xt_difference_5"]["paired_vs_control"]["week_blocks"] > 20
    print("V2 rich candidate coverage and no-shots checks passed")


if __name__ == "__main__":
    main()
