#!/usr/bin/env python3
"""Generate point-in-time domestic match predictions from a trusted artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import model_artifact
import train_match_baselines as baseline
import frozen_slate_contract as frozen


def validate_frozen_persistence(payload: dict) -> None:
    """Never persist a retrospective file as a genuine Thursday call."""
    as_of = parse_instant(str(payload["as_of"]))
    created = parse_instant(str(payload["generated_at"]))
    if not as_of <= created <= as_of + frozen.MAX_FREEZE_DELAY:
        raise RuntimeError("frozen snapshot was not generated at its real Thursday cutoff")
    manifest_path = Path(str(payload["fixture_manifest"]))
    manifest = frozen.load_manifest(manifest_path, str(payload["season"]), as_of, strict_capture=True)
    if frozen.sha256(manifest_path) != payload["fixture_manifest_sha256"]:
        raise RuntimeError("frozen provider manifest has changed since prediction")
    from freeze_shadow_tournament import canonical_digest
    bundle = json.loads(Path(str(payload["feature_input_bundle"])).read_text(encoding="utf-8"))
    if canonical_digest(bundle) != payload["feature_input_bundle_sha256"]:
        raise RuntimeError("frozen feature input bundle has changed since prediction")
    if bundle["source_provenance"]["source_rows_sha256"] != payload["source_rows_sha256"]:
        raise RuntimeError("frozen source-row fingerprint mismatch")
    through = parse_instant(str(payload["evaluation_through"]))
    coverage = frozen.validate_week(manifest, list(payload["predictions"]), as_of, through)
    if not coverage["passed"] or not coverage["expected"]:
        raise RuntimeError(f"cannot persist an incomplete frozen provider slate: {coverage}")


def parse_instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--as-of must include a timezone")
    return parsed.astimezone(UTC)


def parse_fixture_instant(value: str) -> datetime:
    """Parse stored fixture times, tolerating legacy date-only midnight rows.

    A small number of manually ingested cup/league fixtures predate the
    timezone-aware ``kickoff_at`` contract. They must not block persistence of
    an unrelated seven-day slate; treating their naive timestamp as UTC keeps
    their ordering deterministic until the exact kickoff is reconciled.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def select_fixtures(season_matches: list[dict], as_of: datetime,
                    provider_fixture_ids: set[str] | None) -> list[dict]:
    """Select future fixtures, treating the provider snapshot as lifecycle truth."""
    fixtures_by_pair: dict[tuple[str, str, str, str], dict] = {}
    for row in season_matches:
        if parse_instant(row.get("kickoff_at") or f"{row['date']}T12:00:00+00:00") <= as_of:
            continue
        game_id = str(row["game_id"])
        scored_after_cutoff = row.get("home_score") is not None and row.get("away_score") is not None
        provider_row_is_known = provider_fixture_ids is None or game_id in provider_fixture_ids
        if scored_after_cutoff or not game_id.startswith("fd-") or provider_row_is_known:
            key = (str(row["league"]), str(row["season"]),
                   str(row["home_team"]), str(row["away_team"]))
            previous = fixtures_by_pair.get(key)
            def priority(candidate: dict) -> tuple[bool, bool, bool]:
                candidate_id = str(candidate["game_id"])
                return (
                    provider_fixture_ids is not None and candidate_id in provider_fixture_ids,
                    not candidate_id.startswith("fd-"),
                    candidate.get("home_score") is not None and candidate.get("away_score") is not None,
                )
            if previous is None or priority(row) > priority(previous):
                fixtures_by_pair[key] = row
    return sorted(fixtures_by_pair.values(), key=lambda row: (
        str(row.get("kickoff_at") or row["date"]), str(row["game_id"])
    ))


def provider_completion_gaps(
    completed_provider: list[dict], season_matches: list[dict],
    observed_game_ids: set[str], as_of: datetime,
) -> list[str]:
    """Find provider-known results absent from canonical matches or observations."""
    canonical = {
        (str(row["league"]), str(row["date"])[:10], str(row["home_team"]), str(row["away_team"])): row
        for row in season_matches
    }
    gaps = []
    for provider in completed_provider:
        if parse_instant(provider.get("kickoff_at") or f"{provider['date']}T12:00:00+00:00") > as_of:
            continue
        key = (
            str(provider["league"]), str(provider["date"])[:10],
            str(provider["home_team"]), str(provider["away_team"]),
        )
        match = canonical.get(key)
        label = f"{key[0]} {key[1]} {key[2]} vs {key[3]}"
        if match is None:
            gaps.append(f"missing canonical match: {label}")
            continue
        actual = (match.get("home_score"), match.get("away_score"))
        expected = (provider.get("home_score"), provider.get("away_score"))
        if actual != expected:
            gaps.append(f"score mismatch: {label} provider={expected} database={actual}")
        elif str(match["game_id"]) not in observed_game_ids:
            gaps.append(f"missing ML observations: {label}")
    return gaps


