"""Drain the re-scrape queue at the start of every scraper run.

Why this exists. A fixture whose event feed is truncated is worse than one that
is missing: mv_match_length derives length from the events themselves, and
mv_player_minutes scales each spell by 90.0/length_min, so a feed that stops at
minute 50 credits every player a full 90 of exposure against a numerator that
stopped halfway. Every per-90 for those players is diluted and the percentile
pools they sit in are depressed with them, silently.

So the pipeline pulls the fixture out of the metrics layer, records it here, and
fetches it again. Nothing is left for a human to notice.

Credentials come from get_supabase() in scrape_and_load, which reads
SUPABASE_URL and SUPABASE_SERVICE_KEY from the .env at the repo root. No key
belongs in this file.

Wiring, in pipeline/scrape_league.py main(), immediately after the scraper is
built and before the normal backfill loop:

    from rescrape_queue import drain_rescrape_queue
    drain_rescrape_queue(scraper, limit=10)
"""
from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path, PurePosixPath
from typing import Any

import pandas as pd

from scrape_and_load import (
    cached_event_json_path,
    get_scraper,
    get_supabase,
    upsert_match,
    upsert_events,
    upsert_players_and_lineups,
)


def _claim_rows(client: Any, limit: int, game_ids: list[str] | None) -> list[dict]:
    if game_ids:
        return (
            client.rpc("claim_rescrape_games", {"p_game_ids": game_ids})
            .execute()
            .data
            or []
        )
    return (
        client.rpc("claim_rescrape_batch", {"p_limit": limit}).execute().data or []
    )


