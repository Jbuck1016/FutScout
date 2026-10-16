"""Offline arithmetic checks for the Premier control-vs-primary diagnosis."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diagnose_premier_model_gap as diagnosis  # noqa: E402


def main() -> None:
    frame = pd.DataFrame({
        "date": pd.to_datetime(["2025-01-01", "2025-01-01", "2025-01-08"]),
        "outcome": ["home_win", "away_win", "home_win"],
        "primary_loss": [0.4, 2.0, 0.6],
        "control_loss": [0.5, 1.8, 0.5],
    })
    frame["delta_loss"] = frame.control_loss - frame.primary_loss
    grouped = diagnosis.grouped_contributions(frame, "outcome")
    contributions = sum(value["additive_contribution_to_overall_mean"] for value in grouped.values())
    assert np.isclose(contributions, frame.delta_loss.mean())
    interval = diagnosis.weekly_block_interval(frame, draws=100)
    assert interval["calendar_week_blocks"] == 2
    assert len(interval["ci_95"]) == 2
    print("Premier gap diagnostic decomposition checks passed")


if __name__ == "__main__":
    main()
