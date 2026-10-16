"""League-wide backfill: WhoScored -> Supabase.

Reads the league schedule ONCE, then scrapes every PLAYED match that is not
already loaded, one at a time, with a jittered pause between event reads to
stay under WhoScored's anti-bot rate limit.

Design notes (why it's built this way):
  * The block is rate-based, not volume-based. One schedule read up front, then
    a randomised 60-120s gap between per-match event reads, keeps us under it.
  * Idempotent + resumable. "Done" is defined by rows existing in the events
    table inside the requested league and season, NOT by the local JSON cache.
    Re-running only scrapes what's still missing, so an interrupted run resumes.
  * Null cache files (written when a read is blocked) are purged before each
    match so a prior failure re-fetches instead of re-reading an empty file.
  * A consecutive-failure circuit breaker stops the run if we look blocked,
    rather than failing every remaining match for hours. Resume later.

Usage:
  python pipeline/scrape_league.py --list                 # show the plan, scrape nothing
  python pipeline/scrape_league.py                        # backfill all missing played matches
  python pipeline/scrape_league.py --limit 5             # do only the next 5 (good first test)
  python pipeline/scrape_league.py --min-gap 45 --max-gap 90
"""
from __future__ import annotations

import argparse
import pathlib
import random
import shutil
import sys
import time

import traceback

import pandas as pd

# Reuse the battle-tested single-match machinery. Importing is safe: that module
# is guarded by `if __name__ == "__main__"`, so nothing runs on import.
from rescrape_queue import drain_rescrape_queue
from scraper_heartbeat import heartbeat
from scrape_and_load import (
    cached_event_json_path,
    get_scraper,
    get_supabase,
    league_club_count,
    league_expected_clubs,
    league_whitelist,
    match_payload,
    process_match,
)

DEFAULT_LEAGUE = "USA-MLS"
DEFAULT_SEASON = "2627"
NULL_CACHE_MAX_BYTES = 50  # a real event json is >100KB; anything tiny is a null/blocked write


def is_history_command(cmdline: list[str]) -> bool:
    return any(pathlib.Path(arg).name.lower() == "scrape_history.py" for arg in cmdline[1:])


def active_history_processes() -> list[int]:
    """Return same-user historical Python scrapers; inaccessible processes are ignored."""
    try:
        import psutil
    except ImportError as exc:  # a missing overlap guard is unsafe for unattended use
        raise RuntimeError("psutil is required for the historical/live scraper overlap guard") from exc
    found = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = str(process.info.get("name") or "").lower()
            command = list(process.info.get("cmdline") or [])
            if name.startswith("python") and is_history_command(command):
                found.append(int(process.info["pid"]))
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return sorted(found)


def install_league_dict() -> None:
    """Copy the bundled custom league_dict.json into soccerdata's config dir."""
    src = pathlib.Path(__file__).parent / "league_dict.json"
    dst = pathlib.Path.home() / "soccerdata" / "config" / "league_dict.json"
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)


def read_full_schedule(ws) -> pd.DataFrame:
    """Whole-league schedule as a flat DataFrame (one row per fixture)."""
    sched = ws.read_schedule()
    if sched.index.names and any(n for n in sched.index.names):
        sched = sched.reset_index()
    return sched


def purge_schedule_cache(ws, league: str, season: str) -> list[pathlib.Path]:
    """Remove only the selected league-season schedule cache, never event JSON."""
    matches_dir = pathlib.Path(ws.data_dir) / "matches"
    removed: list[pathlib.Path] = []
    if not matches_dir.is_dir():
        return removed
    prefix = f"{league}_{season}"
    for path in matches_dir.iterdir():
        if path.is_file() and (path.name == f"{prefix}.html" or path.name.startswith(f"{prefix}_")):
            path.unlink()
            removed.append(path)
    return removed


def played_matches(sched: pd.DataFrame) -> pd.DataFrame:
    """Fixtures that have actually been played (a real home_score)."""
    df = sched[sched["home_score"].notna()].copy()
    if "date" in df.columns:
        df = df.sort_values("date")
    return df