def _source_game_id(client: Any, game_id: str) -> str:
    """Resolve a canonical fixture id to the WhoScored id in its raw archive."""
    rows = (
        client.table("archive_match_manifest")
        .select("object_path")
        .eq("game_id", game_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        if game_id.isdigit():
            return game_id
        raise ValueError(f"no archive manifest maps canonical game {game_id}")
    filename = PurePosixPath(rows[0]["object_path"]).name
    if not filename.endswith(".json.gz"):
        raise ValueError(f"unexpected archive object path for {game_id}: {filename}")
    source_id = filename.removesuffix(".json.gz")
    if not source_id.isdigit():
        raise ValueError(f"archive source id is not numeric for {game_id}: {source_id}")
    return source_id


def _fixture_scope(client: Any, game_id: str) -> tuple[str, str]:
    rows = (
        client.table("matches")
        .select("league,season")
        .eq("game_id", game_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise ValueError(f"canonical match row is missing for {game_id}")
    return str(rows[0]["league"]), str(rows[0]["season"])


def _queued_fixture_scope(client: Any, source_id: str) -> tuple[str, str]:
    """A failed source ID can precede the canonical match-row upsert."""
    queue = (
        client.table("rescrape_queue")
        .select("league")
        .eq("game_id", source_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not queue:
        raise ValueError(f"no queued scope for source game {source_id}")
    league = str(queue[0]["league"])
    registry = (
        client.table("leagues")
        .select("season")
        .eq("league", league)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not registry or not registry[0].get("season"):
        raise ValueError(f"no registered season for queued source game {source_id}")
    return league, str(registry[0]["season"])


def _canonicalize_missing_fixture(
    client: Any, game_data: dict, source_id: str, league: str, season: str
) -> str:
    """Match the direct match-centre payload to exactly one scheduled fixture."""
    home = game_data.get("home") or {}
    away = game_data.get("away") or {}
    date = str(game_data.get("startDate") or game_data.get("startTime") or "")[:10]
    home_name, away_name = home.get("name"), away.get("name")
    if not date or not home_name or not away_name:
        raise ValueError(f"match-centre metadata is incomplete for {source_id}")
    rows = (
        client.table("matches")
        .select("game_id,home_team,away_team")
        .eq("league", league)
        .eq("season", season)
        .eq("date", date)
        .execute()
        .data
        or []
    )
    aliases = (
        client.table("team_names")
        .select("match_name,event_name,display_name")
        .eq("league", league)
        .execute()
        .data
        or []
    )

    def same_team(left: str, right: str) -> bool:
        if not left or not right:
            return False
        a, b = str(left).strip().casefold(), str(right).strip().casefold()
        if a == b:
            return True
        return any(
            a in names and b in names
            for row in aliases
            if (names := {
                str(value).strip().casefold()
                for value in (row.get("match_name"), row.get("event_name"), row.get("display_name"))
                if value
            })
        )

    matches = [
        row for row in rows
        if same_team(home_name, row.get("home_team"))
        and same_team(away_name, row.get("away_team"))
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one canonical fixture for source {source_id}; found {len(matches)}"
        )
    canonical_id = str(matches[0]["game_id"])

    def score(side: dict) -> int | None:
        scores = side.get("scores") or {}
        value = scores.get("fulltime", scores.get("running"))
        return int(value) if value is not None else None

    fixture = pd.Series({
        "game_id": canonical_id,
        "date": date,
        "home_team": matches[0]["home_team"],
        "away_team": matches[0]["away_team"],
        "home_score": score(home),
        "away_score": score(away),
        "week": None,
        "venue": game_data.get("venueName"),
    })
    upsert_match(client, fixture, league, season)
    return canonical_id


def _fetch_event_payload(scraper: Any, source_id: str, league: str, season: str) -> dict:
    """Fetch one WhoScored match without refreshing its season calendar."""
    path = cached_event_json_path(scraper, source_id, league, season)
    path.parent.mkdir(parents=True, exist_ok=True)
    reader = scraper.get(
        f"https://www.whoscored.com/Matches/{source_id}/Live",
        path,
        var="require.config.params['args'].matchCentreData",
        no_cache=True,
    )
    reader.seek(0)
    payload = json.load(reader)
    if not isinstance(payload, dict) or not payload.get("events"):
        raise ValueError(f"provider returned no usable event payload for {source_id}")
    return payload


def _last_event_minute(game_data: dict) -> int:
    minutes = []
    for event in game_data.get("events", []):
        value = event.get("expandedMinute", event.get("minute"))
        try:
            minutes.append(int(value))
        except (TypeError, ValueError):
            continue
    return max(minutes, default=0)


def _prune_stale_events(
    client: Any, game_id: str, provider_event_ids: set[int]
) -> int:
    rows = []
    offset = 0
    while True:
        page = (client.table("events").select("ws_id").eq("game_id", game_id)
                .order("id").range(offset, offset + 999).execute().data or [])
        rows.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    stored_ids = {int(row["ws_id"]) for row in rows if row.get("ws_id") is not None}
    stale_ids = sorted(stored_ids - provider_event_ids)
    for offset in range(0, len(stale_ids), 200):
        client.table("events").delete().eq("game_id", game_id).in_(
            "ws_id", stale_ids[offset : offset + 200]
        ).execute()
    return len(stale_ids)


def _refresh_canonical_fixture(
    client: Any, game_id: str, *, reuse_cache: bool = False
) -> tuple[int, str]:
    """Fetch a fresh provider feed and retain the existing canonical identity."""
    scraper = None
    try:
        try:
            league, season = _fixture_scope(client, game_id)
            canonical_id = game_id
            source_id = _source_game_id(client, game_id)
        except ValueError:
            if not game_id.isdigit():
                raise
            league, season = _queued_fixture_scope(client, game_id)
            source_id = game_id
            canonical_id = None
        # A direct match-centre fetch works even when the provider's season
        # calendar is unavailable. A fresh request bypasses the truncated cache.
        if reuse_cache:
            path = (
                Path.home()
                / "soccerdata"
                / "data"
                / "WhoScored"
                / "events"
                / f"{league}_{season}"
                / f"{source_id}.json"
            )
            with path.open(encoding="utf-8") as handle:
                game_data = json.load(handle)
        else:
            scraper = get_scraper(league, season, headless=False)
            game_data = _fetch_event_payload(scraper, source_id, league, season)
        provider_events = game_data.get("events", [])
        event_count = len(provider_events)
        provider_event_ids = {
            int(event["id"]) for event in provider_events if event.get("id") is not None
        }
        unique_event_count = len(provider_event_ids)
        last_minute = _last_event_minute(game_data)
        if event_count == 0 or last_minute < 80:
            raise ValueError(
                f"provider feed remains truncated: {event_count} events, "
                f"last minute {last_minute}"
            )
        if canonical_id is None:
            canonical_id = _canonicalize_missing_fixture(
                client, game_data, source_id, league, season
            )
            print(f"    -> mapped source {source_id} to canonical {canonical_id}")
        upsert_players_and_lineups(client, game_data, canonical_id, league)
        written = upsert_events(client, game_data, canonical_id, league)
        if written != unique_event_count:
            raise ValueError(
                "event write count mismatch: "
                f"provider_unique={unique_event_count}, written={written}"
            )
        pruned = _prune_stale_events(client, canonical_id, provider_event_ids)
        if pruned:
            print(f"    -> removed {pruned} stale event row(s)")
        return written, canonical_id
    finally:
        driver = getattr(scraper, "_driver", None) if scraper is not None else None
        if driver is not None:
            driver.quit()


def drain_rescrape_queue(
    scraper: Any = None,
    limit: int = 10,
    game_ids: list[str] | None = None,
    reuse_cache: bool = False,
) -> int:
    """Re-fetch every fixture the database has flagged as unusable.

    Claims a batch server side, which increments attempts before the work starts,
    so a crash mid-fetch still counts as an attempt and the fixture cannot retry
    forever. Three failures marks it exhausted and raises an alert.
    """
    client = get_supabase()
    try:
        claimed = _claim_rows(client, limit, game_ids)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 0

    if not claimed:
        print("rescrape queue: empty")
        return 0

    print(f"rescrape queue: {len(claimed)} fixture(s) to refetch")
    done = 0
    for row in claimed:
        game_id = row["game_id"]
        attempts = row.get("attempts")
        print(f"  refetching {game_id} (attempt {attempts})")
        ok, err = False, None
        try:
            written, canonical_id = _refresh_canonical_fixture(
                client, game_id, reuse_cache=reuse_cache
            )
            print(
                f"    -> refreshed {written} events for queued source {game_id} "
                f"under canonical {canonical_id}"
            )
            ok = True
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()

        try:
            result = client.rpc(
                "record_rescrape_result_canonical",
                {
                    "p_game_id": game_id,
                    "p_canonical_game_id": canonical_id if ok else game_id,
                    "p_ok": ok,
                    "p_error": err,
                },
            ).execute()
            print(f"    -> {result.data}")
            if ok:
                done += 1
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    return done


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--reuse-cache",
        action="store_true",
        help="Use the latest cached provider payload after a verified fresh fetch.",
    )
    parser.add_argument(
        "--game-id",
        action="append",
        dest="game_ids",
        help="Claim and repair only this canonical game id; repeat as needed.",
    )
    args = parser.parse_args()
    repaired = drain_rescrape_queue(
        limit=args.limit,
        game_ids=args.game_ids,
        reuse_cache=args.reuse_cache,
    )
    return 0 if repaired == len(args.game_ids or []) or not args.game_ids else 1


if __name__ == "__main__":
    raise SystemExit(main())
