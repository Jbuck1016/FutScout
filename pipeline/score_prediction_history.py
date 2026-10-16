#!/usr/bin/env python3
"""Score several immutable weekly snapshots as one deduplicated shadow history."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import score_prediction_snapshot as scoring
import train_match_baselines as baseline
import frozen_slate_contract as frozen


# Require three genuinely complete frozen weekends, alongside the
# 100-overall/20-per-league sample gate. A weekend discovered later to have
# omitted completed fixtures does not count and is never backfilled.
MIN_COMPLETE_FROZEN_WEEKENDS = 3


def authentic_cutoff(payload: dict) -> bool:
    """Legacy backfills may be scored but cannot satisfy the live frozen gate."""
    try:
        as_of = scoring.parse_utc_datetime(payload["as_of"])
        created = scoring.parse_utc_datetime(payload["generated_at"])
        if not as_of <= created <= as_of + frozen.MAX_FREEZE_DELAY:
            return False
        manifest = Path(str(payload["fixture_manifest"]))
        if frozen.sha256(manifest) != payload["fixture_manifest_sha256"]:
            return False
        bundle_path = Path(str(payload["feature_input_bundle"]))
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        from freeze_shadow_tournament import canonical_digest
        return canonical_digest(bundle) == payload["feature_input_bundle_sha256"]
    except (KeyError, OSError, TypeError, ValueError):
        return False


def combine_snapshots(payloads: list[dict]) -> tuple[list[dict], int]:
    """Keep the earliest eligible frozen call for each game across weekly files."""
    chosen = {}
    repeats = 0
    for payload in sorted(payloads, key=lambda item: item["as_of"]):
        eligible, _ = scoring.evaluation_predictions(payload)
        for row in eligible:
            game_id = str(row["game_id"])
            if game_id in chosen:
                repeats += 1
                continue
            chosen[game_id] = row
    return list(chosen.values()), repeats


def frozen_weekend_coverage(
    payloads: list[dict], matches: list[dict]
) -> list[dict]:
    """Reconcile each frozen slate with fixtures later verified as completed.

    A provider schedule can be incomplete at forecast time.  The immutable call
    must not be backfilled after kickoff, but the weekend also must not count as
    complete once the canonical result ledger proves that a fixture was missed.
    """
    required_leagues = set(baseline.TOP_FIVE)
    coverage = []
    for payload in payloads:
        as_of = scoring.parse_utc_datetime(payload["as_of"])
        eligible, through_text = scoring.evaluation_predictions(payload)
        through = scoring.parse_utc_datetime(through_text)
        predicted_ids = {str(row["game_id"]) for row in eligible}
        canonical_rows = [
            row for row in matches
            if row.get("home_score") is not None
            and row.get("away_score") is not None
            and as_of < scoring.parse_utc_datetime(
                row.get("kickoff_at") or f"{row['date']}T12:00:00+00:00"
            ) <= through
        ]
        canonical_ids = {str(row["game_id"]) for row in canonical_rows}
        canonical_leagues = {str(row["league"]) for row in canonical_rows}
        missing_ids = sorted(canonical_ids - predicted_ids)
        cutoff_verified = authentic_cutoff(payload)
        coverage.append({
            "as_of": as_of.isoformat(),
            "evaluation_through": through.isoformat(),
            "predicted_calls": len(predicted_ids),
            "canonical_completed_fixtures": len(canonical_ids),
            "missing_completed_fixture_ids": missing_ids,
            "cutoff_provenance_verified": cutoff_verified,
            "complete": not missing_ids and canonical_leagues == required_leagues and cutoff_verified,
        })
    return coverage


def complete_frozen_weekends(payloads: list[dict], matches: list[dict]) -> int:
    """Count immutable windows covering every later-verified completed fixture."""
    return sum(row["complete"] for row in frozen_weekend_coverage(payloads, matches))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions-file", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/model_reports/shadow_score_history.json"))
    args = parser.parse_args()
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in args.predictions_file]
    if any(payload.get("forecast_kind") != "thursday_frozen" for payload in payloads):
        raise RuntimeError("shadow history accepts only immutable thursday_frozen snapshots")
    predictions, repeats = combine_snapshots(payloads)
    seasons = sorted({str(payload["season"]) for payload in payloads})
    if len(seasons) != 1:
        raise RuntimeError("all shadow snapshots must belong to one season")
    db = baseline.db_client()
    matches = baseline.fetch_pages(
        db.table("matches")
        .select(
            "game_id,season,league,date,kickoff_at,home_team,away_team,"
            "home_score,away_score"
        )
        .eq("season", seasons[0])
        .in_("league", list(baseline.TOP_FIVE))
        .order("game_id")
    )
    evaluated = scoring.evaluate(predictions, matches)
    weekend_coverage = frozen_weekend_coverage(payloads, matches)
    complete_weekends = sum(row["complete"] for row in weekend_coverage)
    sample_gate = evaluated["sample_gate"]
    sample_gate["minimum_complete_frozen_weekends"] = MIN_COMPLETE_FROZEN_WEEKENDS
    sample_gate["complete_frozen_weekends"] = complete_weekends
    sample_gate["ready"] = (
        bool(sample_gate["ready"])
        and complete_weekends >= MIN_COMPLETE_FROZEN_WEEKENDS
    )
    if not sample_gate["ready"]:
        sample_gate["decision"] = (
            "collect_more_complete_frozen_weekends"
            if complete_weekends < MIN_COMPLETE_FROZEN_WEEKENDS
            else "collect_more_results"
        )

    report = {
        "report_schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "season": seasons[0],
        "snapshot_count": len(payloads),
        "duplicate_game_forecasts_ignored": repeats,
        "selection_policy": "earliest_evaluation_eligible_thursday_frozen_prediction_per_game",
        "frozen_weekend_coverage": weekend_coverage,
        "snapshots": [str(path) for path in args.predictions_file],
        **evaluated,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Shadow history: snapshots={len(payloads)} eligible={len(predictions)} "
        f"resolved={report['resolved']} repeats_ignored={repeats}"
    )
    print(f"Sample decision: {report['sample_gate']['decision']}")
    print(f"Report: {args.output}")
    print("Read-only scoring; no Supabase rows were written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