def loaded_game_ids(
    sb,
    historical: bool = False,
    league: str | None = None,
    season: str | None = None,
) -> set[str]:
    """game_ids that already have events in the requested publication scope."""
    if not league or not season:
        mode = "historical" if historical else "live"
        raise ValueError(f"{mode} resume detection requires league and season")
    # Despite its older name, this service-only RPC is safe for live ingestion:
    # it filters matches by league and season before checking event existence.
    # Avoid v_loaded_games here; its global DISTINCT scan grows with the entire
    # event archive and can hit the Data API statement timeout.
    resp = sb.rpc(
        "historical_loaded_game_ids",
        {"p_league": league, "p_season": season},
    ).execute()
    return {str(r["game_id"]) for r in (resp.data or [])}


def _fixture_key(row) -> tuple[str, str, str]:
    date_value = row.get("date")
    try:
        date_text = pd.to_datetime(date_value).date().isoformat()
    except Exception:  # noqa: BLE001 - malformed values should simply not match
        date_text = str(date_value or "")
    return (
        date_text,
        str(row.get("home_team") or "").strip(),
        str(row.get("away_team") or "").strip(),
    )


def schedule_payloads(
    sched: pd.DataFrame,
    existing: list[dict],
    league: str,
    season: str,
) -> list[dict]:
    """Return canonical rows for a full provider schedule without losing known scores."""
    by_id = {str(row["game_id"]): row for row in existing}
    reserved = {
        _fixture_key(row): str(row["game_id"])
        for row in existing
        if str(row.get("game_id", "")).startswith("fd-")
    }
    # Domestic round-robin pairings retain identity after kickoff/date changes.
    # Do not apply this to cups or MLS, where repeat pairings are legitimate.
    domestic = league in {"ENG-Premier League", "ESP-La Liga", "FRA-Ligue 1", "GER-Bundesliga", "ITA-Serie A"}
    pairings = {}
    for prior in existing:
        pairings.setdefault(_fixture_key(prior)[1:], []).append(prior)
    payloads: list[dict] = []
    for _, row in sched.iterrows():
        source_id = str(row.get("game_id") or "").strip()
        if not source_id:
            raise RuntimeError(f"{league} schedule contains a fixture without a game_id")
        canonical_id = reserved.get(_fixture_key(row), source_id)
        if domestic and source_id not in by_id:
            candidates = pairings.get(_fixture_key(row)[1:], [])
            if len(candidates) > 1:
                raise RuntimeError(f"ambiguous existing fixture pairing: {_fixture_key(row)[1:]}")
            if candidates:
                canonical_id = str(candidates[0]["game_id"])
        payload = match_payload(row, league, season, game_id=canonical_id)
        prior = by_id.get(canonical_id, {})
        # A transient partial provider response must never erase a published result.
        for field in ("home_score", "away_score", "matchday", "venue"):
            if payload.get(field) is None and prior.get(field) is not None:
                payload[field] = prior[field]
        payloads.append(payload)
    return payloads


def upsert_full_schedule(sb, sched: pd.DataFrame, league: str, season: str) -> int:
    """Persist the complete live schedule so the database is not one-club scoped."""
    whitelist = league_whitelist(sb, league)
    expected = league_expected_clubs(sb, league)
    if whitelist and league_club_count(sb, league) >= expected > 0:
        clubs = set(sched["home_team"].dropna().astype(str)) | set(
            sched["away_team"].dropna().astype(str)
        )
        foreign = sorted(clubs - whitelist)
        if foreign:
            raise RuntimeError(
                f"{league} schedule contains clubs outside its complete whitelist: "
                + ", ".join(foreign)
            )
    existing = (
        sb.table("matches")
        .select("game_id,date,home_team,away_team,home_score,away_score,matchday,venue")
        .eq("league", league)
        .eq("season", season)
        .execute()
        .data
        or []
    )
    rows = schedule_payloads(sched, existing, league, season)
    for i in range(0, len(rows), 500):
        sb.table("matches").upsert(rows[i : i + 500], on_conflict="game_id").execute()
    return len(rows)


