#!/usr/bin/env python3
"""Regression checks for duplicate fixture selection and shot phase tagging."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generate_match_predictions import select_fixtures
from event_phase import event_is_open_play
from sync_future_fixtures import existing_fixtures, fixture_key


def fixture(game_id: str) -> dict:
    return {
        "game_id": game_id, "season": "2627", "league": "ENG-Premier League",
        "home_team": "Arsenal", "away_team": "Manchester City",
        "date": "2026-11-29", "kickoff_at": "2026-11-29T16:30:00+00:00",
        "home_score": None, "away_score": None,
    }


class FakeQuery:
    def __init__(self, rows: list[dict]):
        self.data = rows

    def select(self, _columns: str) -> FakeQuery:
        return self

    def eq(self, _column: str, _value: str) -> FakeQuery:
        return self

    def execute(self) -> FakeQuery:
        return self


class FakeDb:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def table(self, _table: str) -> FakeQuery:
        return FakeQuery(self.rows)


def main() -> None:
    who_scored = fixture("1983824")
    provider = fixture("fd-560654")
    canonical = existing_fixtures(FakeDb([provider, who_scored]), "ENG-Premier League", "2627")
    assert canonical[fixture_key(provider)]["game_id"] == "1983824"

    cutoff = datetime(2026, 9, 24, 12, tzinfo=UTC)
    selected = select_fixtures([provider, who_scored], cutoff, {"1983824"})
    assert [row["game_id"] for row in selected] == ["1983824"]
    selected_legacy = select_fixtures([provider, who_scored], cutoff, {"fd-560654"})
    assert [row["game_id"] for row in selected_legacy] == ["fd-560654"]
    assert len(select_fixtures([provider, who_scored], cutoff, None)) == 1

    def qualifiers(name: str) -> list[dict]:
        return [{"type": {"displayName": name}}]

    for name in ("Penalty", "FromCorner", "SetPiece", "DirectFreekick", "ThrowinSetPiece"):
        assert event_is_open_play(qualifiers(name)) is False, name
    assert event_is_open_play(qualifiers("BoxCentre")) is True
    assert event_is_open_play([]) is True
    print("Fixture identity and open-play classification checks passed")


if __name__ == "__main__":
    main()
