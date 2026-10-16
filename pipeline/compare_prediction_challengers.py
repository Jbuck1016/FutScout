#!/usr/bin/env python3
"""Compare two immutable prediction snapshots fixture by fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROBABILITY_FIELDS = ("home_win_probability", "draw_probability", "away_win_probability")
FIXTURE_IDENTITY_FIELDS = ("game_id", "date", "league", "home_team", "away_team")


def evidence_classification(primary: dict, challenger: dict) -> dict:
    """Conservative label: identical outputs are not proof of a real-time freeze."""
    reasons = []
    for label, payload in [('primary',primary),('challenger',challenger)]:
        if payload.get('forecast_kind') != 'thursday_frozen':
            reasons.append(f'{label}: not a Thursday-frozen snapshot')
        try:
            cutoff=datetime.fromisoformat(payload['as_of'].replace('Z','+00:00'))
            captured=datetime.fromisoformat(payload['generated_at'].replace('Z','+00:00'))
            if cutoff.tzinfo is None or captured.tzinfo is None or not 0 <= (captured-cutoff).total_seconds() <= 1800:
                reasons.append(f'{label}: capture not within real cutoff window')
        except (KeyError,ValueError,TypeError):
            reasons.append(f'{label}: missing capture provenance')
    for field in ('fixture_manifest_sha256','source_rows_sha256','feature_input_bundle_sha256'):
        if not primary.get(field) or primary.get(field)!=challenger.get(field):
            reasons.append(f'{field}: missing or mismatched')
    return {'classification':'frozen_candidate_requires_tournament_audit' if not reasons else 'exploratory_only',
            'promotion_evidence':False,'reasons':reasons,
            'note':'Only the verified frozen-tournament scorer can establish promotion eligibility.'}


def index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {str(row["game_id"]): row for row in payload.get("predictions", [])}
    if len(rows) != len(payload.get("predictions", [])):
        raise RuntimeError("prediction snapshot contains duplicate game ids")
    return rows


def fixture_identity(rows: dict[str, dict[str, Any]]) -> tuple[list[tuple[str, ...]], str]:
    """Return the canonical forecast-fixture identity and its stable digest.

    The source fixture manifest can legitimately be refreshed between model runs
    without changing any forecasted fixture.  Same-fixture comparisons therefore
    validate the immutable prediction rows directly and retain the source hashes
    separately as provenance.
    """
    identity = sorted(
        tuple(str(row.get(field, "")) for field in FIXTURE_IDENTITY_FIELDS)
        for row in rows.values()
    )
    encoded = json.dumps(identity, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return identity, hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--challenger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    primary_payload = json.loads(args.primary.read_text(encoding="utf-8"))
    challenger_payload = json.loads(args.challenger.read_text(encoding="utf-8"))
    identity = ("season", "as_of", "forecast_kind")
    mismatched = [key for key in identity if primary_payload.get(key) != challenger_payload.get(key)]
    if mismatched:
        raise RuntimeError(f"snapshots do not share an immutable fixture identity: {mismatched}")
    primary, challenger = index(primary_payload), index(challenger_payload)
    if set(primary) != set(challenger):
        raise RuntimeError("snapshots do not contain exactly the same fixtures")
    primary_fixture_identity, fixture_identity_sha256 = fixture_identity(primary)
    challenger_fixture_identity, challenger_fixture_sha256 = fixture_identity(challenger)
    if primary_fixture_identity != challenger_fixture_identity:
        raise RuntimeError("snapshots contain different fixture dates, leagues, or teams")
    if fixture_identity_sha256 != challenger_fixture_sha256:
        raise RuntimeError("canonical fixture identity digests do not match")

    rows = []
    for game_id in primary:
        left, right = primary[game_id], challenger[game_id]
        deltas = {
            field: float(right[field]) - float(left[field]) for field in PROBABILITY_FIELDS
        }
        max_field = max(PROBABILITY_FIELDS, key=lambda field: abs(deltas[field]))
        primary_pick = max(PROBABILITY_FIELDS, key=lambda field: float(left[field]))
        challenger_pick = max(PROBABILITY_FIELDS, key=lambda field: float(right[field]))
        rows.append({
            "game_id": game_id,
            "date": left["date"],
            "league": left["league"],
            "home_team": left["home_team"],
            "away_team": left["away_team"],
            "primary": {field: float(left[field]) for field in PROBABILITY_FIELDS} | {
                "home_expected_goals": float(left["home_expected_goals"]),
                "away_expected_goals": float(left["away_expected_goals"]),
                "pick": primary_pick,
            },
            "challenger": {field: float(right[field]) for field in PROBABILITY_FIELDS} | {
                "home_expected_goals": float(right["home_expected_goals"]),
                "away_expected_goals": float(right["away_expected_goals"]),
                "pick": challenger_pick,
            },
            "probability_delta": deltas,
            "maximum_absolute_probability_delta": abs(deltas[max_field]),
            "largest_moved_outcome": max_field,
            "different_favourite": primary_pick != challenger_pick,
            "primary_drivers": (left.get("explanation") or {}).get("drivers", [])[:3],
            "challenger_drivers": (right.get("explanation") or {}).get("drivers", [])[:3],
        })
    rows.sort(key=lambda row: row["maximum_absolute_probability_delta"], reverse=True)
    report = {
        "report_schema_version": 1,
        "evidence_status": evidence_classification(primary_payload,challenger_payload),
        "created_at": datetime.now(UTC).isoformat(),
        "scope": {
            **{key: primary_payload.get(key) for key in identity},
            "fixture_identity_sha256": fixture_identity_sha256,
            "primary_fixture_manifest_sha256": primary_payload.get("fixture_manifest_sha256"),
            "challenger_fixture_manifest_sha256": challenger_payload.get("fixture_manifest_sha256"),
            "source_manifest_hashes_match": (
                primary_payload.get("fixture_manifest_sha256")
                == challenger_payload.get("fixture_manifest_sha256")
            ),
        },
        "primary_model": primary_payload.get("model_version"),
        "challenger_model": challenger_payload.get("model_version"),
        "fixtures_compared": len(rows),
        "different_favourite_count": sum(row["different_favourite"] for row in rows),
        "mean_maximum_probability_delta": (
            sum(row["maximum_absolute_probability_delta"] for row in rows) / len(rows)
            if rows else 0.0
        ),
        "largest_disagreements": rows[:25],
        "all_fixture_comparisons": rows,
        "interpretation": (
            "Disagreement is diagnostic, not proof that either model is right. "
            "Resolved frozen forecasts must decide which philosophy generalizes live."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Compared {len(rows)} identical fixtures: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
