#!/usr/bin/env python3
"""Synchronize top-five domestic future fixtures from football-data.org.

Dry-run is the default. Pass ``--execute`` to upsert unresolved future matches
into ``public.matches``. Provider IDs are namespaced so they cannot collide
with WhoScored IDs; ``scrape_and_load.py`` later reuses these canonical rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from supabase import Client, create_client


ROOT = Path(__file__).resolve().parents[1]
COMPETITIONS = {
    "ENG-Premier League": "PL",
    "ESP-La Liga": "PD",
    "ITA-Serie A": "SA",
    "GER-Bundesliga": "BL1",
    "FRA-Ligue 1": "FL1",
}
EXPECTED_LEAGUE_FIXTURES = {
    "ENG-Premier League": 380,
    "ESP-La Liga": 380,
    "ITA-Serie A": 380,
    "GER-Bundesliga": 306,
    "FRA-Ligue 1": 306,
}
ALIASES = {
    "paris saint germain": "Paris Saint-Germain",
    "internazionale milano": "Inter",
    "milan": "Milan",
    "hellas verona": "Verona",
    "1 koeln": "FC Koln",
    "rc deportivo la coruna": "Deportivo de A Coruna",
    "deportivo la coruna": "Deportivo de A Coruna",
    "rcd espanyol de barcelona": "Espanyol",
    "borussia monchengladbach": "Borussia M.Gladbach",
    "bayern munchen": "Bayern Munich",
    "schalke 04": "Schalke 04",
    "sc paderborn 07": "Paderborn",
    "sv 07 elversberg": "Elversberg",
    "olympique lyonnais": "Lyon",
    "stade brestois 29": "Brest",
    "stade rennais 1901": "Rennes",
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"\b(fc|cf|afc|calcio|club)\b", " ", value.lower())
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def api_start_year(season: str) -> int:
    if not re.fullmatch(r"\d{4}", season):
        raise ValueError("season must use YYZZ format, for example 2627")
    return 2000 + int(season[:2])


def db_client() -> Client:
    import os

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY are required")
    return create_client(url, key)


def fetch_api_matches(token: str, code: str, year: int) -> list[dict[str, Any]]:
    response = None
    for attempt in range(2):
        response = requests.get(
            f"https://api.football-data.org/v4/competitions/{code}/matches",
            params={"season": year},
            headers={"X-Auth-Token": token},
            timeout=45,
        )
        if response.status_code != 429 or attempt:
            break
        retry_after = min(max(int(response.headers.get("Retry-After", "60")), 1), 60)
        print(f"football-data.org rate limit reached; retrying {code} in {retry_after}s")
        time.sleep(retry_after)
    assert response is not None
    if response.status_code == 403:
        raise RuntimeError(f"football-data.org plan does not grant competition {code}")
    if response.status_code == 429:
        raise RuntimeError("football-data.org rate limit remained active after one retry")
    response.raise_for_status()
    # The API payload is UTF-8 even when its Content-Type omits a charset.
    response.encoding = "utf-8"
    return list(response.json().get("matches", []))


def canonical_teams(db: Client, league: str, season: str) -> set[str]:
    current_rows = (
        db.table("matches")
        .select("home_team,away_team")
        .eq("league", league)
        .eq("season", season)
        .execute()
        .data
        or []
    )
    historical_rows = (
        db.table("matches")
        .select("home_team,away_team")
        .eq("league", league)
        .execute()
        .data
        or []
    )
    name_rows = (
        db.table("team_names")
        .select("match_name")
        .eq("league", league)
        .execute()
        .data
        or []
    )
    teams = {
        str(name).strip()
        for row in current_rows + historical_rows
        for name in (row.get("home_team"), row.get("away_team"))
        if name
    }
    teams.update(str(row["match_name"]).strip() for row in name_rows if row.get("match_name"))
    return teams


def resolve_team(provider_name: str, teams: set[str]) -> str:
    alias = ALIASES.get(normalize(provider_name))
    if alias:
        return alias
    wanted = normalize(provider_name)
    matches = sorted(team for team in teams if normalize(team) == wanted)
    if len(matches) == 1:
        return matches[0]
    # Providers often append a location suffix ("Town", "City", "United")
    # that WhoScored omits. Accept containment only when it produces one clear
    # canonical club; ambiguous cases must still be explicitly aliased.
    contained = sorted(
        team
        for team in teams
        if len(normalize(team)) >= 4
        and (
            f" {normalize(team)} " in f" {wanted} "
            or f" {wanted} " in f" {normalize(team)} "
        )
    )
    if len(contained) == 1:
        return contained[0]
    provider_tokens = set(wanted.split())
    token_matches = sorted(
        team
        for team in teams
        if len(normalize(team)) >= 4
        and set(normalize(team).split()).issubset(provider_tokens)
    )
    if len(token_matches) == 1:
        return token_matches[0]
    raise RuntimeError(
        f"unmapped football-data.org team {provider_name!r}; add an explicit ALIASES entry"
    )


def build_row(
    match: dict[str, Any], league: str, season: str, teams: set[str], *, include_score: bool = False
) -> dict[str, Any]:
    kickoff = datetime.fromisoformat(str(match["utcDate"]).replace("Z", "+00:00")).astimezone(UTC)
    return {
        "game_id": f"fd-{match['id']}",
        "season": season,
        "competition": league,
        "league": league,
        "date": kickoff.date().isoformat(),
        "kickoff_at": kickoff.isoformat(),
        "home_team": resolve_team(str(match["homeTeam"]["name"]), teams),
        "away_team": resolve_team(str(match["awayTeam"]["name"]), teams),
        "home_score": provider_score(match, "home") if include_score else None,
        "away_score": provider_score(match, "away") if include_score else None,
        "matchday": match.get("matchday"),
        "provider_status": match.get("status"),
        "venue": match.get("venue"),
    }


def is_future_fixture(match: dict[str, Any], now: datetime) -> bool:
    status = str(match.get("status") or "")
    if status == "CANCELLED":
        return False
    kickoff = datetime.fromisoformat(str(match["utcDate"]).replace("Z", "+00:00")).astimezone(UTC)
    # Kickoff is the durable selector. Some 2026 provider rows currently carry
    # an ISO timestamp in `status`; relying only on the enum would drop them.
    return kickoff > now or status in {"POSTPONED", "SUSPENDED"}


def provider_score(match: dict[str, Any], side: str) -> int | None:
    value = ((match.get("score") or {}).get("fullTime") or {}).get(side)
    return int(value) if value is not None else None


def is_completed_fixture(match: dict[str, Any]) -> bool:
    # football-data.org can leave a placeholder 0-0 score on postponed rows.
    # Treating those placeholders as results creates a false canonical/event
    # coverage gap and can block an otherwise healthy forecast run.
    status = str(match.get("status") or "").upper()
    return (
        status in {"FINISHED", "AWARDED"}
        and provider_score(match, "home") is not None
        and provider_score(match, "away") is not None
    )


def database_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return only canonical match columns; provider metadata stays in snapshot."""
    return {key: value for key, value in row.items() if not key.startswith("provider_")}


