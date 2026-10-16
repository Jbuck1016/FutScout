"""Immutable-fixture and cutoff checks shared by private shadow experiments."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import sync_future_fixtures as fixture_sync


MAX_FREEZE_DELAY = timedelta(minutes=30)
TOP_FIVE = tuple(fixture_sync.COMPETITIONS)


def instant(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timezone required: {value}")
    return parsed.astimezone(UTC)


def fixture_instant(row: dict[str, Any]) -> datetime:
    return instant(row.get("kickoff_at") or f"{row['date']}T12:00:00+00:00")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(path: Path, season: str, as_of: datetime, *, strict_capture: bool) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if str(payload.get("season")) != season:
        raise RuntimeError("fixture manifest season mismatch")
    if payload.get("provider") != "football-data.org":
        raise RuntimeError("expected football-data.org fixture manifest")
    if strict_capture:
        generated = instant(payload["generated_at"])
        if not as_of <= generated <= as_of + MAX_FREEZE_DELAY:
            raise RuntimeError("provider manifest was not captured within 30 minutes of the frozen cutoff")
        counts = payload.get("provider_match_counts") or {}
        if counts != fixture_sync.EXPECTED_LEAGUE_FIXTURES:
            raise RuntimeError("provider manifest is missing a complete five-league schedule")
        if 'excluded_fixtures' not in payload:
            raise RuntimeError('manifest lacks explicit excluded/postponed schedule accounting; capture a fresh manifest')
        for row in payload['excluded_fixtures']:
            if row.get('provider_status') not in {'POSTPONED', 'SUSPENDED', 'CANCELLED', 'AWARDED'}:
                raise RuntimeError('excluded fixture has an active or unknown status; cannot prove schedule completeness')
        represented = list(payload.get('fixtures') or []) + list(payload.get('completed_fixtures') or []) + list(payload['excluded_fixtures'])
        for league, expected_count in counts.items():
            league_rows = [r for r in represented if r['league'] == league]
            source_ids = [str(r.get('provider_game_id') or r['game_id']) for r in league_rows]
            if len(source_ids) != expected_count or len(set(source_ids)) != expected_count:
                raise RuntimeError(f'{league}: declared provider count does not match unique accounted fixtures')
        if any(not r.get('kickoff_at') for r in payload.get('fixtures', [])):
            raise RuntimeError('active fixture lacks an exact kickoff; cannot freeze an assumed noon timestamp')
    future = list(payload.get("fixtures") or [])
    ids = [str(row["game_id"]) for row in future]
    if len(ids) != len(set(ids)):
        raise RuntimeError("provider fixture manifest contains duplicate game IDs")
    return payload


def expected_week(manifest: dict, as_of: datetime, through: datetime) -> dict[str, dict]:
    if through <= as_of:
        raise ValueError("evaluation horizon must end after cutoff")
    expected = {
        str(row["game_id"]): row
        for row in list(manifest["fixtures"]) + list(manifest.get('completed_fixtures') or [])
        if as_of < fixture_instant(row) <= through and row["league"] in TOP_FIVE
        and row.get('provider_status') not in {'POSTPONED', 'SUSPENDED', 'CANCELLED'}
    }
    return expected


def validate_week(
    manifest: dict, predictions: list[dict], as_of: datetime, through: datetime,
) -> dict:
    expected = expected_week(manifest, as_of, through)
    actual_rows = [row for row in predictions if as_of < instant(row["date"]) <= through]
    actual_ids = [str(row["game_id"]) for row in actual_rows]
    expected_ids = set(expected)
    actual_set = set(actual_ids)
    mismatched = []
    for row in actual_rows:
        source = expected.get(str(row["game_id"]))
        if source is None:
            continue
        if (
            row["league"] != source["league"]
            or row["home_team"] != source["home_team"]
            or row["away_team"] != source["away_team"]
            or instant(row["date"]) != fixture_instant(source)
        ):
            mismatched.append(str(row["game_id"]))
    by_league = {}
    for league in TOP_FIVE:
        required = {game_id for game_id, row in expected.items() if row["league"] == league}
        predicted = {str(row["game_id"]) for row in actual_rows if row["league"] == league}
        by_league[league] = {
            "expected": len(required),
            "predicted": len(predicted),
            "missing": sorted(required - predicted),
            "unexpected": sorted(predicted - required),
        }
    report = {
        "expected": len(expected_ids),
        "predicted": len(actual_ids),
        "duplicate_count": len(actual_ids) - len(actual_set),
        "missing": sorted(expected_ids - actual_set),
        "unexpected": sorted(actual_set - expected_ids),
        "mismatched_identity": sorted(mismatched),
        "by_league": by_league,
    }
    report["passed"] = not any((
        report["duplicate_count"], report["missing"], report["unexpected"],
        report["mismatched_identity"],
    ))
    return report


def require_real_cutoff(as_of: datetime, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    if as_of.weekday() != 3:
        raise RuntimeError("frozen slate cutoff must be Thursday UTC")
    if not as_of <= now <= as_of + MAX_FREEZE_DELAY:
        raise RuntimeError(
            "a Thursday-frozen slate must be generated within 30 minutes of its real cutoff; "
            "retrospective research must use a different, explicitly non-frozen label"
        )