def enqueue_failed_fixture(sb, game_id: str, league: str, reason: str) -> None:
    """Record a scrape failure in the re-scrape queue.

    Never raises. A fixture failing to scrape is already the bad path; the
    bookkeeping about it must not be able to make the run worse.
    """
    try:
        sb.rpc("enqueue_rescrape", {
            "p_game_id": game_id, "p_league": league, "p_reason": reason[:500],
        }).execute()
        print(f"  -> queued {game_id} for re-scrape", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  !! could not queue {game_id} for re-scrape: {e}",
              file=sys.stderr, flush=True)


def exhausted_game_ids(sb) -> set[str]:
    """Fixtures that have failed three times and already alerted.

    These are excluded from live scope by v_match_season_scope, so they
    contribute to no metric. They must also stop counting as missing, or a
    fixture WhoScored will never serve blocks the analytics rebuild forever.
    That is the shape of the failure that left the site on 1 September data for
    thirteen days, and it should not be reachable a second time by a different
    route.
    """
    try:
        rows = sb.table("v_rescrape_exhausted").select("game_id").execute().data or []
        return {str(r["game_id"]) for r in rows}
    except Exception as e:  # noqa: BLE001
        print(f"  !! could not read exhausted fixtures: {e}", file=sys.stderr, flush=True)
        return set()


def scrape_targets(sb, args, targets, scrape_fn=None) -> tuple[int, int, int, int]:
    """Run every target and return loaded, failed, remaining, and written events."""
    if scrape_fn is None:
        scrape_fn = scrape_one_league
    total_ok = total_failed = total_remaining = total_events = 0
    for league, season in targets:
        try:
            ok, failed, remaining, events = scrape_fn(sb, args, league, season)
        except Exception as e:  # noqa: BLE001 - isolate leagues in scheduled runs
            msg = str(e).strip().splitlines()[0] if str(e).strip() else repr(e)
            print(f"  !! {league} {season} aborted: {msg}", file=sys.stderr, flush=True)
            ok, failed, remaining, events = 0, 1, 1, 0
        total_ok += ok
        total_failed += failed
        total_remaining += remaining
        total_events += events
    return total_ok, total_failed, total_remaining, total_events


def purge_null_cache(ws, game_id: str, league: str, season: str) -> None:
    """Remove a null/blocked cache file so the match re-fetches from source."""
    path = cached_event_json_path(ws, game_id, league, season)
    try:
        if path.is_file() and path.stat().st_size < NULL_CACHE_MAX_BYTES:
            path.unlink()
    except OSError:
        pass


def fetch_leagues(sb, active_only: bool = True) -> list[dict]:
    """Leagues from the registry, optionally limited to live ingestion."""
    try:
        query = sb.table("leagues").select("league, display_name, season, is_active")
        if active_only:
            query = query.eq("is_active", True)
        res = query.execute()
        rows = res.data or []
    except Exception as e:  # noqa: BLE001
        print(f"Could not read the leagues registry ({e}); falling back to {DEFAULT_LEAGUE}.",
              file=sys.stderr, flush=True)
        rows = []
    if not rows:
        rows = [{"league": DEFAULT_LEAGUE, "display_name": "Major League Soccer",
                 "season": DEFAULT_SEASON}]
    rows.sort(key=lambda r: r["league"])
    return rows