def fixture_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    """A league season has one fixture for each ordered team pairing."""
    return (str(row["league"]), str(row["season"]), str(row["home_team"]), str(row["away_team"]))


def existing_fixtures(db: Client, league: str, season: str) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    rows = (
        db.table("matches")
        .select("game_id,season,league,home_team,away_team,home_score,away_score")
        .eq("league", league)
        .eq("season", season)
        .execute()
        .data
        or []
    )
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(fixture_key(row), []).append(row)
    canonical = {}
    for key, candidates in grouped.items():
        who_scored = [row for row in candidates if not str(row["game_id"]).startswith("fd-")]
        if len(who_scored) > 1 or (not who_scored and len(candidates) > 1):
            raise RuntimeError(f"ambiguous canonical fixture identity for {key}: "
                               f"{[row['game_id'] for row in candidates]}")
        canonical[key] = (who_scored or candidates)[0]
    return canonical


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2627")
    parser.add_argument("--league", action="append", choices=sorted(COMPETITIONS))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    import os

    token = os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()
    if not token:
        raise RuntimeError("FOOTBALL_DATA_API_KEY is missing from .env")

    db = db_client()
    selected = args.league or list(COMPETITIONS)
    all_rows: list[dict[str, Any]] = []
    completed_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    provider_match_counts: dict[str, int] = {}
    now = datetime.now(UTC)
    for league in selected:
        teams = canonical_teams(db, league, args.season)
        known_fixtures = existing_fixtures(db, league, args.season)
        if not teams:
            raise RuntimeError(f"no canonical {args.season} teams found for {league}")
        matches = fetch_api_matches(token, COMPETITIONS[league], api_start_year(args.season))
        provider_match_counts[league] = len(matches)
        if len(matches) != EXPECTED_LEAGUE_FIXTURES[league]:
            raise RuntimeError(
                f"{league} provider schedule has {len(matches)} matches; expected "
                f"{EXPECTED_LEAGUE_FIXTURES[league]}. Refusing a partial fixture manifest."
            )
        future = [match for match in matches if is_future_fixture(match, now)]
        completed = [match for match in matches if is_completed_fixture(match)]
        included_ids = {str(match['id']) for match in future + completed}
        excluded_rows.extend({
            'game_id': f"fd-{match['id']}", 'league': league,
            'provider_status': match.get('status'), 'kickoff_at': match.get('utcDate'),
            'reason': 'not eligible as future or completed at capture',
        } for match in matches if str(match['id']) not in included_ids)
        provider_names = {
            str(match[side]["name"])
            for match in future + completed
            for side in ("homeTeam", "awayTeam")
        }
        unmapped: list[str] = []
        for provider_name in sorted(provider_names):
            try:
                resolve_team(provider_name, teams)
            except RuntimeError:
                unmapped.append(provider_name)
        if unmapped:
            raise RuntimeError(
                f"{league} has {len(unmapped)} unmapped football-data.org teams: "
                + ", ".join(repr(name) for name in unmapped)
            )
        rows = []
        provider_keys: set[tuple[str, str, str, str]] = set()
        for match in future:
            row = build_row(match, league, args.season, teams)
            key = fixture_key(row)
            if key in provider_keys:
                raise RuntimeError(f"provider returned duplicate league fixture {key}")
            provider_keys.add(key)
            existing = known_fixtures.get(key)
            if existing and str(existing["game_id"]) != row["game_id"]:
                row["provider_game_id"] = row["game_id"]
                row["game_id"] = str(existing["game_id"])
            row["provider_status"] = match.get("status")
            row["provider_updated_at"] = match.get("lastUpdated")
            rows.append(row)
        all_rows.extend(rows)
        for match in completed:
            row = build_row(match, league, args.season, teams, include_score=True)
            row["provider_status"] = match.get("status")
            row["provider_updated_at"] = match.get("lastUpdated")
            completed_rows.append(row)
        print(
            f"{league}: provider={len(matches)} completed={len(completed)} "
            f"future={len(rows)} teams={len(teams)}"
        )

    output = args.output or ROOT / "artifacts" / "fixtures" / f"{args.season}_football_data.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": "football-data.org",
        "season": args.season,
        "provider_match_counts": provider_match_counts,
        "fixtures": all_rows,
        "completed_fixtures": completed_rows,
        "excluded_fixtures": excluded_rows,
    }
    rendered = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    output.write_text(rendered, encoding="utf-8")
    print(f"Fixture snapshot: {output} sha256={hashlib.sha256(rendered.encode()).hexdigest()}")
    print(f"Fixture sync plan: season={args.season} rows={len(all_rows)} execute={args.execute}")
    if not args.execute:
        print("Dry run only; no Supabase rows written")
        return 0
    for offset in range(0, len(all_rows), 100):
        batch = [database_row(row) for row in all_rows[offset : offset + 100]]
        db.table("matches").upsert(
            batch, on_conflict="game_id"
        ).execute()
    print(f"Persisted {len(all_rows)} idempotent future fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