def persistence_horizon(
    rows: list[dict], as_of: datetime, evaluation_through: datetime,
) -> list[dict]:
    """Keep only the scored weekly slate in Supabase.

    The local artifact intentionally retains every remaining fixture so the
    league-table simulator has a complete schedule. Persisting those full
    scoreline grids every week would duplicate large, unscored payloads.
    """
    return [
        row for row in rows
        if as_of < parse_fixture_instant(str(row["date"])) <= evaluation_through
    ]


def persist_predictions(db, args, artifact: dict, rows: list[dict], as_of: datetime,
                        evaluation_through: datetime) -> None:
    model_rows = db.table("ml_model_runs").select("id,status,artifact_sha256").eq("id", args.model_run_id).execute().data or []
    if len(model_rows) != 1 or model_rows[0]["status"] not in {"validated", "shadow", "active"}:
        raise RuntimeError("prediction persistence requires one validated, shadow, or active model run")
    digest = hashlib.sha256(args.artifact.read_bytes()).hexdigest()
    if model_rows[0].get("artifact_sha256") != digest:
        raise RuntimeError("local artifact digest does not match registered model")
    scored_slate = persistence_horizon(rows, as_of, evaluation_through)
    if not scored_slate:
        raise RuntimeError("no fixtures fall inside the private scoring horizon")
    db_rows = [{k: value for k, value in row.items() if k not in {
                   "league", "date", "home_team", "away_team", "explanation"
               }} |
               {"model_run_id": args.model_run_id, "forecast_kind": args.forecast_kind, "as_of": as_of.isoformat()} for row in scored_slate]
    db.table("ml_match_predictions").upsert(db_rows, on_conflict="model_run_id,game_id,forecast_kind,as_of").execute()
    print(f"Persisted {len(db_rows)} idempotent predictions inside the {args.evaluation_days}-day scoring horizon")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--model-run-id", type=int)
    parser.add_argument("--season", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--forecast-kind", choices=("thursday_frozen", "latest"), default="latest")
    parser.add_argument("--evaluation-days", type=int, default=7,
                        help="weekly frozen scoring horizon; simulation still uses every fixture")
    parser.add_argument("--league", action="append", choices=baseline.TOP_FIVE)
    parser.add_argument("--fixtures-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reuse-output", action="store_true",
                        help="persist an already-frozen output without recomputing or rewriting it")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.execute and args.model_run_id is None:
        raise ValueError("--execute requires --model-run-id")
    if args.execute and args.forecast_kind == "thursday_frozen" and not args.reuse_output:
        raise RuntimeError("persist Thursday calls only from a verified same-cutoff tournament snapshot")
    as_of = parse_instant(args.as_of)
    if args.evaluation_days < 1 or args.evaluation_days > 14:
        raise ValueError("--evaluation-days must be between 1 and 14")
    leagues = args.league or list(baseline.TOP_FIVE)
    db = baseline.db_client()
    artifact = model_artifact.load_artifact(args.artifact)
    if args.reuse_output:
        if args.output is None or not args.output.is_file():
            raise RuntimeError("--reuse-output requires an existing --output snapshot")
        payload = json.loads(args.output.read_text(encoding="utf-8"))
        expected_version = args.artifact.stem
        if (payload.get("model_version") != expected_version or
            payload.get("season") != args.season or
            payload.get("forecast_kind") != args.forecast_kind or
            parse_instant(str(payload.get("as_of"))) != as_of):
            raise RuntimeError("existing immutable output identity does not match requested persistence")
        evaluation_through = parse_instant(str(payload["evaluation_through"]))
        rows = list(payload.get("predictions", []))
        if not rows:
            raise RuntimeError("existing immutable output is empty")
        print(f"Reusing {len(rows)} immutable predictions: {args.output}")
        if args.execute:
            if args.forecast_kind == "thursday_frozen":
                validate_frozen_persistence(payload)
            persist_predictions(db, args, artifact, rows, as_of, evaluation_through)
        else:
            print("Dry run only; no Supabase rows written")
        return 0
    provider_fixture_ids: set[str] | None = None
    completed_provider: list[dict] = []
    fixture_manifest_digest: str | None = None
    if args.fixtures_file is not None:
        fixture_payload = json.loads(args.fixtures_file.read_text(encoding="utf-8"))
        if str(fixture_payload.get("season")) != args.season:
            raise RuntimeError("fixture snapshot season does not match --season")
        provider_fixture_ids = {
            str(row["game_id"]) for row in fixture_payload.get("fixtures", [])
            if str(row.get("league")) in leagues
            and row.get('provider_status') not in {'POSTPONED','SUSPENDED','CANCELLED'}
        }
        completed_provider = [
            row for row in fixture_payload.get("completed_fixtures", [])
            if str(row.get("league")) in leagues
        ]
        provider_fixture_ids.update(str(row["game_id"]) for row in completed_provider)
        fixture_manifest_digest = hashlib.sha256(args.fixtures_file.read_bytes()).hexdigest()
    matches = baseline.fetch_pages(
        db.table("matches").select("game_id,season,league,date,kickoff_at,home_team,away_team,home_score,away_score")
        .in_("league", leagues).order("date").order("game_id")
    )
    season_matches = [row for row in matches if row["season"] == args.season]
    fixtures = select_fixtures(season_matches, as_of, provider_fixture_ids)
    if not fixtures:
        raise RuntimeError(f"no upcoming {args.season} fixtures are loaded after {as_of.isoformat()}")
    observations = baseline.fetch_pages(
        db.table("ml_team_match_observations")
        .select(",".join(("game_id", "team", "season", "league", "match_date") +
                         model_artifact.observation_metrics(int(artifact["feature_schema_version"]))))
        .eq("observation_schema_version", int(artifact["feature_schema_version"]))
        .in_("league", leagues).order("match_date").order("game_id")
    )
    completed_current = {
        str(row["game_id"]) for row in season_matches
        if row.get("home_score") is not None and row.get("away_score") is not None
        and parse_instant(row.get("kickoff_at") or f"{row['date']}T12:00:00+00:00") <= as_of
    }
    eligible_game_ids = {
        str(row["game_id"])
        for row in matches
        if row.get("home_score") is not None and row.get("away_score") is not None
        and parse_instant(row.get("kickoff_at") or f"{row['date']}T12:00:00+00:00") <= as_of
    }
    eligible_observations = [row for row in observations if str(row["game_id"]) in eligible_game_ids]
    eligible_matches = [row for row in matches if str(row["game_id"]) in eligible_game_ids]
    observed_current = {
        str(row["game_id"]) for row in eligible_observations if row.get("season") == args.season
    }
    missing_current = sorted(completed_current - observed_current)
    if missing_current:
        raise RuntimeError(
            f"current-season ML observations are stale: {len(missing_current)} completed fixtures are missing; "
            "refresh observations before forecasting"
        )
    provider_gaps = provider_completion_gaps(
        completed_provider, season_matches, observed_current, as_of
    )
    if provider_gaps:
        preview = "; ".join(provider_gaps[:5])
        raise RuntimeError(
            f"fixture provider knows {len(provider_gaps)} completed result(s) missing from the "
            f"current-form layer: {preview}"
        )
    rows = model_artifact.predict_rows(
        artifact,
        fixtures,
        eligible_observations,
        eligible_matches,
        prediction_as_of=as_of,
    )
    evaluation_through = as_of + timedelta(days=args.evaluation_days)
    payload = {"as_of": as_of.isoformat(),
               "evaluation_through": evaluation_through.isoformat(),
               "forecast_kind": args.forecast_kind,
               "season": args.season, "artifact": str(args.artifact),
               "model_version": args.artifact.stem,
               "feature_schema_version": int(artifact["feature_schema_version"]),
               "algorithm": artifact["algorithm"],
               "trained_through": artifact["trained_through"],
               "feature_count": len(artifact["numeric_columns"]),
               "fixture_manifest": str(args.fixtures_file) if args.fixtures_file else None,
               "fixture_manifest_sha256": fixture_manifest_digest, "predictions": rows}
    output = args.output or Path(__file__).resolve().parents[1] / "artifacts" / "predictions" / f"{args.season}_{args.forecast_kind}_{as_of:%Y%m%dT%H%M%SZ}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Generated {len(rows)} predictions: {output}")
    if not args.execute:
        print("Dry run only; no Supabase rows written")
        return 0
    persist_predictions(db, args, artifact, rows, as_of, evaluation_through)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
