"""Scrape WhoScored match events for a team and load into Supabase.

Usage:
    python pipeline/scrape_and_load.py                                          # all Arsenal PL 25/26
    python pipeline/scrape_and_load.py --league "INT-Champions League"          # Champions League
    python pipeline/scrape_and_load.py --league USA-MLS --season 2526 --team "Los Angeles FC"
    python pipeline/scrape_and_load.py --match-id 1821342                       # single match
    python pipeline/scrape_and_load.py --list                                   # list schedule only
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import soccerdata as sd
from dotenv import load_dotenv
from supabase import Client, create_client

from event_phase import event_is_open_play
from feed_validation import validate_completed_feed

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
DEFAULT_LEAGUE = "ENG-Premier League"
DEFAULT_SEASON = "2526"
SLEEP_BETWEEN_MATCHES = 8


def get_supabase() -> Client:
    # The default PostgREST client timeout is 5s, which is far too short for the
    # rebuild RPCs: refreshing a batch of materialized views takes tens of seconds
    # and grows with every league added. Raised well past anything we expect.
    try:
        from supabase.client import ClientOptions

        return create_client(
            SUPABASE_URL,
            SUPABASE_SERVICE_KEY,
            options=ClientOptions(postgrest_client_timeout=600),
        )
    except Exception:  # noqa: BLE001 - older client versions lack ClientOptions
        return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def get_scraper(league: str, season: str, headless: bool = False) -> sd.WhoScored:
    # headless defaults to False: WhoScored's Incapsula anti-bot tends to crash
    # the undetected-chromedriver session in headless mode.
    return sd.WhoScored(leagues=league, seasons=[season], headless=headless)


def _int_or_none(v: Any) -> int | None:
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
        return int(v)
    except (ValueError, TypeError):
        return None


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except TypeError:
        pass
    s = str(v)
    return s if s else None


def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def get_team_schedule(ws: sd.WhoScored, team: str) -> pd.DataFrame:
    schedule = ws.read_schedule()
    if schedule.index.names and any(n for n in schedule.index.names):
        schedule = schedule.reset_index()
    mask = schedule["home_team"].str.contains(team, na=False) | schedule[
        "away_team"
    ].str.contains(team, na=False)
    return schedule[mask].copy()


def match_payload(
    sched_row: pd.Series,
    league: str,
    season: str,
    *,
    game_id: str | None = None,
) -> dict[str, Any]:
    """Build the canonical matches row shared by event and schedule ingestion."""
    source_game_id = str(sched_row["game_id"])
    date_val = sched_row.get("date")
    try:
        date_str = pd.to_datetime(date_val).date().isoformat() if date_val is not None else None
    except Exception:
        date_str = str(date_val) if date_val is not None else None
    game_id = game_id or source_game_id
    home_team = _str_or_none(sched_row.get("home_team"))
    away_team = _str_or_none(sched_row.get("away_team"))
    return {
        "game_id": game_id,
        "season": season,
        "competition": league,
        "league": league,
        "date": date_str,
        "home_team": home_team,
        "away_team": away_team,
        "home_score": _int_or_none(sched_row.get("home_score")),
        "away_score": _int_or_none(sched_row.get("away_score")),
        "matchday": _int_or_none(
            sched_row.get("week")
            if "week" in sched_row.index
            else sched_row.get("matchday")
        ),
        "venue": _str_or_none(sched_row.get("venue")),
    }


def upsert_match(sb: Client, sched_row: pd.Series, league: str, season: str) -> str:
    payload = match_payload(sched_row, league, season)
    date_str = payload["date"]
    home_team = payload["home_team"]
    away_team = payload["away_team"]
    if date_str and home_team and away_team:
        same_fixture = (
            sb.table("matches")
            .select("game_id")
            .eq("season", season)
            .eq("league", league)
            .eq("date", date_str)
            .eq("home_team", home_team)
            .eq("away_team", away_team)
            .execute()
            .data
            or []
        )
        numeric = [row for row in same_fixture if str(row["game_id"]).isdigit()]
        reserved = [row for row in same_fixture if str(row["game_id"]).startswith("fd-")]
        if len(numeric) > 1 or (not numeric and len(reserved) > 1):
            raise RuntimeError(
                f"ambiguous fixture identity for {home_team} vs {away_team} on {date_str}"
            )
        if numeric or reserved:
            payload["game_id"] = str((numeric or reserved)[0]["game_id"])
    sb.table("matches").upsert(payload, on_conflict="game_id").execute()
    return str(payload["game_id"])


def cached_event_json_path(ws: sd.WhoScored, game_id: str, league: str, season: str) -> Path:
    return ws.data_dir / "events" / f"{league}_{season}" / f"{game_id}.json"


def ensure_event_json(ws: sd.WhoScored, game_id: str, league: str, season: str) -> dict:
    path = cached_event_json_path(ws, game_id, league, season)
    if not path.is_file():
        # populate cache
        ws.read_events(match_id=int(game_id), output_fmt="raw")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _display_name(v: Any) -> str | None:
    if isinstance(v, dict):
        return v.get("displayName")
    return _str_or_none(v)


def upsert_players_and_lineups(
    sb: Client,
    game_data: dict,
    game_id: str,
    # Required, no default. A "USA-MLS" default here is the Python half of the
    # database default that silently wrote La Liga and Premier League rows as
    # MLS. Omitting league must be a TypeError, not a mislabelled fixture.
    league: str,
    write_shared_players: bool = True,
) -> None:
    team_names = {
        int(game_data["home"]["teamId"]): game_data["home"]["name"],
        int(game_data["away"]["teamId"]): game_data["away"]["name"],
    }
    player_names: dict[int, str] = {
        int(pid): name for pid, name in game_data.get("playerIdNameDictionary", {}).items()
    }

    # Assign each player to a team based on the first event we see them touch
    player_team: dict[int, int] = {}
    for ev in game_data.get("events", []):
        pid = ev.get("playerId")
        tid = ev.get("teamId")
        if pid is None or tid is None:
            continue
        if pid not in player_team:
            player_team[int(pid)] = int(tid)

    # If home/away include player lists with starter info, use them
    starters: dict[int, bool] = {}
    positions: dict[int, str | None] = {}
    shirts: dict[int, int | None] = {}
    for side in ("home", "away"):
        side_data = game_data.get(side, {})
        for p in side_data.get("players", []) or []:
            pid = p.get("playerId")
            if pid is None:
                continue
            pid = int(pid)
            starters[pid] = not bool(p.get("isFirstEleven") is False)
            if "isFirstEleven" in p:
                starters[pid] = bool(p["isFirstEleven"])
            positions[pid] = p.get("position")
            shirts[pid] = _int_or_none(p.get("shirtNo"))

    players_payload: list[dict] = []
    lineups_payload: list[dict] = []
    seen_players: set[str] = set()

    for pid_int, name in player_names.items():
        tid = player_team.get(pid_int)
        team = team_names.get(tid) if tid is not None else None
        pid_str = str(pid_int)
        if pid_str not in seen_players:
            players_payload.append(
                {"player_id": pid_str, "player_name": name, "team": team}
            )
            seen_players.add(pid_str)
        lineups_payload.append(
            {
                "game_id": game_id,
                "player_id": pid_str,
                "team": team or "unknown",
                "is_starter": starters.get(pid_int, True),
                "position": positions.get(pid_int),
                "shirt_number": shirts.get(pid_int),
            }
        )

    for _r in lineups_payload:
        _r["league"] = league
    # Historical matches must never move a present-day player back to an old
    # club. Events retain player names and lineups retain player IDs, so the
    # training archive does not need to mutate this current identity table.
    if players_payload and write_shared_players:
        sb.table("players").upsert(players_payload, on_conflict="player_id").execute()
    # lineups has no unique constraint; clear + reinsert for idempotency
    sb.table("lineups").delete().eq("game_id", game_id).execute()
    for i in range(0, len(lineups_payload), 500):
        sb.table("lineups").insert(lineups_payload[i : i + 500]).execute()


def build_event_row(
    game_id: str,
    ev: dict,
    team_names: dict[int, str],
    player_names: dict[int, str],
) -> dict:
    pid = ev.get("playerId")
    tid = ev.get("teamId")
    return {
        "game_id": game_id,
        "ws_id": _int_or_none(ev.get("id")),
        "event_id": _int_or_none(ev.get("eventId")),
        "period": _int_or_none(
            ev["period"].get("value") if isinstance(ev.get("period"), dict) else ev.get("period")
        ),
        "minute": _int_or_none(ev.get("minute")),
        "second": _int_or_none(ev.get("second")),
        "expanded_minute": _int_or_none(ev.get("expandedMinute")),
        "team_id": str(tid) if tid is not None else None,
        "team": team_names.get(int(tid)) if tid is not None else None,
        "player_id": str(pid) if pid is not None else None,
        "player": player_names.get(int(pid)) if pid is not None else None,
        "type": _display_name(ev.get("type")),
        "outcome_type": _display_name(ev.get("outcomeType")),
        "x": _float_or_none(ev.get("x")),
        "y": _float_or_none(ev.get("y")),
        "end_x": _float_or_none(ev.get("endX")),
        "end_y": _float_or_none(ev.get("endY")),
        "is_touch": bool(ev.get("isTouch", False)),
        "is_shot": bool(ev.get("isShot", False)),
        "is_goal": bool(ev.get("isGoal", False)),
        "card_type": _display_name(ev.get("cardType")),
        "qualifiers": ev.get("qualifiers") or [],
        "is_open_play": event_is_open_play(ev.get("qualifiers")),
    }


def upsert_events(sb: Client, game_data: dict, game_id: str, league: str) -> int:
    team_names = {
        int(game_data["home"]["teamId"]): game_data["home"]["name"],
        int(game_data["away"]["teamId"]): game_data["away"]["name"],
    }
    player_names = {
        int(pid): name
        for pid, name in game_data.get("playerIdNameDictionary", {}).items()
    }
    rows_by_wsid: dict[int, dict] = {}
    for ev in game_data.get("events", []):
        if ev.get("id") is None:
            continue
        row = build_event_row(game_id, ev, team_names, player_names)
        rows_by_wsid[row["ws_id"]] = row  # last-write wins for duplicates
    rows = list(rows_by_wsid.values())
    for _r in rows:
        _r["league"] = league
    if not rows:
        return 0
    for i in range(0, len(rows), 500):
        chunk = rows[i : i + 500]
        sb.table("events").upsert(chunk, on_conflict="game_id,ws_id").execute()
    return len(rows)


_WHITELIST_CACHE: dict[str, set[str]] = {}
_EXPECTED_CACHE: dict[str, int] = {}
_CLUBCOUNT_CACHE: dict[str, int] = {}


def league_whitelist(sb: Client, league: str) -> set[str]:
    """Team names registered for THIS league. Empty set means the league is new."""
    if league in _WHITELIST_CACHE:
        return _WHITELIST_CACHE[league]
    names: set[str] = set()
    try:
        res = (
            sb.table("team_names")
            .select("match_name, event_name, display_name")
            .eq("league", league)
            .execute()
        )
        for r in res.data or []:
            for key in ("match_name", "event_name", "display_name"):
                if r.get(key):
                    names.add(str(r[key]).strip())
    except Exception as e:  # noqa: BLE001 - a lookup failure must not corrupt data
        print(f"  !! could not read whitelist for {league}: {e}", file=sys.stderr, flush=True)
        raise
    _WHITELIST_CACHE[league] = names
    # rows, not names: each club contributes several name variants
    _CLUBCOUNT_CACHE[league] = len(res.data or [])
    return names


def league_club_count(sb: Client, league: str) -> int:
    """Number of clubs registered, not name variants.

    league_whitelist() returns event_name, match_name and display_name for every club, so
    its length is roughly three times the club count and cannot be compared to a squad
    total. MLS would read as 60+ clubs against an expected 30.
    """
    if league not in _CLUBCOUNT_CACHE:
        league_whitelist(sb, league)
    return _CLUBCOUNT_CACHE.get(league, 0)


def league_expected_clubs(sb: Client, league: str) -> int:
    """How many clubs the league should have once the whitelist is complete.

    A partially built whitelist must not be enforced. After one Premier League fixture the
    list held two clubs; after six La Liga matches it held twelve of twenty. Enforcing
    either would silently refuse every match involving a club not yet seen, and the scrape
    would report success while writing nothing.
    """
    if league in _EXPECTED_CACHE:
        return _EXPECTED_CACHE[league]
    n = 0
    try:
        res = sb.table("leagues").select("expected_teams").eq("league", league).execute()
        rows = res.data or []
        if rows and rows[0].get("expected_teams"):
            n = int(rows[0]["expected_teams"])
    except Exception:  # noqa: BLE001 - unknown size means do not enforce
        n = 0
    _EXPECTED_CACHE[league] = n
    return n


def process_match(
    sb: Client,
    ws: sd.WhoScored,
    sched_row: pd.Series,
    league: str,
    season: str,
    historical: bool = False,
) -> tuple[str, int]:
    # GUARD: refuse to write a match whose clubs are not registered to this league.
    # Fails OPEN only when the league has no whitelist yet, so a brand new league can
    # be bootstrapped from its first scrape. Everything else is refused.
    if not historical:
        allowed = league_whitelist(sb, league)
        expected = league_expected_clubs(sb, league)
        known = league_club_count(sb, league)
        # Enforce only when the whitelist is COMPLETE for that league. A fixed threshold does
        # not work: twelve clubs is complete for nobody and looks complete against a floor.
        if expected and known >= expected:
            home = str(sched_row.get("home_team") or "").strip()
            away = str(sched_row.get("away_team") or "").strip()
            unknown = [t for t in (home, away) if t and t not in allowed]
            if unknown:
                print(
                    f"  !! SKIPPED: {', '.join(unknown)} not registered to {league} "
                    f"({known}/{expected} clubs known). This match was not written.",
                    flush=True,
                )
                return "", 0

    source_game_id = str(sched_row["game_id"])
    game_data = ensure_event_json(ws, source_game_id, league, season)
    validate_completed_feed(game_data)
    game_id = upsert_match(sb, sched_row, league, season)
    print(f"  -> match row upserted (game_id={game_id})")
    print(f"  -> loaded raw json ({len(game_data.get('events', []))} events)")
    upsert_players_and_lineups(
        sb,
        game_data,
        game_id,
        league,
        write_shared_players=not historical,
    )
    n = upsert_events(sb, game_data, game_id, league)
    print(f"  -> upserted {n} events (league={league})")
    return game_id, n


def main() -> int:
    # Copy bundled league_dict.json to soccerdata config dir so custom leagues are recognised
    import shutil, pathlib
    src = pathlib.Path(__file__).parent / "league_dict.json"
    dst = pathlib.Path.home() / "soccerdata" / "config" / "league_dict.json"
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)
    p = argparse.ArgumentParser()
    p.add_argument("--league", type=str, default=DEFAULT_LEAGUE, help="league id (default: ENG-Premier League)")
    p.add_argument("--season", type=str, default=DEFAULT_SEASON, help="season code (default: 2526)")
    p.add_argument("--team", type=str, default="Arsenal", help="team name to filter (default: Arsenal)")
    p.add_argument("--match-id", type=str, help="scrape a single WhoScored match id")
    p.add_argument("--list", action="store_true", help="list team schedule and exit")
    p.add_argument("--headless", action="store_true", help="run browser headless (default: headful, which is needed to get past WhoScored's anti-bot)")
    args = p.parse_args()

    league = args.league
    season = args.season
    team = args.team

    sb = get_supabase()
    ws = get_scraper(league, season, headless=args.headless)

    print(f"Reading schedule for {league} {season}...")
    team_sched = get_team_schedule(ws, team)
    print(f"Found {len(team_sched)} {team} matches in schedule")

    if args.list:
        cols = [
            c
            for c in ("date", "home_team", "away_team", "home_score", "away_score", "game_id")
            if c in team_sched.columns
        ]
        print(team_sched[cols].to_string(index=False))
        return 0

    if args.match_id:
        match = team_sched[team_sched["game_id"].astype(str) == str(args.match_id)]
        if match.empty:
            print(f"match_id {args.match_id} not in {team} schedule", file=sys.stderr)
            return 1
        row = match.iloc[0]
        print(
            f"Scraping single match: {row.get('home_team')} vs {row.get('away_team')}"
        )
        process_match(sb, ws, row, league, season)
        return 0

    for idx, (_, row) in enumerate(team_sched.iterrows()):
        print(
            f"[{idx + 1}/{len(team_sched)}] {row.get('date')} {row.get('home_team')} vs {row.get('away_team')}"
        )
        try:
            process_match(sb, ws, row, league, season)
        except Exception as e:
            print(f"  !! failed: {e}", file=sys.stderr)
        if idx < len(team_sched) - 1:
            time.sleep(SLEEP_BETWEEN_MATCHES)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
