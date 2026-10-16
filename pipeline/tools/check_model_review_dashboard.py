#!/usr/bin/env python3
"""Static safety checks for the key-free private model review page."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
page = (ROOT / "dashboard" / "model-review.html").read_text(encoding="utf-8")
builder = (ROOT / "pipeline" / "build_model_review_dashboard.py").read_text(encoding="utf-8")
assert "SUPABASE_SERVICE_KEY" not in page
assert "SHADOW · PRIVATE" in page
assert "Experimental review output" in page
assert "Password-gated review output" not in page
assert "scoreline_distribution" not in builder
assert '"publication_allowed": False' in builder
assert '"review_ready": review_ready' in builder
assert "model-review-data.js" in page
assert "model-review-archive-data.js" in page
assert "model-lab-data.js" in page and 'id="reviewHealth"' in page
assert "Early-season table uncertainty" in page
assert "current points already won plus simulated remaining points" in page
assert "no calibrated team-level interval" in page
assert "LATEST RESEARCH · NOT FROZEN" in page
assert "FROZEN ARCHIVE · NOT UPCOMING" in page
assert "?view=archive" in page
assert "MODEL_REVIEW_ARCHIVE_DATA" in builder
assert "def parse_instant" in builder
assert 'ROOT / "artifacts" / "model-review"' in builder
assert "BLOCKED · STALE INPUT" in page

bundle_path = ROOT / "dashboard" / "model-review-data.js"
if bundle_path.is_file():
    source = bundle_path.read_text(encoding="utf-8")
    bundle = json.loads(source.removeprefix("window.MODEL_REVIEW_DATA=").removesuffix(";\n"))
    teams = [team for league in bundle["simulations"].values() for team in league["teams"]]
    assert teams
    assert all(
        abs(team["expected_points"] - team["current_points"] - team["projected_remaining_points"]) < 0.001
        for team in teams
    )
print("Model review dashboard safety checks passed")
