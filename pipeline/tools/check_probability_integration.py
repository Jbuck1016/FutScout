"""Offline production-contract regressions; no fitting, credentials or live DB.

Exercises the installed PostgREST/httpx serializer through MockTransport. Decimal
coercion emulates ONLY the checked-in numeric declarations, not a PostgreSQL
round trip, permissions, FK enforcement, storage, or deployed schema discovery.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, redirect_stdout
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
import numpy as np
import pandas as pd
from postgrest import SyncPostgrestClient
from scipy.stats import skellam

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))


def offline_guards():
    stack = ExitStack()
    for target in ("socket.socket.connect", "socket.create_connection",
                   "dotenv.load_dotenv", "supabase.create_client",
                   "httpx.HTTPTransport.handle_request"):
        stack.enter_context(patch(target, side_effect=AssertionError(
            "offline test forbids live transport, credentials and service clients")))
    return stack


with offline_guards():
    import generate_match_predictions as generation
    import model_artifact
    import run_league_simulation as simulation
    import train_match_baselines as baseline
    from score_probabilities import SCORE_CONTRACT_VERSION, result_masses, score_dict, score_matrix
    from simulate_league_table import _score_distribution, prepare_fixtures


FIELDS = ("home_win_probability", "draw_probability", "away_win_probability")
RATES = ("home_expected_goals", "away_expected_goals")
SCHEMA = ROOT / "supabase/migrations/20260901230956_model_data_foundations.sql"
AS_OF = datetime(2026, 9, 17, 12, tzinfo=UTC)
DB_KEYS = {"game_id", "model_run_id", "forecast_kind", "as_of", "scoreline_distribution", *FIELDS, *RATES}
REPORT = {"mode": "offline installed-SDK MockTransport and Decimal emulation; NOT a database round trip"}


def declared_types():
    sql = SCHEMA.read_text(encoding="utf-8")
    table = sql.split("create table if not exists public.ml_match_predictions (", 1)[1].split("\n);", 1)[0]
    types = {}
    for name in (*FIELDS, *RATES):
        match = re.search(r"\b" + name + r"\s+numeric\((\d+),(\d+)\)", table)
        if match is None:
            raise AssertionError(f"missing numeric declaration: {name}")
        types[name] = tuple(map(int, match.groups()))
    assert "scoreline_distribution jsonb" in table
    assert "jsonb_typeof(scoreline_distribution) = 'object'" in table
    assert "<= 0.000001" in table
    return types


def numeric_emulation(value, precision, scale):
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("test emulator accepts finite decimals only")
    rounded = number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    if abs(rounded) >= Decimal(10) ** (precision - scale):
        raise ValueError("numeric precision overflow")
    return rounded


def emulate_declared_row(row):
    result = json.loads(json.dumps(row, allow_nan=False))
    decimals = {name: numeric_emulation(row[name], *kind) for name, kind in declared_types().items()}
    if any(decimals[name] < 0 for name in RATES):
        raise ValueError("negative expected goals")
    if any(not Decimal(0) <= decimals[name] <= Decimal(1) for name in FIELDS):
        raise ValueError("probability outside declared bounds")
    if abs(sum(decimals[name] for name in FIELDS) - 1) > Decimal("0.000001"):
        raise ValueError("declared probability sum constraint")
    if not isinstance(result["scoreline_distribution"], dict):
        raise ValueError("declared JSONB object constraint")
    result.update({name: float(value) for name, value in decimals.items()})
    return result


def prediction(home=1.23456789, away=0.98765432, game_id="offline-fixture", date=None):
    return {"game_id": game_id, "league": "ENG-Premier League",
            "date": (date or AS_OF + timedelta(days=1)).isoformat(),
            "home_team": "Offline Home", "away_team": "Offline Away",
            **dict(zip(RATES, (home, away))),
            **dict(zip(FIELDS, map(float, result_masses(score_matrix(home, away))))),
            "scoreline_distribution": score_dict(home, away),
            "score_distribution_contract": SCORE_CONTRACT_VERSION,
            "explanation": {"private": "synthetic contract fixture"}}


def masses(scores):
    return np.array([sum(p for h, a, p in scores if (0 if h > a else 1 if h == a else 2) == outcome)
                     for outcome in range(3)])


class MockPersistence:
    """Real SDK request serialization; fake registry and numeric-only DB emulator."""
    def __init__(self, directory, status="shadow", matching_digest=True):
        self.path = Path(directory) / "synthetic-artifact.bin"
        self.path.write_bytes(b"offline synthetic artifact identity; not a trained model")
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.status = status
        self.matching_digest = matching_digest
        self.requests = []
        self.rows = []
        client = httpx.Client(base_url="https://offline.invalid/rest/v1/", trust_env=False,
                              transport=httpx.MockTransport(self.handle))
        self.db = SyncPostgrestClient("https://offline.invalid/rest/v1/", http_client=client)
        self.args = SimpleNamespace(artifact=self.path, model_run_id=123456789,
                                    forecast_kind="thursday_frozen", evaluation_days=7)

    def handle(self, request):
        self.requests.append(request)
        assert request.url.host == "offline.invalid"
        assert "authorization" not in request.headers and "apikey" not in request.headers
        if request.method == "GET" and request.url.path.endswith("/ml_model_runs"):
            assert request.url.params["id"] == "eq.123456789"
            data = [{"id": 123456789, "status": self.status,
                     "artifact_sha256": self.digest if self.matching_digest else "0" * 64}]
        elif request.method == "POST" and request.url.path.endswith("/ml_match_predictions"):
            data = json.loads(request.content)
            assert all(set(row) == DB_KEYS for row in data)
            self.rows = [emulate_declared_row(row) for row in data]
            data = self.rows
        elif request.method == "GET" and request.url.path.endswith("/ml_match_predictions"):
            data = self.rows
        else:
            raise AssertionError(f"unexpected mock request: {request.method} {request.url.path}")
        return httpx.Response(200, json=data, request=request)

    def persist(self, rows):
        with redirect_stdout(io.StringIO()):
            generation.persist_predictions(self.db, self.args, {}, rows, AS_OF, AS_OF + timedelta(days=7))

    def close(self):
        self.db.session.close()


class ProbabilityIntegrationChecks(unittest.TestCase):
    def test_declared_numeric_precision_and_constraints(self):
        self.assertEqual(declared_types(), {**dict.fromkeys(FIELDS, (8, 7)), **dict.fromkeys(RATES, (7, 4))})
        self.assertEqual(numeric_emulation("0.12345675", 8, 7), Decimal("0.1234568"))
        self.assertEqual(numeric_emulation("-0.12345675", 8, 7), Decimal("-0.1234568"))
        self.assertEqual(numeric_emulation("999.99994", 7, 4), Decimal("999.9999"))
        with self.assertRaisesRegex(ValueError, "overflow"):
            numeric_emulation("999.99995", 7, 4)
        for name, value in ((FIELDS[0], 1.1), (RATES[0], -1)):
            row = prediction(); row[name] = value
            with self.assertRaises(ValueError):
                emulate_declared_row(row)
        row = prediction(); row[FIELDS[0]] += .01
        with self.assertRaisesRegex(ValueError, "sum constraint"):
            emulate_declared_row(row)

    def test_shared_grid_json_precision_tails_and_independent_oracle(self):
        cases = ((0, 0), (.05, .05), (.05, 6), (6, .05), (6, 6), (1.23456789, .98765432), (2.7, 1.3))
        rounding_errors = []
        for home, away in cases:
            with self.subTest(rates=(home, away)):
                distribution = json.loads(json.dumps(model_artifact.scoreline_distribution(home, away), allow_nan=False))
                scores = [(*map(int, key.split("-")), p) for key, p in distribution.items()]
                probabilities = baseline.poisson_result_probabilities(np.array([home]), np.array([away]))[0]
                np.testing.assert_allclose(masses(scores), probabilities, atol=2e-12, rtol=0)
                self.assertAlmostEqual(sum(distribution.values()), 1, places=12)
                if home > 0 and away > 0:
                    oracle = [skellam.sf(0, home, away), skellam.pmf(0, home, away), skellam.cdf(-1, home, away)]
                    np.testing.assert_allclose(probabilities, oracle, atol=2e-12, rtol=0)
                    self.assertGreater(distribution["9-0"], 0)
                stored = emulate_declared_row(prediction(home, away))
                np.testing.assert_allclose([stored[key] for key in FIELDS], probabilities, atol=5.0002e-8, rtol=0)
                self.assertLessEqual(abs(sum(stored[key] for key in FIELDS) - 1), 1.50001e-7)
                rounding_errors.append(max(abs(stored[key] - probabilities[i]) for i, key in enumerate(FIELDS)))
                self.assertEqual(stored["scoreline_distribution"], distribution)
        REPORT["synthetic_precision"] = {"cases": len(cases), "max_scalar_rounding_error": max(rounding_errors)}

    def test_invalid_rates_and_array_contract(self):
        for home, away in ((-1, 1), (float("nan"), 1), (1, float("inf"))):
            with self.assertRaises(ValueError):
                score_matrix(home, away)
        for lower in (0, True, 1.5):
            with self.assertRaises(ValueError):
                score_matrix(1, 1, lower)
        for home, away in (([1], [1, 2]), ([[1]], [[1]])):
            with self.assertRaises(ValueError):
                baseline.poisson_result_probabilities(np.array(home), np.array(away))
        self.assertEqual(baseline.poisson_result_probabilities(np.array([]), np.array([])).shape, (0, 3))

    def test_real_sdk_wire_round_trip_and_slate_boundaries(self):
        with tempfile.TemporaryDirectory(prefix="soccer-offline-") as directory:
            fake = MockPersistence(directory)
            self.addCleanup(fake.close)
            rows = [prediction(game_id=name, date=when) for name, when in (
                ("at-cutoff", AS_OF), ("inside", AS_OF + timedelta(seconds=1)),
                ("at-end", AS_OF + timedelta(days=7)),
                ("outside", AS_OF + timedelta(days=7, seconds=1)))]
            fake.persist(rows)
            posts = [req for req in fake.requests if req.method == "POST"]
            self.assertEqual(len(posts), 1)
            request = posts[0]
            self.assertEqual(request.url.params["on_conflict"], "model_run_id,game_id,forecast_kind,as_of")
            self.assertIn("resolution=merge-duplicates", request.headers["prefer"])
            self.assertEqual(request.headers["content-type"], "application/json")
            wire = json.loads(request.content)
            self.assertEqual([row["game_id"] for row in wire], ["inside", "at-end"])
            self.assertEqual(wire[0]["scoreline_distribution"], rows[1]["scoreline_distribution"])
            self.assertNotEqual(wire[0][RATES[0]], fake.rows[0][RATES[0]])
            fetched = fake.db.table("ml_match_predictions").select("*").execute().data
            self.assertEqual(fetched, fake.rows)
            self.assertEqual(fetched[0]["scoreline_distribution"], wire[0]["scoreline_distribution"])
            REPORT["sdk_wire"] = {"requests": len(fake.requests), "posts": len(posts),
                                  "rows": len(wire), "request_bytes": len(request.content),
                                  "auth_headers": False, "id": "synthetic 123456789", "keys": sorted(wire[0])}

    def test_registry_and_empty_slate_guards_send_no_post(self):
        cases = (("training", True, False), ("shadow", False, False), ("active", True, True))
        for status, digest, empty in cases:
            with self.subTest(status=status, matching_digest=digest, empty=empty), tempfile.TemporaryDirectory(prefix="soccer-offline-") as directory:
                fake = MockPersistence(directory, status, digest)
                try:
                    with self.assertRaises(RuntimeError):
                        fake.persist([] if empty else [prediction()])
                    self.assertFalse(any(request.method == "POST" for request in fake.requests))
                finally:
                    fake.close()

    def test_httpx_rejects_nonfinite_json_before_mock_transport(self):
        with tempfile.TemporaryDirectory(prefix="soccer-offline-") as directory:
            fake = MockPersistence(directory)
            self.addCleanup(fake.close)
            row = prediction(); row[FIELDS[0]] = float("nan")
            with self.assertRaises(ValueError):
                fake.persist([row])
            self.assertFalse(any(request.method == "POST" for request in fake.requests))

    def test_actual_simulation_adapter_uses_explicit_grid_after_coercion(self):
        original = prediction(1.23456789, .98765432)
        stored = emulate_declared_row(original)
        matches = [{"game_id": original["game_id"], "home_team": original["home_team"],
                    "away_team": original["away_team"], "date": original["date"],
                    "kickoff_at": original["date"], "home_score": None, "away_score": None}]
        _, fixtures, completed = simulation.build_snapshot_with_results(matches, [stored], AS_OF)
        self.assertEqual(completed, [])
        scores = _score_distribution(fixtures[0], 8)
        prepared = prepare_fixtures(fixtures, {original["home_team"], original["away_team"]})[0]
        target = np.array([stored[key] for key in FIELDS]); target /= target.sum()
        np.testing.assert_allclose(masses(scores), target, atol=2e-12, rtol=0)
        self.assertEqual(prepared["cumulative"][-1], 1.0)
        explicit = dict(((h, a), p) for h, a, p in scores)
        self.assertGreater(max(h for h, _, _ in scores), 8)
        self.assertAlmostEqual(explicit[(2, 0)] / explicit[(1, 0)],
                               original["scoreline_distribution"]["2-0"] / original["scoreline_distribution"]["1-0"], places=13)
        # The explicit branch must not regenerate conditional scores from rounded rates.
        altered = dict(fixtures[0], expected_home_goals=6., expected_away_goals=.05)
        self.assertEqual(_score_distribution(altered, 8), scores)
        regenerated = result_masses(score_matrix(stored[RATES[0]], stored[RATES[1]]))
        original_probabilities = np.array([original[key] for key in FIELDS])
        self.assertGreater(max(abs(regenerated - original_probabilities)), 1e-6)

    def test_legacy_explicit_support_and_score_ratios_remain_unchanged(self):
        fixture = {"score_probabilities": [
            {"home_goals": 1, "away_goals": 0, "probability": .3},
            {"home_goals": 2, "away_goals": 0, "probability": .3},
            {"home_goals": 0, "away_goals": 0, "probability": .2},
            {"home_goals": 0, "away_goals": 1, "probability": .2}]}
        self.assertEqual(_score_distribution(fixture, 8), [(1, 0, .3), (2, 0, .3), (0, 0, .2), (0, 1, .2)])
        aligned = _score_distribution(fixture | dict(zip(FIELDS, (.5, .3, .2))), 8)
        np.testing.assert_allclose(masses(aligned), [.5, .3, .2], atol=2e-12, rtol=0)
        self.assertEqual(aligned[0][2], aligned[1][2])

    def test_prediction_output_keeps_existing_model_inputs_and_clips_without_fit(self):
        seen = []
        class FixedPredictor:
            def __init__(self, values): self.values = np.array(values)
            def predict(self, frame):
                seen.append(frame.copy())
                return self.values
            def fit(self, *args): raise AssertionError("no fitting allowed")
        artifact = {"numeric_columns": ["team.rest_days"], "feature_schema_version": 1,
                    "home_model": FixedPredictor([1.23456789, -1, 10]),
                    "away_model": FixedPredictor([.98765432, 10, -1])}
        fixtures = [{"game_id": f"stub-{i}", "league": "ENG-Premier League", "date": pd.Timestamp("2026-09-18", tz="UTC"),
                     "home_team": "Home", "away_team": "Away", "team.rest_days": 500} for i in range(3)]
        with patch.object(model_artifact, "fixture_row", side_effect=lambda row, *a, **k: row), \
             patch.object(model_artifact, "_match_explanation", return_value={}) as explanation:
            rows = model_artifact.predict_rows(artifact, fixtures, [], [])
        expected_frame = model_artifact.multiseason.normalize_model_features(pd.DataFrame(fixtures))
        for frame in seen:
            pd.testing.assert_frame_equal(frame, expected_frame)
        self.assertEqual([row[RATES[0]] for row in rows], [1.23456789, .05, 6.])
        self.assertEqual([row[RATES[1]] for row in rows], [.98765432, 6., .05])
        self.assertEqual(explanation.call_count, 3)
        self.assertTrue(all(row["score_distribution_contract"] == SCORE_CONTRACT_VERSION for row in rows))
        self.assertEqual(model_artifact.predict_rows(artifact, [], [], []), [])

    def test_corrected_label_and_private_dashboard_excludes_grid(self):
        self.assertEqual(model_artifact._explanation_group("team.box_entries_pass_3"), "Completed box passes")
        source = (ROOT / "pipeline/model_artifact.py").read_text(encoding="utf-8")
        self.assertIn("completed passes ending in the box (including passes starting there)", source)
        builder = (ROOT / "pipeline/build_model_review_dashboard.py").read_text(encoding="utf-8")
        self.assertNotIn("scoreline_distribution", builder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    with offline_guards(), patch.object(baseline, "db_client", side_effect=AssertionError("no DB client")), \
         patch.object(baseline, "load_dotenv", side_effect=AssertionError("no credentials")):
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ProbabilityIntegrationChecks))
    REPORT.update({"passed": result.wasSuccessful(), "tests_run": result.testsRun,
                   "failures": len(result.failures), "errors": len(result.errors),
                   "declared_schema_sha256": hashlib.sha256(SCHEMA.read_bytes()).hexdigest(),
                   "versions": {name: importlib.metadata.version(name) for name in
                                ("postgrest", "supabase", "httpx", "numpy", "scipy", "scikit-learn")},
                   "limitations": ["No deployed schema, SQL engine, RLS, FK, idempotency, storage or gateway verification.",
                                   "MockTransport captures real SDK JSON, then test code emulates declared numeric coercion."]})
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(REPORT, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