def choose_leagues(sb, args) -> list[tuple[str, str]]:
    """Resolve which leagues to scrape: flags first, then an interactive menu."""
    registry = fetch_leagues(sb, active_only=not getattr(args, "historical", False))
    by_id = {r["league"]: r for r in registry}

    def with_season(lid: str) -> tuple[str, str]:
        reg = by_id.get(lid, {})
        return lid, (args.season or reg.get("season") or DEFAULT_SEASON)

    if args.all:
        return [with_season(r["league"]) for r in registry]

    if args.league:
        picked: list[str] = []
        for chunk in args.league:
            picked.extend([x.strip() for x in chunk.split(",") if x.strip()])
        unknown = [x for x in picked if x not in by_id]
        if unknown:
            print(f"Unknown league(s): {', '.join(unknown)}", file=sys.stderr, flush=True)
            print(f"Known: {', '.join(by_id)}", file=sys.stderr, flush=True)
            raise SystemExit(2)
        return [with_season(x) for x in picked]

    # non-interactive (Task Scheduler, cron): default rather than block on a prompt
    if not sys.stdin.isatty():
        return [with_season(DEFAULT_LEAGUE)]

    print("\nWhich league(s) do you want to scrape?\n", flush=True)
    for i, r in enumerate(registry, start=1):
        print(f"  {i}. {r['display_name']}  ({r['league']}, season {r.get('season') or DEFAULT_SEASON})",
              flush=True)
    print("  a. all of the above\n", flush=True)
    raw = input("Enter number(s), e.g. 1  or  1,3  or  a  [default 1]: ").strip().lower()

    if raw in ("a", "all"):
        return [with_season(r["league"]) for r in registry]
    if not raw:
        return [with_season(registry[0]["league"])]

    chosen: list[tuple[str, str]] = []
    for tok in raw.replace(" ", "").split(","):
        if not tok:
            continue
        if tok.isdigit() and 1 <= int(tok) <= len(registry):
            chosen.append(with_season(registry[int(tok) - 1]["league"]))
        elif tok in by_id:
            chosen.append(with_season(tok))
        else:
            print(f"Ignoring '{tok}' — not a listed option.", file=sys.stderr, flush=True)
    if not chosen:
        print("Nothing selected.", file=sys.stderr, flush=True)
        raise SystemExit(2)
    # de-duplicate, keep order
    seen, out = set(), []
    for c in chosen:
        if c[0] not in seen:
            out.append(c)
            seen.add(c[0])
    return out


