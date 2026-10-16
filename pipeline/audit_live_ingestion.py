#!/usr/bin/env python3
"""Read-only health audit for active ingestion plus every top-five league."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import train_match_baselines as baseline


ROOT = Path(__file__).resolve().parents[1]


def day(value: Any) -> date:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def audit_league(
    registry: dict[str, Any], matches: list[dict[str, Any]], loaded_ids: set[str], today: date,
    provider_completed: list[dict[str, Any]] | None = None,
    rescrape_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    played = [row for row in matches if row.get("home_score") is not None and row.get("away_score") is not None]
    future = [row for row in matches if row.get("home_score") is None or row.get("away_score") is None]
    with_events = [row for row in played if str(row["game_id"]) in loaded_ids]
    missing = [str(row["game_id"]) for row in played if str(row["game_id"]) not in loaded_ids]
    future_clubs = sorted({str(row[k]) for row in future for k in ("home_team", "away_team") if row.get(k)})
    expected = int(registry.get("expected_teams") or 0)
    warnings = []
    active = registry.get("is_active") is not False
    if registry["league"] in baseline.TOP_FIVE and expected:
        season_total = expected * (expected - 1)
        if len(matches) != season_total:
            warnings.append(
                f"live fixture schedule has {len(matches)}/{season_total} expected matches"
            )
        pair_counts = Counter((str(row["home_team"]), str(row["away_team"])) for row in matches)
        duplicates = [pair for pair, count in pair_counts.items() if count > 1]
        if duplicates:
            warnings.append(f"live fixture schedule has {len(duplicates)} duplicate home/away pairing(s)")
    if not active and provider_completed:
        warnings.append(
            f"league is inactive although the provider knows {len(provider_completed)} completed fixture(s)"
        )
    if missing:
        warnings.append(f"{len(missing)} played fixture(s) have no events")
    if future and expected and len(future_clubs) < expected:
        warnings.append(
            f"future schedule covers only {len(future_clubs)}/{expected} expected clubs"
        )
    newest_played = max((day(row["date"]) for row in played), default=None)
    newest_events = max((day(row["date"]) for row in with_events), default=None)
    if newest_played and (newest_events is None or (today - newest_events).days > 7) and newest_played != newest_events:
        warnings.append(
            f"event feed lags known played schedule: played={newest_played} events={newest_events}"
        )
    provider_completed = provider_completed or []
    canonical_by_id = {str(row["game_id"]): row for row in matches}
    canonical_by_fixture = {
        (str(row["date"])[:10], str(row["home_team"]), str(row["away_team"])): row
        for row in matches
    }
    provider_gaps = []
    provider_with_events = 0
    for provider in provider_completed:
        row = canonical_by_id.get(str(provider.get("game_id"))) or canonical_by_fixture.get((
            str(provider.get("date"))[:10], str(provider.get("home_team")), str(provider.get("away_team")),
        ))
        label = (
            f"{provider.get('date')} {provider.get('home_team')} vs {provider.get('away_team')}"
        )
        if row is None:
            provider_gaps.append(f"missing canonical match: {label}")
            continue
        actual = (row.get("home_score"), row.get("away_score"))
        expected_score = (provider.get("home_score"), provider.get("away_score"))
        if actual != expected_score:
            provider_gaps.append(f"score mismatch or stale fixture: {label}")
        elif str(row["game_id"]) not in loaded_ids:
            provider_gaps.append(f"missing events: {label}")
        else:
            provider_with_events += 1
    if provider_gaps:
        warnings.append(
            f"independent provider knows {len(provider_completed)} completed fixture(s), "
            f"but only {provider_with_events} are canonical with events"
        )
    unresolved_queue = [
        row for row in (rescrape_rows or [])
        if row.get("league") == registry["league"]
        and row.get("status") in {"queued", "in_progress", "exhausted"}
    ]
    aged_queue = [
        row for row in unresolved_queue
        if row.get("status") == "exhausted"
        or (row.get("queued_at") and (today - day(row["queued_at"])).days >= 1)
    ]
    blocked_queue = [
        row for row in unresolved_queue
        if row in aged_queue or int(row.get("attempts") or 0) > 0
    ]
    if blocked_queue:
        warnings.append(
            f"{len(blocked_queue)} rescrape fixture(s) failed an attempt, are exhausted, "
            "or have been queued over a day; "
            "inspect rescrape_queue before declaring coverage healthy"
        )
    return {
        "league": registry["league"],
        "season": str(registry["season"]),
        "is_active": active,
        "played_fixtures": len(played),
        "played_with_events": len(with_events),
        "played_without_events": missing,
        "future_fixtures": len(future),
        "future_schedule_clubs": len(future_clubs),
        "expected_clubs": expected,
        "newest_played": newest_played.isoformat() if newest_played else None,
        "newest_events": newest_events.isoformat() if newest_events else None,
        "provider_completed_fixtures": len(provider_completed),
        "provider_completed_with_events": provider_with_events,
        "provider_completion_gaps": provider_gaps,
        "unresolved_rescrape_games": [str(row["game_id"]) for row in unresolved_queue],
        "blocked_rescrape_games": [str(row["game_id"]) for row in blocked_queue],
        "aged_rescrape_games": [str(row["game_id"]) for row in aged_queue],
        "warnings": warnings,
        "healthy": not warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "data_quality" / "live_ingestion_health.json")
    parser.add_argument(
        "--fixtures-file", type=Path,
        default=ROOT / "artifacts" / "fixtures" / "2627_football_data.json",
        help="Independent football-data.org snapshot used to detect a stale canonical database.",
    )
    parser.add_argument("--strict", action="store_true", help="exit nonzero when warnings exist")
    args = parser.parse_args()
    today = date.fromisoformat(args.as_of)
    db = baseline.db_client()
    provider_payload: dict[str, Any] = {}
    if args.fixtures_file and args.fixtures_file.is_file():
        provider_payload = json.loads(args.fixtures_file.read_text(encoding="utf-8"))
    provider_by_league: dict[str, list[dict[str, Any]]] = {}
    for row in provider_payload.get("completed_fixtures", []):
        provider_by_league.setdefault(str(row.get("league")), []).append(row)
    registry_rows = baseline.fetch_pages(
        db.table("leagues")
        .select("league,season,expected_teams,is_active")
        .order("league")
    )
    registry = [
        row for row in registry_rows
        if row.get("is_active") or row.get("league") in baseline.TOP_FIVE
    ]
    rescrape_rows = baseline.fetch_pages(
        db.table("rescrape_queue")
        .select("game_id,league,status,queued_at,attempts")
        .in_("status", ["queued", "in_progress", "exhausted"])
    )
    results = []
    for league in registry:
        matches = baseline.fetch_pages(
            db.table("matches")
            .select("game_id,date,home_team,away_team,home_score,away_score")
            .eq("league", league["league"])
            .eq("season", league["season"])
            .eq("is_live_scope", True)
            .order("date")
            .order("game_id")
        )
        loaded = db.rpc(
            "historical_loaded_game_ids",
            {"p_league": league["league"], "p_season": league["season"]},
        ).execute().data or []
        result = audit_league(
            league, matches, {str(row["game_id"]) for row in loaded}, today,
            provider_by_league.get(str(league["league"]), []),
            rescrape_rows,
        )
        # Event existence is not completeness. Inspect the bounded current-
        # season metric lengths too; do not describe a 25-minute feed as healthy.
        ids = [str(row["game_id"]) for row in matches if day(row["date"]) < today]
        short = []
        for offset in range(0, len(ids), 100):
            lengths = (db.table("mv_match_length").select("game_id,length_min")
                       .in_("game_id", ids[offset:offset + 100]).lt("length_min", 80)
                       .execute().data or [])
            short.extend(lengths)
        result["short_metric_feeds"] = short
        if short:
            result["healthy"] = False
            result["warnings"].append(
                f"{len(short)} settled-date metric feed(s) under 80 minutes; review completion/abandonment"
            )
        results.append(result)
    payload = {
        "as_of": today.isoformat(),
        "league_count": len(results),
        "provider_snapshot": str(args.fixtures_file) if provider_payload else None,
        "provider_snapshot_generated_at": provider_payload.get("generated_at"),
        "healthy_leagues": sum(row["healthy"] for row in results),
        "leagues": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for row in results:
        marker = "PASS" if row["healthy"] else "WARN"
        print(
            f"{marker} {row['league']}: played={row['played_with_events']}/{row['played_fixtures']} "
            f"future_clubs={row['future_schedule_clubs']}/{row['expected_clubs']}"
        )
        for warning in row["warnings"]:
            print(f"  - {warning}")
    print(f"Live ingestion report: {args.output}")
    return 1 if args.strict and any(not row["healthy"] for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
