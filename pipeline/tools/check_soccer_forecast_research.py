"""Offline regressions for shared probabilities and chronological research."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
import tempfile
import hashlib
import contextlib
import io

import numpy as np
import pandas as pd
from scipy.stats import poisson, skellam

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import train_match_baselines as baseline
import model_artifact
import generate_match_predictions as generation
from simulate_league_table import _score_distribution
from score_probabilities import score_matrix, result_masses, TAIL_TOLERANCE
from soccer_metric_contracts import completed_open_play_box_pass, completed_open_play_box_entry
from research_soccer_forecasts import add_schedule_context, fit_adjusters, apply_adjusters, columns_for


def masses(scores):
    values = np.zeros(3)
    for h, a, p in scores:
        values[0 if h > a else 1 if h == a else 2] += p
    return values


class ProbabilityTests(unittest.TestCase):
    def test_headline_saved_simulated_and_independent_skellam(self):
        for h, a in ((.05, .05), (1.8, .8), (6., 6.), (6., 3.), (.05, 6.), (0., 0.)):
            headline = baseline.poisson_result_probabilities(np.array([h]), np.array([a]))[0]
            saved = [(int(k.split('-')[0]), int(k.split('-')[1]), p)
                     for k, p in model_artifact.scoreline_distribution(h, a).items()]
            simulated = _score_distribution({"expected_home_goals": h, "expected_away_goals": a}, 8)
            np.testing.assert_allclose(headline, masses(saved), atol=1e-14, rtol=0)
            np.testing.assert_allclose(headline, masses(simulated), atol=1e-14, rtol=0)
            self.assertAlmostEqual(sum(p for _, _, p in saved), 1, places=13)
            if h and a:
                reference = [skellam.sf(0, h, a), skellam.pmf(0, h, a), skellam.cdf(-1, h, a)]
                np.testing.assert_allclose(headline, reference, atol=2e-12, rtol=0)
            m = score_matrix(h, a)
            self.assertLessEqual(1 - poisson.cdf(len(m)-1, h)*poisson.cdf(len(m)-1, a), TAIL_TOLERANCE)

    def test_legacy_defect_is_material_at_supported_high_rates(self):
        def old(maximum):
            grid = np.arange(maximum+1)
            m = np.outer(poisson.pmf(grid, 6), poisson.pmf(grid, 3))
            return result_masses(m/m.sum())
        self.assertGreater(np.max(np.abs(old(8)-old(12))), .01)

    def test_dc_marginals_and_positivity(self):
        for h, a in ((.05, .05), (6., 6.), (2.1, 1.3)):
            ordinary = score_matrix(h, a)
            corrected = score_matrix(h, a, rho=-.1)
            np.testing.assert_allclose(ordinary.sum(axis=0), corrected.sum(axis=0), atol=1e-14)
            np.testing.assert_allclose(ordinary.sum(axis=1), corrected.sum(axis=1), atol=1e-14)
            self.assertTrue((corrected >= 0).all())
        with self.assertRaises(ValueError):
            score_matrix(6, 6, rho=.5)

    def test_invalid_rates_and_empty_arrays(self):
        for h in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                score_matrix(h, 1)
        with self.assertRaises(ValueError):
            baseline.poisson_result_probabilities(np.array([1, 2]), np.array([1]))
        self.assertEqual(baseline.poisson_result_probabilities(np.array([]), np.array([])).shape, (0, 3))

    def test_legacy_explicit_forecast_distribution_preserved(self):
        explicit = [{"home_goals": 0, "away_goals": 0, "probability": .3},
                    {"home_goals": 1, "away_goals": 0, "probability": .7}]
        self.assertEqual(_score_distribution({"score_probabilities": explicit}, 8), [(0, 0, .3), (1, 0, .7)])

    def test_local_contract_metadata_does_not_become_database_column(self):
        db = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'artifact.pkl'
            path.write_bytes(b'test fixture, never a trained artifact')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
                {'id': 'test', 'status': 'shadow', 'artifact_sha256': digest}]
            args = SimpleNamespace(model_run_id='test', artifact=path, forecast_kind='test', evaluation_days=7)
            now = datetime(2026, 1, 1, tzinfo=UTC)
            row = dict(game_id='x', date=(now+timedelta(days=1)).isoformat(), league='L', home_team='A', away_team='B',
                       home_expected_goals=1.3, away_expected_goals=1.1,
                       home_win_probability=.4, draw_probability=.3, away_win_probability=.3,
                       scoreline_distribution={'0-0': 1}, explanation={}, score_distribution_contract='test')
            with contextlib.redirect_stdout(io.StringIO()):
                generation.persist_predictions(db, args, {}, [row], now, now+timedelta(days=7))
            payload = db.table.return_value.upsert.call_args.args[0][0]
            self.assertNotIn('score_distribution_contract', payload)
            self.assertEqual(payload['scoreline_distribution'], row['scoreline_distribution'])


class MetricTests(unittest.TestCase):
    def test_box_pass_is_not_always_an_entry(self):
        event = dict(type="Pass", outcome_type="Successful", is_open_play=True, x=87, y=50, end_x=95, end_y=50)
        self.assertTrue(completed_open_play_box_pass(event))
        self.assertFalse(completed_open_play_box_entry(event))
        self.assertTrue(completed_open_play_box_entry(event | {"x": 70}))
        self.assertTrue(completed_open_play_box_entry(event | {"y": 10}))
        self.assertFalse(completed_open_play_box_entry(event | {"x": None}))
        self.assertFalse(completed_open_play_box_entry(event | {"is_open_play": False}))
        self.assertFalse(completed_open_play_box_entry(event | {"outcome_type": "Unsuccessful"}))


class ChronologyTests(unittest.TestCase):
    @staticmethod
    def frame():
        rows = []
        for i in range(36):
            rows.append({"game_id": str(i), "date": pd.Timestamp('2023-08-01')+pd.Timedelta(days=7*i),
                "league": "L", "home_team": "A" if i % 2 else "B", "away_team": "B" if i % 2 else "A",
                "elo_home": 1510+i, "elo_away": 1490-i,
                **{f"{s}.{m}_5": float(i%9+offset) for s in ('team', 'opponent')
                   for m, offset in (("shots", 10), ("shots_against", 12), ("ppda", 8),
                                     ("progressive_passes", 40), ("defensive_height", 35))}})
        return pd.DataFrame(rows)

    def test_schedule_uses_only_past_games_and_no_same_date(self):
        f = self.frame()
        before = add_schedule_context(f)
        mutated = f.copy()
        mutated.loc[mutated.index >= 20, 'elo_away'] = 99999
        after = add_schedule_context(mutated)
        cols = [c for c in before if 'schedule_' in c]
        pd.testing.assert_frame_equal(before.loc[:20, cols], after.loc[:20, cols])
        self.assertEqual(before.loc[0, 'team.schedule_count_5'], 0)
        self.assertEqual(before.loc[1, 'team.schedule_elo_5'], f.loc[0, 'elo_home'])
        same_day = f.iloc[:2].copy()
        same_day['date'] = f.iloc[0].date
        self.assertTrue(add_schedule_context(same_day)['team.schedule_count_5'].eq(0).all())

    def test_adjustment_fit_is_training_only_and_preserves_missingness(self):
        f = add_schedule_context(self.frame())
        adjusters = fit_adjusters(f.iloc[:20])
        before = apply_adjusters(f.iloc[20:], adjusters)
        altered = f.iloc[20:].copy()
        altered['home_goals'] = 999
        altered['away_goals'] = 0
        after = apply_adjusters(altered, adjusters)
        cols = [c for c in before if 'adjusted_' in c]
        pd.testing.assert_frame_equal(before[cols], after[cols])
        altered.loc[20, 'team.ppda_5'] = np.nan
        self.assertTrue(pd.isna(apply_adjusters(altered, adjusters).loc[20, 'team.adjusted_ppda_5']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
