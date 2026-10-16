#!/usr/bin/env python3
"""Stored scoreline grids must reach the league simulator unchanged.

Drives the real ``run_league_simulation.main`` database branch (dry run) through
the installed PostgREST client and an ``httpx.MockTransport`` that returns only
the columns the code actually requests. A query that omits the grid therefore
makes the simulator rebuild scores from rounded rates, and this check fails.
Offline only: no sockets, credentials or service clients; NOT a database
round trip.
"""

from __future__ import annotations

import io
import json
import math
import sys
import tempfile
from contextlib import ExitStack, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
from postgrest import SyncPostgrestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))


def offline_guards() -> ExitStack:
    stack = ExitStack()
    for target in ("socket.socket.connect", "socket.create_connection",
                   "dotenv.load_dotenv", "supabase.create_client",
                   "httpx.HTTPTransport.handle_request"):
        stack.enter_context(patch(target, side_effect=AssertionError(
            "offline check forbids live transport, credentials and service clients")))
    return stack


with offline_guards():
    import run_league_simulation as runner
    import simulate_league_table as simulator

AS_OF = datetime(2026, 9, 17, 12, tzinfo=UTC)
FIELDS = ("home_win_probability", "draw_probability", "away_win_probability")


def outcome(home: int, away: int) -> int:
    return 0 if home > away else 1 if home == away else 2


def masses(grid: dict[str, float]) -> list[float]:
    totals = [0.0, 0.0, 0.0]
    for score, probability in grid.items():
        home, away = map(int, score.split("-"))
        totals[outcome(home, away)] += probability
    return totals


def legacy_grid(home_rate: float, away_rate: float, maximum: int = 8) -> dict[str, float]:
    """The deployed 9x9 grid, built from unrounded rates as at forecast time."""
    pmf = lambda rate, goals: math.exp(-rate) * rate ** goals / math.factorial(goals)
    cells = {f"{h}-{a}": pmf(home_rate, h) * pmf(away_rate, a)
             for h in range(maximum + 1) for a in range(maximum + 1)}
    total = sum(cells.values())
    return {score: value / total for score, value in cells.items()}


# B v C: realistic legacy row. Scalars are stored at numeric(7,4)/(8,7); the grid
# came from the unrounded rates. C v A: deliberately non-Poisson grid, so any
# reconstruction from rates is unmistakable.
LEGACY = legacy_grid(1.23456789, 0.98765432)
SYNTHETIC = {"0-0": 0.1, "1-0": 0.3, "3-1": 0.15, "1-1": 0.2, "0-2": 0.25}
STORED = {
    "f-bc": {"rates": (1.2346, 0.9877), "grid": LEGACY},
    "f-ca": {"rates": (1.1, 1.4), "grid": SYNTHETIC},
}
STORED_ROWS = [
    {"game_id": game_id, "home_expected_goals": spec["rates"][0],
     "away_expected_goals": spec["rates"][1],
     **{field: round(value, 7) for field, value in zip(FIELDS, masses(spec["grid"]))},
     "scoreline_distribution": spec["grid"]}
    for game_id, spec in STORED.items()
]
MATCHES = [
    {"game_id": "p-ab", "date": "2026-09-01", "kickoff_at": "2026-09-01T15:00:00+00:00",
     "home_team": "A", "away_team": "B", "home_score": 1, "away_score": 0},
    {"game_id": "f-bc", "date": "2026-09-20", "kickoff_at": "2026-09-20T15:00:00+00:00",
     "home_team": "B", "away_team": "C", "home_score": None, "away_score": None},
    {"game_id": "f-ca", "date": "2026-09-21", "kickoff_at": "2026-09-21T15:00:00+00:00",
     "home_team": "C", "away_team": "A", "home_score": None, "away_score": None},
]


