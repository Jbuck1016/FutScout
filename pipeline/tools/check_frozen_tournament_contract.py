"""Synthetic checks for complete fixture sets and genuine cutoff provenance."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import frozen_slate_contract as contract  # noqa: E402
import freeze_shadow_tournament as freeze  # noqa: E402
import audit_frozen_tournament as tournament_audit  # noqa: E402
import model_artifact  # noqa: E402
import score_shadow_tournament as scoring  # noqa: E402
import sync_future_fixtures as sync  # noqa: E402


def main() -> None:
    # Small but fully accounted provider schedules for this synthetic fixture.
    sync.EXPECTED_LEAGUE_FIXTURES = {league: 1 for league in contract.TOP_FIVE}
    as_of = datetime(2026, 9, 24, 12, tzinfo=UTC)
    through = as_of + timedelta(days=7)
    rows = [
        {
            "game_id": f"g{index}", "league": league,
            "date": "2026-09-25", "kickoff_at": "2026-09-25T19:00:00+00:00",
            "home_team": f"Home {index}", "away_team": f"Away {index}",
        }
        for index, league in enumerate(contract.TOP_FIVE)
    ]
    manifest = {
        "provider": "football-data.org", "season": "2627",
        "generated_at": (as_of + timedelta(minutes=3)).isoformat(),
        "provider_match_counts": dict(sync.EXPECTED_LEAGUE_FIXTURES),
        "fixtures": rows, "completed_fixtures": [], "excluded_fixtures": [],
    }
    with TemporaryDirectory() as directory:
        path = Path(directory) / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        loaded = contract.load_manifest(path, "2627", as_of, strict_capture=True)
        assert len(contract.expected_week(loaded, as_of, through)) == 5
        predicted = [
            {"game_id": row["game_id"], "date": row["kickoff_at"],
             "league": row["league"], "home_team": row["home_team"],
             "away_team": row["away_team"]}
            for row in rows
        ]
        assert contract.validate_week(loaded, predicted, as_of, through)["passed"]
        truncated = dict(manifest, fixtures=rows[:-1])
        path.write_text(json.dumps(truncated), encoding='utf-8')
        try:
            contract.load_manifest(path, '2627', as_of, strict_capture=True)
        except RuntimeError as exc:
            assert 'unique accounted fixtures' in str(exc)
        else:
            raise AssertionError('declared counts concealed a missing league')
        postponed = dict(manifest, fixtures=rows[:-1], excluded_fixtures=[dict(rows[-1],provider_status='POSTPONED')])
        path.write_text(json.dumps(postponed), encoding='utf-8')
        assert contract.load_manifest(path, '2627', as_of, strict_capture=True)
        assert contract.validate_week(postponed,predicted[:-1],as_of,through)['passed']
        rescheduled = dict(manifest, fixtures=[dict(r) for r in rows])
        rescheduled['fixtures'][0]['kickoff_at']='2026-09-26T19:00:00+00:00'
        assert contract.validate_week(rescheduled,predicted,as_of,through)['mismatched_identity']==['g0']
        missing = contract.validate_week(loaded, predicted[:-1], as_of, through)
        assert not missing["passed"] and missing["missing"] == ["g4"]
        duplicate = contract.validate_week(loaded, predicted + predicted[:1], as_of, through)
        assert not duplicate["passed"] and duplicate["duplicate_count"] == 1
        changed = [dict(row) for row in predicted]
        changed[0]["away_team"] = "Other"
        assert contract.validate_week(loaded, changed, as_of, through)["mismatched_identity"] == ["g0"]
        manifest["provider_match_counts"]["ENG-Premier League"] = 0
        path.write_text(json.dumps(manifest), encoding="utf-8")
        try:
            contract.load_manifest(path, "2627", as_of, strict_capture=True)
        except RuntimeError as exc:
            assert "complete five-league schedule" in str(exc)
        else:
            raise AssertionError("empty league schedule passed the gate")
    contract.require_real_cutoff(as_of, as_of + timedelta(minutes=10))
    try:
        contract.require_real_cutoff(as_of, as_of + timedelta(hours=24))
    except RuntimeError as exc:
        assert "within 30 minutes" in str(exc)
    else:
        raise AssertionError("Friday backfill passed as a Thursday freeze")
    actual = {"g0": {"home_score": 2, "away_score": 0}}
    forecast = [{
        "game_id": "g0", "league": contract.TOP_FIVE[0],
        "home_win_probability": 0.6, "draw_probability": 0.25,
        "away_win_probability": 0.15, "home_expected_goals": 1.8,
        "away_expected_goals": 0.8,
    }]
    assert scoring.score_rows(forecast, actual)["matches"] == 1
    assert scoring.score_rows(forecast, {})["status"] == "awaiting_results"
    pl_rows = {
        "primary": {
            "win": {"league": "ENG-Premier League", "home_win_probability": 0.6,
                    "draw_probability": 0.25, "away_win_probability": 0.15},
            "upset": {"league": "ENG-Premier League", "home_win_probability": 0.7,
                      "draw_probability": 0.2, "away_win_probability": 0.1},
            "ordinary": {"league": "ENG-Premier League", "home_win_probability": 0.5,
                         "draw_probability": 0.3, "away_win_probability": 0.2},
        },
        "compact_control": {
            "win": {"league": "ENG-Premier League", "home_win_probability": 0.55,
                    "draw_probability": 0.25, "away_win_probability": 0.2},
            "upset": {"league": "ENG-Premier League", "home_win_probability": 0.6,
                      "draw_probability": 0.2, "away_win_probability": 0.2},
            "ordinary": {"league": "ENG-Premier League", "home_win_probability": 0.45,
                         "draw_probability": 0.3, "away_win_probability": 0.25},
        },
    }
    pl_actual = {"win": {"home_score": 2, "away_score": 0},
                 "upset": {"home_score": 0, "away_score": 1},
                 "ordinary": {"home_score": 1, "away_score": 1}}
    pl_monitor = scoring.premier_home_favorite_monitor(pl_rows, pl_actual)
    assert pl_monitor["premier_league_resolved"] == 3
    assert pl_monitor["strong_home_favorites"]["matches"] == 2
    assert pl_monitor["strong_home_favorites"]["observed_home_win_rate"] == 0.5
    assert pl_monitor["strong_home_favorites"]["observed_away_wins"] == 1
    assert pl_monitor["strong_home_favorites"]["away_upset_log_loss_delta_sum"] < 0
    assert scoring.premier_home_favorite_monitor(
        {"primary": {}, "compact_control": {}}, {}
    )["strong_home_favorites"]["observed_home_win_rate"] is None
    # Full five-model freeze, provenance audit, and cumulative score use one
    # synthetic Thursday; neither provider nor Supabase is contacted.
    with TemporaryDirectory() as directory:
        root = Path(directory)
        history = pd.DataFrame([
            {
                "game_id": str(index), "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=index),
                "season": "test", "league": contract.TOP_FIVE[0],
                "home_team": "A", "away_team": "B",
                "home_goals": index % 4, "away_goals": (index + 1) % 3,
                "result": "H" if index % 4 > (index + 1) % 3 else "D" if index % 4 == (index + 1) % 3 else "A",
                "elo_diff": float(30 + index), "team.shots_3": float(8 + index % 5),
            }
            for index in range(40)
        ])
        artifact = model_artifact.train_poisson(history, 2, ["elo_diff", "team.shots_3"], "synthetic")
        artifact_path = root / "synthetic.pkl"
        digest = model_artifact.save_artifact(artifact, artifact_path)
        research = root / "research.json"
        research.write_text(json.dumps({
            "purpose": "private_research_only_unregistered_not_active",
            "artifacts": {name: {"path": str(artifact_path), "sha256": digest} for name in freeze.CHALLENGERS},
        }))
        frozen_manifest = {
            "provider": "football-data.org", "season": "2627",
            "generated_at": (as_of + timedelta(minutes=3)).isoformat(),
            "provider_match_counts": dict(sync.EXPECTED_LEAGUE_FIXTURES),
            "fixtures": rows, "completed_fixtures": [], "excluded_fixtures": [],
        }
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(frozen_manifest))
        primary_path = root / "primary.json"

        class SyntheticClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return as_of + timedelta(minutes=10)

        arguments = [
            "freeze_shadow_tournament.py", "--season", "2627", "--as-of", as_of.isoformat(),
            "--fixtures-file", str(manifest_path), "--primary-artifact", str(artifact_path),
            "--research-artifacts", str(research), "--prediction-output", str(primary_path),
            "--research-dir", str(root / "research"),
        ]
        provenance = {
            "eligible_match_count": 0, "eligible_observation_count": 0,
            "latest_eligible_match_kickoff": None, "source_rows_sha256": "synthetic-source",
        }
        with patch.object(freeze.contract, "require_real_cutoff"), \
             patch.object(freeze.baseline, "db_client", return_value=object()), \
             patch.object(freeze, "fetch_inputs", return_value=(rows, [], [], provenance)), \
             patch.object(freeze, "datetime", SyntheticClock), \
             patch.object(sys, "argv", arguments):
            assert freeze.main() == 0
        tournament_path = root / "research" / "2627_20260924T120000Z_tournament.json"
        assert tournament_audit.audit(tournament_path)["passed"]
        finished = [
            {"game_id": row["game_id"], "league": row["league"],
             "date": row["date"], "kickoff_at": row["kickoff_at"],
             "home_score": 2, "away_score": 1}
            for row in rows
        ]
        scorecard = scoring.cumulative("2627", root / "research", finished)
        assert scorecard["verified_tournaments"] == 1
        assert scorecard["scored_same_fixture_calls"] == 5
        assert set(scorecard["metrics"]) == set(scoring.MODELS)
        assert scorecard["weeks"][0]["complete_result_window"]
        assert scorecard["premier_home_favorite_monitor"]["premier_league_resolved"] == 1
        extra = finished + [{"game_id": "omitted", "league": contract.TOP_FIVE[0],
                             "date": "2026-09-26", "kickoff_at": "2026-09-26T19:00:00+00:00",
                             "home_score": 1, "away_score": 0}]
        incomplete = scoring.cumulative("2627", root / "research", extra)
        assert incomplete["weeks"][0]["later_verified_omitted_fixture_ids"] == ["omitted"]
        assert not incomplete["weeks"][0]["complete_result_window"]
        assert not scorecard["review_gate"]["ready_for_human_review"]
    print("Frozen tournament cutoff, coverage, and scoring checks passed")


if __name__ == "__main__":
    main()
