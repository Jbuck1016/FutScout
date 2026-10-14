"""Profile installed-SDK JSON payloads from an existing forecast, without outcomes.

Only reads the supplied frozen file. Rebuilds a memory copy using its recorded
goal rates, which can already be rounded. This is transport sizing, not a new
forecast, evaluation, SQL round trip, or storage benchmark.
"""
from contextlib import redirect_stdout
from datetime import datetime
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
from time import perf_counter

import httpx
from check_probability_integration import (
    FIELDS, MockPersistence, SCORE_CONTRACT_VERSION, generation, offline_guards,
    result_masses, score_dict, score_matrix,
)


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def db_rows(rows, as_of, kind):
    local = {"league", "date", "home_team", "away_team", "explanation", "score_distribution_contract"}
    return [{k: v for k, v in row.items() if k not in local} |
            {"model_run_id": 123456789, "forecast_kind": kind, "as_of": as_of.isoformat()} for row in rows]


def run(snapshot, output):
    source = snapshot.read_bytes()
    payload = json.loads(source)
    as_of, through = instant(payload["as_of"]), instant(payload["evaluation_through"])
    original = payload["predictions"]
    rebuilt = []
    for row in original:
        home, away = row["home_expected_goals"], row["away_expected_goals"]
        rebuilt.append(row | {"scoreline_distribution": score_dict(home, away),
                              "score_distribution_contract": SCORE_CONTRACT_VERSION} |
                       dict(zip(FIELDS, map(float, result_masses(score_matrix(home, away))))))
    profiles = {}
    with offline_guards(), tempfile.TemporaryDirectory(prefix="soccer-payload-") as directory:
        for name, rows in (("existing_frozen", original), ("adaptive_memory_copy", rebuilt)):
            fake = MockPersistence(directory)
            try:
                fake.args.forecast_kind = payload["forecast_kind"]
                start = perf_counter()
                with redirect_stdout(io.StringIO()):
                    generation.persist_predictions(fake.db, fake.args, {}, rows, as_of, through)
                elapsed = perf_counter() - start
                posts = [request for request in fake.requests if request.method == "POST"]
                assert len(posts) == 1
                wire = posts[0].content
                all_rows = db_rows(rows, as_of, payload["forecast_kind"])
                # A 1,000-row JSON result as used by the ledger's page size.
                # Fixture IDs/timestamps are kept; model-run ID is synthetic.
                page_bytes = [len(httpx.Response(200, json=all_rows[start:start + 1000]).content)
                              for start in range(0, len(all_rows), 1000)]
                profiles[name] = {
                    "weekly_post_count": len(posts), "weekly_rows": len(fake.rows),
                    "weekly_request_bytes": len(wire),
                    "weekly_request_gzip_bytes": len(gzip.compress(wire, mtime=0)),
                    "sdk_and_emulator_seconds": elapsed,
                    "simulated_1000_row_page_bytes": page_bytes,
                    "max_single_score_grid_compact_json_bytes": max(
                        len(httpx.Response(200, json=row["scoreline_distribution"]).content) for row in rows),
                    "max_grid_cells": max(len(row["scoreline_distribution"]) for row in rows),
                }
            finally:
                fake.close()
    assert snapshot.read_bytes() == source
    worst = score_dict(6, 6)
    report = {"mode": "offline captured installed-SDK requests and synthetic JSON response sizes; NOT live database/storage",
              "snapshot": str(snapshot), "snapshot_sha256": hashlib.sha256(source).hexdigest(),
              "snapshot_unchanged": True, "fixtures": len(original),
              "as_of": payload["as_of"], "evaluation_through": payload["evaluation_through"],
              "model_run_id": "synthetic 123456789 (nine decimal digits)",
              "profiles": profiles,
              "maximum_clipped_rates": {"home": 6, "away": 6, "grid_cells": len(worst),
                                        "score_grid_compact_json_bytes": len(httpx.Response(200, json=worst).content)},
              "limitations": [
                  "Existing file rates may already be rounded; memory-copy figures size adaptive grids, not recover original rates.",
                  "Response sizes model requested fields; actual server response headers, policies, limits and numeric formatting are not measured.",
                  "Gzip figures are hypothetical compressed bytes; actual request compression was not enabled.",
                  "Runtime includes a fake registry and Python Decimal emulator, not network or PostgreSQL.",
                  "No live body-size limit, PostgreSQL TOAST size, full season runtime, or concurrent load was verified."]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.snapshot, args.output)