class MockSupabase:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        client = httpx.Client(base_url="https://offline.invalid/rest/v1/", trust_env=False,
                              transport=httpx.MockTransport(self.handle))
        self.db = SyncPostgrestClient("https://offline.invalid/rest/v1/", http_client=client)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "offline.invalid"
        assert request.method == "GET", f"dry run must not write: {request.method} {request.url.path}"
        table = request.url.path.rsplit("/", 1)[-1]
        if table == "ml_model_runs":
            data = [{"id": 4, "status": "shadow", "model_key": "offline", "model_version": "offline"}]
        elif table == "matches":
            data = MATCHES
        elif table == "ml_match_predictions":
            params = request.url.params
            assert params["model_run_id"] == "eq.4"
            assert params["forecast_kind"] == "eq.thursday_frozen"
            assert datetime.fromisoformat(params["as_of"].removeprefix("eq.")) == AS_OF
            columns = params["select"].split(",")
            # Like PostgREST, return only the requested columns.
            data = [{column: row[column] for column in columns} for row in STORED_ROWS]
        else:
            raise AssertionError(f"unexpected table: {table}")
        return httpx.Response(200, json=data, request=request)


def run_main(fake: MockSupabase, output: Path) -> list[dict]:
    captured: list[dict] = []

    def capture(standings, fixtures, **kwargs):
        captured.extend(json.loads(json.dumps(fixtures)))
        return simulator.simulate_league(standings, fixtures, **kwargs)

    argv = ["run_league_simulation.py", "--model-run-id", "4", "--league", "ENG-Premier League",
            "--season", "offline", "--as-of", AS_OF.isoformat(), "--forecast-kind", "thursday_frozen",
            "--simulations", "50", "--output", str(output)]
    with patch.object(sys, "argv", argv), \
         patch.object(runner.baseline, "db_client", return_value=fake.db), \
         patch.object(runner, "simulate_league", side_effect=capture), \
         redirect_stdout(io.StringIO()):
        assert runner.main() == 0
    return captured


def check_distribution(fixture: dict, grid: dict[str, float], stored_row: dict) -> None:
    expected = [{"home_goals": int(score.split("-")[0]), "away_goals": int(score.split("-")[1]),
                 "probability": probability} for score, probability in grid.items()]
    assert fixture.get("score_probabilities") == expected, \
        "stored scoreline grid did not reach the simulator unchanged"
    distribution = simulator._score_distribution(fixture, 10)
    assert [(h, a) for h, a, _ in distribution] == [(i["home_goals"], i["away_goals"]) for i in expected], \
        "simulator support differs from the stored grid"
    # Alignment to the stored (7-dp) headline may rescale whole classes, but the
    # within-class score ratios must be the stored ones.
    target = [stored_row[field] for field in FIELDS]
    stored_mass = masses(grid)
    for (h, a, probability), item in zip(distribution, expected):
        k = outcome(h, a)
        assert math.isclose(probability, item["probability"] * target[k] / stored_mass[k] / sum(target),
                            rel_tol=1e-12, abs_tol=1e-15)
    prepared = simulator.prepare_fixtures([fixture], {"A", "B", "C"})[0]
    assert prepared["scores"] == [(i["home_goals"], i["away_goals"]) for i in expected]

    rebuilt = simulator._score_distribution(
        {k: v for k, v in fixture.items() if k != "score_probabilities"}, 10)
    assert {(h, a) for h, a, _ in rebuilt} != {(h, a) for h, a, _ in distribution}, \
        "control: rebuilding from rates must not coincide with the stored grid"


def main() -> int:
    with offline_guards(), tempfile.TemporaryDirectory(prefix="sim-grid-offline-") as directory:
        fake = MockSupabase()
        try:
            fixtures = run_main(fake, Path(directory) / "simulation.json")
            assert (Path(directory) / "simulation.json").is_file()
        finally:
            fake.db.session.close()
    by_pair = {(f["home_team"], f["away_team"]): f for f in fixtures}
    assert set(by_pair) == {("B", "C"), ("C", "A")}
    rows = {row["game_id"]: row for row in STORED_ROWS}
    check_distribution(by_pair[("B", "C")], LEGACY, rows["f-bc"])
    check_distribution(by_pair[("C", "A")], SYNTHETIC, rows["f-ca"])
    selects = [r.url.params["select"] for r in fake.requests if r.url.path.endswith("/ml_match_predictions")]
    assert selects and all("scoreline_distribution" in s.split(",") for s in selects), \
        f"simulation query omits scoreline_distribution: {selects}"
    print("Stored scoreline grid simulation checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
