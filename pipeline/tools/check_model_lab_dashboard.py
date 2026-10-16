#!/usr/bin/env python3
"""Static and payload checks for the read-only model laboratory."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
page = (ROOT / "dashboard" / "model-lab.html").read_text(encoding="utf-8")
builder = (ROOT / "pipeline" / "build_model_lab_dashboard.py").read_text(encoding="utf-8")
history = (ROOT / "pipeline" / "score_prediction_history.py").read_text(encoding="utf-8")
for label in ("overview", "validation", "legitimacy", "research", "features", "matches", "monitoring", "guide"):
    assert f'id="{label}"' in page
assert "gate.js" in page and "model-lab-data.js" in page
assert "can_promote\": False" in builder and "can_activate\": False" in builder
assert "SUPABASE_SERVICE_KEY" not in page
assert "Coefficient explorer" in page and "Forecast dissection" in page
assert "Model tournament" in page and "textSize" in page
assert "weights are not a league table" in page
assert "Out-of-sample family reliance" in page and "Historical table backtests" in page
assert "Cross-season feature gate" in page and "What team strength currently means" in page
assert "Hybrid versus tactical" in page and "A five-minute route through Model Lab" in page
assert "Original tournament exclusions" in page and "eligible for trial" in page
assert "Mixed-date research bundle" in page and "not a live feed" in page
assert "newest_audit_path" in builder
assert "parse_utc_datetime(row[\"date\"])" in builder
assert "MIN_COMPLETE_FROZEN_WEEKENDS = 3" in history

payload_path = ROOT / "dashboard" / "model-lab-data.js"
if payload_path.is_file():
    text = payload_path.read_text(encoding="utf-8")
    payload = json.loads(text.removeprefix("window.MODEL_LAB_DATA=").removesuffix(";\n"))
    assert payload["model"]["feature_schema_version"] == 2
    assert payload["model"]["feature_count"] == 29
    assert payload["guardrails"] == {
        "can_activate": False,
        "can_promote": False,
        "note": "The lab visualizes immutable artifacts. Lifecycle changes remain separate reviewed commands.",
        "read_only": True,
    }
    assert payload["validation_folds"] and payload["candidate_ranking"]
    tournament = payload["model_tournament"]
    assert tournament["winner"] == "shooting_territory"
    assert len(tournament["summary"]) >= 8
    assert "train_2324_2425_test_2526" in tournament["folds"]
    assert tournament["unavailable_families"]["expected_threat"]
    assert tournament["created_at"]
    assert payload["drift"]["checked_at"]
    legitimacy = payload["legitimacy"]
    assert legitimacy["confidence"]["shooting_vs_territory_2526"]
    assert legitimacy["family_permutation"]["rows"]
    assert legitimacy["table_backtests"]["summary"]
    stability = payload["feature_stability"]
    assert "territory" in stability["gate"]["passed_families"]
    assert "progression" in stability["gate"]["research_only_families"]
    assert stability["elo_dependency"]["decision"] == "retain_as_benchmark_and_test_residual_tactical_lift"
    research = payload["challenger_research"]
    eligible = {
        row["family"] for row in research["coverage"]["families"]
        if row["historical_ready"] and row["current_ready"]
    }
    assert set(research["coverage"]["decision"]["trainable_now"]) == eligible
    assert research["league_coverage"]["repair_queue"] == []
    assert research["coverage"]["created_at"] > tournament["created_at"]
    assert len(research["league_coverage"]["groups"]) >= 20
    assert research["scoring_readiness"]["ready"] is True
print("Model lab dashboard checks passed")