def scrape_one_league(sb, args, league: str, season: str) -> tuple[int, int, int, int]:
    """Scrape one league and return loaded, failed, remaining, and written events."""
    print(f"\n{'=' * 62}", flush=True)
    print(f"  {league}  season {season}", flush=True)
    print(f"{'=' * 62}", flush=True)

    # opening the reader can fail too (unmapped league, bad season code), and one bad
    # league must never take down the other five
    try:
        ws = get_scraper(league, season, headless=args.headless)
    except Exception as e:  # noqa: BLE001
        msg = str(e).strip().splitlines()[0] if str(e).strip() else repr(e)
        print(f"  !! could not open {league}: {msg}", file=sys.stderr, flush=True)
        print("     (is it mapped to a WhoScored name in league_dict.json?)",
              file=sys.stderr, flush=True)
        if getattr(args, "historical", False):
            raise RuntimeError(f"could not open historical target {league} {season}") from e
        return 0, 0, 0, 0

    if getattr(args, "refresh_schedule", False):
        removed = purge_schedule_cache(ws, league, season)
        print(f"  refreshed schedule cache: removed {len(removed)} file(s)", flush=True)

    print(f"Reading full schedule for {league} {season}...", flush=True)
    try:
        sched = read_full_schedule(ws)
    except Exception as e:  # noqa: BLE001 - one bad league must not kill the rest
        print(f"  !! could not read schedule: {e}", file=sys.stderr, flush=True)
        print("     (usually means no fixtures published for that season yet)",
              file=sys.stderr, flush=True)
        raise RuntimeError(f"could not read schedule {league} {season}") from e

    if not getattr(args, "historical", False):
        written = upsert_full_schedule(sb, sched, league, season)
        print(f"  schedule fixtures : {written} synced", flush=True)

    played = played_matches(sched)
    if getattr(args, "historical", False) and played.empty:
        raise RuntimeError(f"historical schedule has no played fixtures: {league} {season}")
    expected_matches = getattr(args, "expected_matches", None)
    if expected_matches and len(played) != expected_matches:
        raise RuntimeError(
            f"historical schedule incomplete: {league} {season} has {len(played)} "
            f"played fixtures; expected {expected_matches}. Re-run with --refresh-schedule."
        )
    loaded = loaded_game_ids(
        sb,
        historical=getattr(args, "historical", False),
        league=league,
        season=season,
    )
    loaded_fixture_keys: set[tuple[str, str, str]] = set()
    if not getattr(args, "historical", False):
        reservations = (
            sb.table("matches")
            .select("game_id,date,home_team,away_team")
            .eq("league", league)
            .eq("season", season)
            .like("game_id", "fd-%")
            .execute()
            .data
            or []
        )
        loaded_fixture_keys = {
            _fixture_key(row) for row in reservations if str(row["game_id"]) in loaded
        }
    already_loaded = played.apply(
        lambda row: str(row.get("game_id")) in loaded or _fixture_key(row) in loaded_fixture_keys,
        axis=1,
    )
    todo = played[~already_loaded].copy()
    # Exhausted fixtures are known-bad and already alerted. Counting them as
    # missing would keep every run "incomplete" forever and keep the analytics
    # rebuild permanently skipped.
    exhausted = exhausted_game_ids(sb) if not getattr(args, "historical", False) else set()
    if exhausted:
        before = len(todo)
        todo = todo[~todo.apply(lambda r: str(r.get("game_id")) in exhausted, axis=1)].copy()
        if before != len(todo):
            print(f"  exhausted, skipped : {before - len(todo)}", flush=True)
    missing_total = len(todo)
    if args.limit and args.limit > 0:
        todo = todo.head(args.limit)

    n = len(todo)
    avg_gap = (args.min_gap + args.max_gap) / 2
    print(f"  played in schedule : {len(played)}", flush=True)
    print(f"  already loaded     : {len(played) - n if not args.limit else 'n/a'}", flush=True)
    print(f"  to scrape          : {n}", flush=True)
    if n:
        print(f"  est. runtime       : ~{round((n * avg_gap) / 60)} min", flush=True)

    if args.list:
        if n and getattr(args, "list_details", True):
            cols = [c for c in ("date", "home_team", "away_team", "home_score", "away_score", "game_id")
                    if c in todo.columns]
            print(todo[cols].to_string(index=False), flush=True)
        else:
            print("  nothing to do.", flush=True)
        return 0, 0, missing_total, 0
    if n == 0:
        print("  nothing to do — all played matches already loaded.", flush=True)
        return 0, 0, 0, 0

    succeeded = failed = consecutive = 0
    events = 0
    for i, (_, row) in enumerate(todo.iterrows(), start=1):
        stop_at = getattr(args, "stop_at_monotonic", None)
        if stop_at is not None and time.monotonic() >= stop_at:
            print("  nightly time budget reached; stopping cleanly.", flush=True)
            break
        gid = str(row.get("game_id"))
        print(f"[{i}/{n}] {row.get('date')} {row.get('home_team')} vs {row.get('away_team')} "
              f"(game_id={gid})", flush=True)
        purge_null_cache(ws, gid, league, season)
        try:
            game_id, n_events = process_match(
                sb,
                ws,
                row,
                league,
                season,
                historical=getattr(args, "historical", False),
            )
            if not game_id:
                raise RuntimeError("match was rejected before ingestion")
            print("  -> success", flush=True)
            succeeded += 1
            events += int(n_events or 0)
            consecutive = 0
        except Exception as e:  # noqa: BLE001
            print(f"  !! failed: {e}", file=sys.stderr, flush=True)
            # Put it somewhere the database can see. Until now a failed fixture
            # existed only as a line in a log file on one PC: counted in the run
            # summary, then forgotten. The re-scrape queue was already built and
            # already drained at the start of every run, and nothing was feeding
            # it scrape failures.
            enqueue_failed_fixture(sb, gid, league, f"{type(e).__name__}: {e}")
            failed += 1
            consecutive += 1
            if consecutive >= args.max_consecutive_failures:
                print(f"\n!! {consecutive} failures in a row for {league} — looks blocked. "
                      f"Moving on.", file=sys.stderr, flush=True)
                break
        if i < n:
            time.sleep(random.uniform(args.min_gap, args.max_gap))

    remaining = max(0, missing_total - succeeded)
    print(f"  {league}: {succeeded} loaded, {failed} failed, "
          f"{remaining} remaining, {events} events", flush=True)
    return succeeded, failed, remaining, events


