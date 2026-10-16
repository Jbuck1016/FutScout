#!/usr/bin/env python3
"""Resumable, bounded archived-event sequence and xT backfill.

The database RPC selects only verified completed top-five matches without
historical sequences, so restarting this script does not duplicate work.
It never touches the live ``sequences`` table or starts a site rebuild.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from build_ml_features import client


ROOT = Path(__file__).resolve().parents[1]
SEASONS = ("2324", "2425", "2526")


def record(state_path: Path, payload: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(state_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", nargs="+", choices=SEASONS, default=list(SEASONS))
    parser.add_argument("--job", choices=("sequences", "candidates", "carries", "observations"),
                        default="sequences")
    parser.add_argument("--batch-size", type=int, default=4, choices=range(1, 9))
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--max-batches", type=int, default=0,
                        help="0 means run until all selected seasons complete")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print("Dry run: no database writes. Add --execute to backfill.", flush=True)
        return 0
    db = client()
    state_path = ROOT / "pipeline" / "state" / f"historical_rich_{args.job}_backfill.json"
    rpc_name = {
        "sequences": "ml_backfill_historical_sequence_batch",
        "candidates": "ml_backfill_historical_event_candidate_batch",
        "carries": "ml_backfill_historical_carry_candidate_batch",
        "observations": "ml_backfill_historical_v2_observation_batch",
    }[args.job]
    status = {"status": "running", "job": args.job,
              "seasons": args.seasons, "batches": 0,
              "games": 0, "sequences": 0, "season": None}
    record(state_path, status)
    try:
        for season in args.seasons:
            status["season"] = season
            failures = 0
            while True:
                try:
                    result = db.rpc(rpc_name, {
                        "p_season": season, "p_limit": args.batch_size,
                    }).execute().data
                    if not isinstance(result, dict):
                        raise RuntimeError(f"Unexpected RPC result: {result!r}")
                    state = result.get("status")
                    if state == "complete":
                        print(f"{season}: complete", flush=True)
                        break
                    if state == "busy":
                        time.sleep(max(args.delay_seconds, 5.0))
                        continue
                    if state != "progress" or result.get("games", 0) <= 0:
                        raise RuntimeError(f"Unexpected RPC state: {result!r}")
                    failures = 0
                    status["batches"] += 1
                    status["games"] += result["games"]
                    status["sequences"] += result.get("sequences", 0)
                    record(state_path, status)
                    unit = "sequences" if args.job == "sequences" else "sides"
                    print(f"{season}: +{result['games']} games, "
                          f"+{result.get('sequences', result.get('sides', 0))} "
                          f"{unit}; "
                          f"total {status['games']} games", flush=True)
                    if args.max_batches and status["batches"] >= args.max_batches:
                        status["status"] = "paused_at_batch_limit"
                        record(state_path, status)
                        return 0
                    time.sleep(args.delay_seconds)
                except Exception as exc:
                    failures += 1
                    print(f"{season}: error {failures}/3: {exc}", file=sys.stderr,
                          flush=True)
                    if failures >= 3:
                        raise
                    time.sleep(10 * failures)
        status["status"] = "complete"
        status["season"] = None
        record(state_path, status)
        return 0
    except Exception as exc:
        status["status"] = "failed"
        status["error"] = str(exc)
        record(state_path, status)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
