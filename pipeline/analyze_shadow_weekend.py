#!/usr/bin/env python3
"""Build an inspectable retrospective for one immutable Thursday slate.

The report distinguishes forecast quality from what happened on the pitch.
Post-match tactical metrics are diagnostic evidence only: they explain how the
match unfolded and must never be treated as inputs that were known pre-match.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import score_prediction_snapshot as scoring
import train_match_baselines as baseline


OUTCOMES = ("H", "D", "A")
PROBABILITY_KEYS = (
    "home_win_probability",
    "draw_probability",
    "away_win_probability",
)
TACTICAL_FIELDS = (
    "shots",
    "shots_against",
    "field_tilt_pct",
    "box_entries_pass",
    "xt_created",
    "xt_conceded",
    "npxg_for",
    "npxg_against",
)


def outcome(home: int, away: int) -> str:
    return "H" if home > away else "D" if home == away else "A"


def fixture_in_window(row: dict[str, Any], start: datetime, end: datetime) -> bool:
    kickoff = scoring.parse_utc_datetime(
        row.get("kickoff_at") or f"{row['date']}T12:00:00+00:00"
    )
    return start < kickoff <= end


def score_row(prediction: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
    home, away = int(match["home_score"]), int(match["away_score"])
    actual = outcome(home, away)
    probabilities = [float(prediction[key]) for key in PROBABILITY_KEYS]
    actual_index = OUTCOMES.index(actual)
    favorite_index = max(range(3), key=probabilities.__getitem__)
    target = [1.0 if index == actual_index else 0.0 for index in range(3)]
    return {
        "actual_outcome": actual,
        "actual_probability": probabilities[actual_index],
        "favorite": OUTCOMES[favorite_index],
        "favorite_probability": probabilities[favorite_index],
        "correct_favorite": favorite_index == actual_index,
        "log_loss": -math.log(max(probabilities[actual_index], 1e-15)),
        "brier": sum((probabilities[index] - target[index]) ** 2 for index in range(3)),
        "home_goal_error": home - float(prediction["home_expected_goals"]),
        "away_goal_error": away - float(prediction["away_expected_goals"]),
        "home_score": home,
        "away_score": away,
        "probabilities": dict(zip(OUTCOMES, probabilities, strict=True)),
    }


def tactical_summary(
    prediction: dict[str, Any], observations: dict[tuple[str, str], dict[str, Any]]
) -> dict[str, Any] | None:
    game_id = str(prediction["game_id"])
    home = observations.get((game_id, str(prediction["home_team"])))
    away = observations.get((game_id, str(prediction["away_team"])))
    if not home or not away:
        return None
    home_metrics = {field: home.get(field) for field in TACTICAL_FIELDS}
    away_metrics = {field: away.get(field) for field in TACTICAL_FIELDS}
    home_edges = away_edges = 0
    for field in ("shots", "field_tilt_pct", "box_entries_pass", "xt_created", "npxg_for"):
        left, right = home.get(field), away.get(field)
        if left is None or right is None or float(left) == float(right):
            continue
        if float(left) > float(right):
            home_edges += 1
        else:
            away_edges += 1
    leader = "H" if home_edges > away_edges else "A" if away_edges > home_edges else "level"
    return {
        "home": home_metrics,
        "away": away_metrics,
        "multi_metric_leader": leader,
        "home_metric_edges": home_edges,
        "away_metric_edges": away_edges,
        "note": "Post-match metrics describe match process; they were not available to the frozen forecast.",
    }


def interpretation(scored: dict[str, Any], tactical: dict[str, Any] | None) -> str:
    if scored["correct_favorite"]:
        return "directionally_correct"
    if scored["actual_probability"] >= 0.25:
        return "plausible_alternate_outcome"
    if tactical and tactical["multi_metric_leader"] == scored["favorite"]:
        return "result_swung_against_process"
    if tactical and tactical["multi_metric_leader"] == scored["actual_outcome"]:
        return "pre_match_read_missed_match_process"
    return "high_surprise_unresolved"


def market_context(
    market_rows: list[dict[str, Any]], frozen_probabilities: dict[str, float], actual: str
) -> dict[str, Any] | None:
    if not market_rows:
        return None
    chosen = min(
        market_rows,
        key=lambda row: (
            not bool(row.get("closing_eligible")),
            abs(float(row.get("minutes_before_kickoff") or 999999)),
        ),
    )
    market_probs = [float(value) for value in chosen["market_probabilities"]]
    actual_index = OUTCOMES.index(actual)
    return {
        "snapshot_kind": chosen.get("snapshot_kind"),
        "captured_at": chosen.get("market_captured_at"),
        "minutes_before_kickoff": chosen.get("minutes_before_kickoff"),
        "bookmaker_count": chosen.get("bookmaker_count"),
        "closing_eligible": bool(chosen.get("closing_eligible")),
        "probabilities": dict(zip(OUTCOMES, market_probs, strict=True)),
        "market_log_loss": -math.log(max(market_probs[actual_index], 1e-15)),
        "frozen_model_log_loss": -math.log(
            max(float(frozen_probabilities[actual]), 1e-15)
        ),
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"matches": 0}
    result_counts = Counter(row["actual_outcome"] for row in rows)
    expected = {
        code: sum(float(row["probabilities"][code]) for row in rows) / len(rows)
        for code in OUTCOMES
    }
    observed = {code: result_counts[code] / len(rows) for code in OUTCOMES}
    return {
        "matches": len(rows),
        "accuracy": sum(row["correct_favorite"] for row in rows) / len(rows),
        "mean_log_loss": sum(row["log_loss"] for row in rows) / len(rows),
        "mean_brier": sum(row["brier"] for row in rows) / len(rows),
        "home_goals_mae": sum(abs(row["home_goal_error"]) for row in rows) / len(rows),
        "away_goals_mae": sum(abs(row["away_goal_error"]) for row in rows) / len(rows),
        "expected_outcome_share": expected,
        "observed_outcome_share": observed,
    }


def market_loss_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"matches": 0, "frozen_model_log_loss": None, "market_log_loss": None,
                "model_delta_vs_market_log_loss": None}
    model_loss = sum(row["frozen_model_log_loss"] for row in rows) / len(rows)
    market_loss = sum(row["market_log_loss"] for row in rows) / len(rows)
    return {
        "matches": len(rows),
        "frozen_model_log_loss": model_loss,
        "market_log_loss": market_loss,
        "model_delta_vs_market_log_loss": model_loss - market_loss,
    }


def markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Frozen V2 weekend review",
        "",
        f"Frozen at `{report['as_of']}`; evaluated through `{report['evaluation_through']}`.",
        "",
        "Post-match tactical metrics below explain how a match unfolded. They are not retroactive model inputs and do not prove why a result occurred.",
        "",
        "## Headline",
        "",
        f"- Scored calls: **{summary['matches']}**",
        f"- Favourite accuracy: **{summary['accuracy']:.1%}**",
        f"- Mean log loss: **{summary['mean_log_loss']:.4f}**",
        f"- Mean Brier score: **{summary['mean_brier']:.4f}**",
        f"- Tactical evidence coverage: **{report['coverage']['tactical_matches']}/{summary['matches']}**",
        f"- Canonical completed fixtures missed by the immutable slate: **{len(report['coverage']['missing_completed_fixtures'])}**",
        "",
    ]
    value_summary = report.get("value_bet_summary")
    if value_summary:
        roi = value_summary.get("median_price_roi")
        lines += [
            "## Frozen value-selection research",
            "",
            f"- Qualifying selections: **{value_summary['selections']}**",
            f"- Record: **{value_summary['wins']}–{value_summary['losses']}**",
            f"- Median-price profit: **{value_summary['median_price_profit_units']:+.2f} units**",
            f"- Median-price ROI: **{'—' if roi is None else f'{roi:.1%}'}**",
            "- These are flat-stake retrospective exploratory results from an outcome-blind rule, not evidence of a proven betting edge.",
            "",
        ]
    lines += [
        "## Largest forecast misses",
        "",
        "| Match | Score | H / D / A | Actual p | Log loss | Value pick | Diagnostic |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for row in report["largest_misses"]:
        p = row["probabilities"]
        selection = row.get("value_bet")
        value_pick = (
            f"{selection['outcome']} ({selection['median_price_profit_units']:+.2f}u)"
            if selection else "none"
        )
        lines.append(
            f"| {row['home_team']}–{row['away_team']} | {row['home_score']}–{row['away_score']} | "
            f"{p['H']:.1%} / {p['D']:.1%} / {p['A']:.1%} | {row['actual_probability']:.1%} | "
            f"{row['log_loss']:.3f} | {value_pick} | {row['interpretation'].replace('_', ' ')} |"
        )
    lines += ["", "## Strongest correct calls", ""]
    for row in report["strongest_correct_calls"]:
        lines.append(
            f"- **{row['home_team']} {row['home_score']}–{row['away_score']} {row['away_team']}** — "
            f"{row['actual_probability']:.1%} on the realised outcome; log loss {row['log_loss']:.3f}."
        )
    if report["coverage"]["missing_completed_fixtures"]:
        lines += ["", "## Missing frozen calls", ""]
        for row in report["coverage"]["missing_completed_fixtures"]:
            lines.append(
                f"- {row['date']}: {row['home_team']}–{row['away_team']} ({row['league']})"
            )
    lines += [
        "",
        "## Interpretation rules",
        "",
        "- `directionally correct`: the highest-probability outcome happened.",
        "- `plausible alternate outcome`: the favourite lost, but the realised outcome already had at least 25% probability.",
        "- `result swung against process`: the low-probability result occurred even though the post-match tactical ledger leaned toward the forecast favourite.",
        "- `pre match read missed match process`: the low-probability winner also led the post-match tactical ledger.",
        "- These buckets are diagnostic descriptions, not causal claims.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions-file", type=Path, required=True)
    parser.add_argument(
        "--market-report",
        type=Path,
        default=Path("artifacts/model_reports/market_edge_report_2627.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--value-ledger", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.predictions_file.read_text(encoding="utf-8"))
    predictions, through_text = scoring.evaluation_predictions(payload)
    if not predictions:
        raise RuntimeError("frozen snapshot has no evaluation-eligible calls")
    as_of = scoring.parse_utc_datetime(payload["as_of"])
    through = scoring.parse_utc_datetime(through_text)
    game_ids = {str(row["game_id"]) for row in predictions}

    db = baseline.db_client()
    matches = baseline.fetch_pages(
        db.table("matches")
        .select(
            "game_id,season,league,date,kickoff_at,home_team,away_team,"
            "home_score,away_score"
        )
        .eq("season", str(payload["season"]))
        .in_("league", list(baseline.TOP_FIVE))
        .order("game_id")
    )
    match_by_id = {str(row["game_id"]): row for row in matches}
    unresolved = sorted(
        game_id for game_id in game_ids
        if game_id not in match_by_id
        or match_by_id[game_id].get("home_score") is None
        or match_by_id[game_id].get("away_score") is None
    )
    if unresolved:
        raise RuntimeError(f"frozen calls are unresolved: {unresolved}")

    observations = baseline.fetch_pages(
        db.table("ml_team_match_observations")
        .select("game_id,team," + ",".join(TACTICAL_FIELDS))
        .eq("season", str(payload["season"]))
        .eq("observation_schema_version", int(payload.get("feature_schema_version") or 2))
        .in_("game_id", sorted(game_ids))
        .order("game_id")
        .order("team")
    )
    observation_by_side = {
        (str(row["game_id"]), str(row["team"])): row for row in observations
    }

    market_by_game: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if args.market_report.is_file():
        market_payload = json.loads(args.market_report.read_text(encoding="utf-8"))
        for row in market_payload.get("matches", []):
            market_by_game[str(row["game_id"])].append(row)

    value_by_game: dict[str, dict[str, Any] | None] = {}
    value_summary = None
    if args.value_ledger and args.value_ledger.is_file():
        value_payload = json.loads(args.value_ledger.read_text(encoding="utf-8"))
        value_summary = value_payload.get("summary")
        value_by_game = {
            str(row["game_id"]): row.get("selection")
            for row in value_payload.get("matches", [])
        }

    rows = []
    for prediction in predictions:
        game_id = str(prediction["game_id"])
        match = match_by_id[game_id]
        scored = score_row(prediction, match)
        tactical = tactical_summary(prediction, observation_by_side)
        row = {
            "game_id": game_id,
            "date": prediction["date"],
            "league": prediction["league"],
            "home_team": prediction["home_team"],
            "away_team": prediction["away_team"],
            "home_expected_goals": float(prediction["home_expected_goals"]),
            "away_expected_goals": float(prediction["away_expected_goals"]),
            "forecast_summary": (prediction.get("explanation") or {}).get("summary"),
            "forecast_drivers": (prediction.get("explanation") or {}).get("drivers", []),
            **scored,
            "tactical": tactical,
            "value_bet": value_by_game.get(game_id),
        }
        row["interpretation"] = interpretation(scored, tactical)
        row["market"] = market_context(
            market_by_game.get(game_id, []), scored["probabilities"], scored["actual_outcome"]
        )
        rows.append(row)

    canonical_completed = [
        row for row in matches
        if row.get("home_score") is not None
        and row.get("away_score") is not None
        and fixture_in_window(row, as_of, through)
    ]
    missing = [row for row in canonical_completed if str(row["game_id"]) not in game_ids]

    by_league = {
        league: aggregate([row for row in rows if row["league"] == league])
        for league in baseline.TOP_FIVE
    }
    market_rows = [row["market"] for row in rows if row.get("market")]
    closing_rows = [row for row in market_rows if row["closing_eligible"]]
    market_summary = {
        "all_pre_kickoff": market_loss_summary(market_rows),
        "closing_eligible": market_loss_summary(closing_rows),
        "note": (
            "Market prices are contextual benchmarks captured at different pre-kickoff times; "
            "the closing-eligible subset is the controlled comparison and remains a small sample."
        ),
    }
    driver_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        drivers = row.get("forecast_drivers") or []
        driver_groups[str(drivers[0].get("label") if drivers else "No named driver")].append(row)
    driver_summary = {
        label: aggregate(group) for label, group in sorted(driver_groups.items())
    }

    report = {
        "report_schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "prediction_snapshot": str(args.predictions_file.resolve()),
        "season": str(payload["season"]),
        "model_version": payload.get("model_version"),
        "as_of": as_of.isoformat(),
        "evaluation_through": through.isoformat(),
        "summary": aggregate(rows),
        "by_league": by_league,
        "interpretation_counts": dict(Counter(row["interpretation"] for row in rows)),
        "top_driver_family_results": driver_summary,
        "market_context": market_summary,
        "value_bet_summary": value_summary,
        "coverage": {
            "frozen_calls": len(rows),
            "canonical_completed_fixtures": len(canonical_completed),
            "missing_completed_fixtures": missing,
            "tactical_matches": sum(row["tactical"] is not None for row in rows),
            "market_matches": len(market_rows),
        },
        "largest_misses": sorted(rows, key=lambda row: row["log_loss"], reverse=True)[:10],
        "strongest_correct_calls": sorted(
            [row for row in rows if row["correct_favorite"]],
            key=lambda row: row["actual_probability"],
            reverse=True,
        )[:10],
        "all_matches": sorted(rows, key=lambda row: (row["date"], row["league"], row["game_id"])),
        "guardrail": (
            "Post-match tactical metrics are diagnostic evidence, not retroactive forecast inputs. "
            "Observed dominance can distinguish process from score variance but does not establish causality."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_output = args.markdown_output or args.output.with_suffix(".md")
    markdown_output.write_text(markdown(report), encoding="utf-8")
    print(
        f"Weekend review: calls={len(rows)} tactical={report['coverage']['tactical_matches']} "
        f"missing_frozen={len(missing)}"
    )
    print(f"JSON: {args.output}")
    print(f"Markdown: {markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