def main() -> int:
    install_league_dict()

    p = argparse.ArgumentParser(description="Multi-league WhoScored -> Supabase backfill.")
    p.add_argument("--league", action="append",
                   help="league id; repeatable or comma-separated. Omit to be asked.")
    p.add_argument("--all", action="store_true", help="scrape every active league")
    p.add_argument("--season", default=None,
                   help="override the season code (default: whatever the registry says)")
    p.add_argument("--headless", action="store_true",
                   help="run browser headless (default: headful, needed to get past the anti-bot)")
    p.add_argument("--refresh-schedule", action="store_true",
                   help="discard only the selected schedule cache before reading fixtures")
    p.add_argument("--min-gap", type=float, default=60.0, help="min seconds between matches")
    p.add_argument("--max-gap", type=float, default=120.0, help="max seconds between matches")
    p.add_argument("--limit", type=int, default=0, help="only scrape the next N per league (0 = all)")
    # Windows Task Scheduler kills "MLS-Euro Analytics Scrape" at its
    # ExecutionTimeLimit of PT8H. The 13 September run took 7h28m for 131
    # fixtures, which is inside that limit by half an hour. A hard kill lands
    # mid-fixture, and because events are upserted in chunks of about 1,500 a
    # killed fixture keeps whatever prefix already landed. Events are ordered by
    # minute, so the prefix ends at a minute boundary, which is exactly the
    # signature of the truncated fixtures: 1952894 at 31 events, Como and Torino
    # stopping around minute 50. A truncated upstream feed would not truncate so
    # tidily.
    #
    # scrape_history.py already had a budget and the live path had none. This
    # stops cleanly between fixtures with room to spare, so the kill is never
    # reached. Task Scheduler settings belong to Jack; this does not need them
    # changed.
    p.add_argument("--time-budget-mins", type=float, default=360.0,
                   help="stop cleanly between fixtures after this many minutes "
                        "(0 = unbounded). Default 360 leaves two hours of head "
                        "room under the scheduled task's 8 hour kill limit.")
    p.add_argument("--max-consecutive-failures", type=int, default=5,
                   help="give up on a league after this many failures in a row")
    p.add_argument("--list", action="store_true", help="print the plan and exit without scraping")
    p.add_argument("--no-rebuild", action="store_true", help="skip the analytics rebuild afterwards")
    p.add_argument("--historical", action="store_true",
                   help="archive mode: preserve current player teams and never rebuild live analytics")
    args = p.parse_args()

    if args.historical:
        args.no_rebuild = True
    else:
        history_pids = active_history_processes()
        if history_pids:
            print(
                "REFUSED: historical scrape is active "
                f"(PID(s) {', '.join(map(str, history_pids))}); live scrape must not overlap.",
                file=sys.stderr,
                flush=True,
            )
            return 75

    if args.min_gap > args.max_gap:
        args.min_gap, args.max_gap = args.max_gap, args.min_gap

    budget = getattr(args, "time_budget_mins", 0) or 0
    if budget > 0:
        args.stop_at_monotonic = time.monotonic() + budget * 60.0
        print(f"  time budget        : {budget:.0f} min, stopping cleanly between "
              f"fixtures after that", flush=True)
    else:
        args.stop_at_monotonic = None

    sb = get_supabase()
    targets = choose_leagues(sb, args)

    print(f"\nScraping {len(targets)} league(s): "
          f"{', '.join(l for l, _ in targets)}", flush=True)

    # Two pipeline obligations, both before the normal backfill.
    #
    # The heartbeat records that this run happened at all, including if it
    # fails or returns nothing. Every freshness check the database can run is
    # derived from events and all of them are blind to the laptop never waking
    # up, because no new events looks exactly like no matches played.
    #
    # The re-scrape queue holds fixtures whose event feed was truncated. Those
    # are excluded from the metrics layer while queued, so they contaminate
    # nothing, but they stay wrong until they are fetched again.
    with heartbeat(leagues=[l for l, _ in targets]) as hb:
        try:
            drain_rescrape_queue(limit=10)
        except Exception:  # noqa: BLE001
            traceback.print_exc()

        total_ok, total_failed, total_remaining, total_events = scrape_targets(
            sb, args, targets
        )
        hb.record(matches_attempted=total_ok + total_failed, matches_written=total_ok,
                  events_written=total_events,
                  matches_failed=total_failed, matches_remaining=total_remaining)

    print("\n=== Summary ===", flush=True)
    print(f"  leagues:   {len(targets)}", flush=True)
    print(f"  succeeded: {total_ok}", flush=True)
    print(f"  failed:    {total_failed}", flush=True)
    print(f"  remaining: {total_remaining}", flush=True)
    print(f"  events:    {total_events}", flush=True)
    if total_remaining > 0 and not args.list:
        print("  (re-run to resume — it only scrapes what's still missing)", flush=True)

    if args.list:
        return 0

    # A partial load is not publishable. Do not refresh the materialized
    # analytics from a mixture of old and new league coverage; the next
    # idempotent run resumes only the missing games.
    #
    # A partial run must also be nonzero for Task Scheduler. The heartbeat and
    # log counts distinguish partial progress from a startup failure.
    if total_failed > 0 or total_remaining > 0:
        print(
            "\n  analytics rebuild skipped: live-ingestion gaps remain; re-run to resume.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    # One rebuild after ALL leagues, not per league: the analytics layers span leagues,
    # so rebuilding per league would repeat the same expensive work N times.
    if total_ok > 0 and not args.no_rebuild:
        print("\n=== Rebuild ===", flush=True)
        try:
            from backfill_bio import run_backfill
            b = run_backfill(sb, quiet=True)
            print(f"  bio        -> {b.get('written',0)} players "
                  f"(age {b.get('with_age',0)}, ht {b.get('with_height',0)})", flush=True)
        except Exception as e:  # noqa: BLE001 - bio is enrichment, never block the rebuild
            print(f"  bio        -> skipped ({e})", flush=True)
        # Queue the rebuild; do not drive it from here. This used to call
        # rebuild_step for all 19 steps over HTTP. Metrics steps now take 15 to
        # 25 minutes, so on 14 September at 23:30 the metrics1 call hit the API
        # gateway's upstream timeout, returned 504, and this process exited 1
        # after a scrape that wrote every fixture. The database was never told:
        # metrics1 kept executing for more than ten minutes with no client and no
        # statement timeout, as service_role has none, rebuilding the same
        # matviews as the cron worker on the same disk. Every nightly run would
        # have done the same.
        #
        # The cron worker already owns rebuilds: queued runs, per-step records,
        # the reaper, the verify gate, the published as-of date. The scraper's
        # only job is to say new data has landed, and enqueue_rebuild_if_new_data
        # does exactly that, skipping when a run is already pending or running.
        # A failure here is not fatal: job analytics-enqueue-on-new-data makes
        # the same call every ten minutes, so the rebuild is late, not lost.
        try:
            resp = sb.rpc("enqueue_rebuild_if_new_data", {}).execute()
            print(f"  rebuild    -> {resp.data}", flush=True)
            print("  the cron worker publishes the new games when its verify gate passes.",
                  flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"\n  !! could not queue the rebuild: {e}", file=sys.stderr, flush=True)
            print("  data loaded fine; the scheduled enqueue picks it up within ten minutes.",
                  file=sys.stderr, flush=True)
    elif total_ok == 0:
        print("\n  no new games loaded; analytics publication status is tracked separately.", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
