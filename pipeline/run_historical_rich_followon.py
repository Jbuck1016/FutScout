#!/usr/bin/env python3
"""After archived sequences finish, rebuild v2 observations and rolling features.

This is a one-shot local continuation, not a scheduler. It stops on a failed
or stale sequence worker. It does not train, register, or activate a model.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from build_ml_features import TOP_FIVE, client


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "pipeline" / "state"
SOURCE = STATE_DIR / "historical_rich_sequences_backfill.json"
CANDIDATES = STATE_DIR / "historical_rich_candidates_backfill.json"
STATE = STATE_DIR / "historical_rich_followon.json"
SEASONS = ("2324", "2425", "2526")


def record(status: str, **details: object) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat(),
               **details}
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE)
    print(json.dumps(payload, sort_keys=True), flush=True)


def run(*args: str) -> None:
    completed = subprocess.run([sys.executable, *args], cwd=ROOT, check=False)
    if completed.returncode:
        raise RuntimeError(f"Command exited {completed.returncode}: {' '.join(args)}")


def main() -> int:
    try:
        record("waiting_for_sequences_and_candidates")
        while True:
            sources = []
            for path in (SOURCE, CANDIDATES):
                if not path.exists():
                    raise RuntimeError(f"Missing source state: {path}")
                source = json.loads(path.read_text(encoding="utf-8"))
                sources.append(source)
                status = source.get("status")
                if status not in ("running", "complete"):
                    raise RuntimeError(f"{path.name} stopped: {status}: "
                                       f"{source.get('error', '')}")
                if status == "running":
                    updated = datetime.fromisoformat(source["updated_at"])
                    if (datetime.now(timezone.utc) - updated).total_seconds() > 900:
                        raise RuntimeError(f"{path.name} has not advanced for 15 minutes")
            if all(source.get("status") == "complete" for source in sources):
                break
            time.sleep(30)

        db = client()
        for season in SEASONS:
            xt_rows = db.rpc("ml_historical_sequence_xt_mismatches",
                             {"p_season": season}).execute().data or []
            pass_rows = []
            for league in TOP_FIVE:
                pass_rows.extend(db.rpc("ml_historical_sequence_pass_mismatches", {
                    "p_season": season, "p_league": league,
                }).execute().data or [])
            game_ids = sorted({str(row["game_id"])
                               for row in [*xt_rows, *pass_rows]})
            record("repairing_sequence_mismatches", season=season,
                   mismatched_games=len(game_ids),xt_sides=len(xt_rows),
                   pass_sides=len(pass_rows))
            for game_id in game_ids:
                result = db.rpc("ml_repair_historical_sequence_game",
                                {"p_game_id": game_id}).execute().data
                if result.get("status") != "repaired":
                    raise RuntimeError(f"Unexpected repair result for {game_id}: {result!r}")
            remaining_xt = db.rpc("ml_historical_sequence_xt_mismatches",
                                  {"p_season": season}).execute().data or []
            remaining_pass = []
            for league in TOP_FIVE:
                remaining_pass.extend(db.rpc("ml_historical_sequence_pass_mismatches", {
                    "p_season": season, "p_league": league,
                }).execute().data or [])
            if remaining_xt or remaining_pass:
                raise RuntimeError(f"{season}: {len(remaining_xt)} xT and "
                                   f"{len(remaining_pass)} pass-count mismatches remain")

        record("rebuilding_observations")
        run("pipeline/backfill_historical_sequences.py", "--job", "observations",
            "--execute", "--batch-size", "4", "--delay-seconds", "2")
        for season in SEASONS:
            record("rebuilding_features", season=season)
            run("pipeline/build_ml_features.py", "--season", season,
                "--observation-schema-version", "2", "--feature-schema-version", "2",
                "--features-only", "--execute")
            record("auditing", season=season)
            run("pipeline/audit_model_data_v2.py", "--season", season)
        record("complete", seasons=SEASONS)
        return 0
    except Exception as exc:
        record("failed", error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
