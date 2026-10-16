#!/usr/bin/env python3
"""Validate a generated pre-match signal-audit artifact."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


EXPECTED_KEYS = {
    "xt_difference", "open_play_xt_difference", "npxg_difference", "npxg_per_shot",
    "field_tilt_pct", "final_third_touch_difference", "penalty_area_touch_difference",
    "box_entries_pass", "zone14_passes", "final_third_passes", "progressive_passes",
    "shot_ending_sequences", "progressive_sequences", "box_entry_sequences", "ppda",
    "defensive_height",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.artifact.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["matches"]
    assert payload["method"]["cutoff_rule"].startswith("Only matches dated before")
    for match in payload["matches"]:
        signals = match["signals"]
        assert {signal["key"] for signal in signals} == EXPECTED_KEYS
        assert sum(match["summary"].values()) == len(signals)
        for signal in signals:
            assert signal["lean"] in {"home", "away", "balanced", "unavailable"}
            assert signal["primary_window"] in {3, 5}
            for window_text, values in signal["windows"].items():
                window = int(window_text)
                assert window in {3, 5, 10}
                assert 0 <= values["home_matches"] <= window
                assert 0 <= values["away_matches"] <= window
                for key in ("home", "away", "standardized_home_edge"):
                    value = values[key]
                    assert value is None or math.isfinite(float(value))
            for key in ("home_percentile", "away_percentile"):
                value = signal[key]
                assert value is None or 0 <= float(value) <= 100
    print(f"PASS: {len(payload['matches'])} match signal boards validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
