#!/usr/bin/env python3
"""Deterministic checks for the flat-stake value-selection ledger."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_value_bet_ledger as ledger  # noqa: E402


selection = ledger.choose_selection(
    {"home": 0.45, "draw": 0.30, "away": 0.25},
    {"home": 0.50, "draw": 0.23, "away": 0.27},
    {"home": 2.00, "draw": 4.50, "away": 3.70},
    edge_threshold=0.05,
    minimum_books=3,
    bookmaker_count=8,
)
assert selection is not None
assert selection["outcome"] == "draw"
assert abs(selection["probability_edge"] - 0.07) < 1e-12
assert abs(selection["model_expected_return_median"] - 0.35) < 1e-12

assert ledger.choose_selection(
    {"home": 0.45, "draw": 0.30, "away": 0.25},
    {"home": 0.50, "draw": 0.23, "away": 0.27},
    {"home": 2.00, "draw": 4.50, "away": 3.70},
    edge_threshold=0.05,
    minimum_books=3,
    bookmaker_count=2,
) is None

summary = ledger.aggregate([
    {"selection": {
        "won": True, "median_price_profit_units": 3.5,
        "best_price_profit_units": 3.8, "probability_edge": 0.07,
        "model_expected_return_median": 0.35, "closing_probability_value": 0.02,
    }},
    {"selection": {
        "won": False, "median_price_profit_units": -1.0,
        "best_price_profit_units": -1.0, "probability_edge": 0.06,
        "model_expected_return_median": 0.12, "closing_probability_value": -0.01,
    }},
])
assert summary["selections"] == 2
assert summary["wins"] == 1
assert abs(summary["median_price_profit_units"] - 2.5) < 1e-12
assert abs(summary["median_price_roi"] - 1.25) < 1e-12
assert abs(summary["average_closing_probability_value"] - 0.005) < 1e-12

print("Value-bet ledger checks passed")
