#!/usr/bin/env python3
"""Score deterministic 1X2 value selections from an immutable forecast slate.

The primary ledger uses the median available bookmaker price at the first
eligible market capture after the frozen model call.  Best price is retained
as an explicitly optimistic line-shopping sensitivity, never as the headline
return.  Exactly one outcome can be selected per match.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import score_prediction_snapshot as scoring


OUTCOMES = ("home", "draw", "away")
MODEL_KEYS = (
    "home_win_probability",
    "draw_probability",
    "away_win_probability",
)
FAIR_KEYS = (
    "home_probability_fair",
    "draw_probability_fair",
    "away_probability_fair",
)
ODDS_KEYS = ("home_odds", "draw_odds", "away_odds")


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def prediction_kickoff(prediction: dict[str, Any]) -> datetime:
    value = str(prediction.get("kickoff_at") or prediction["date"])
    if "T" not in value:
        value = f"{value}T12:00:00Z"
    return instant(value)


def load_odds_rows(directory: Path) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("rows", []):
            identity = str(row.get("payload_hash") or (
                row.get("game_id"), row.get("captured_at"), row.get("bookmaker_key")
            ))
            unique[identity] = row
    return list(unique.values())


def capture_summary(rows: list[dict[str, Any]], kickoff: datetime) -> dict[str, Any]:
    if not rows:
        raise ValueError("capture summary requires bookmaker rows")
    captured = instant(rows[0]["captured_at"])
    fair = [statistics.fmean(float(row[key]) for row in rows) for key in FAIR_KEYS]
    medians = [statistics.median(float(row[key]) for row in rows) for key in ODDS_KEYS]
    best = [max(float(row[key]) for row in rows) for key in ODDS_KEYS]
    updates = [instant(row["source_updated_at"]) for row in rows if row.get("source_updated_at")]
    newest_update = max(updates) if updates else None
    source_age = (
        (kickoff - newest_update).total_seconds() / 60 if newest_update else None
    )
    minutes = (kickoff - captured).total_seconds() / 60
    return {
        "snapshot_kind": rows[0]["snapshot_kind"],
        "captured_at": captured.isoformat(),
        "minutes_before_kickoff": minutes,
        "bookmaker_count": len({str(row["bookmaker_key"]) for row in rows}),
        "market_probabilities": dict(zip(OUTCOMES, fair, strict=True)),
        "median_odds": dict(zip(OUTCOMES, medians, strict=True)),
        "best_odds": dict(zip(OUTCOMES, best, strict=True)),
        "source_age_at_kickoff_minutes": source_age,
        "closing_eligible": (
            0 <= minutes <= 90
            and source_age is not None
            and 0 <= source_age <= 180
        ),
    }


def choose_selection(
    model: dict[str, float], market: dict[str, float], median_odds: dict[str, float],
    *, edge_threshold: float, minimum_books: int, bookmaker_count: int,
) -> dict[str, Any] | None:
    if bookmaker_count < minimum_books:
        return None
    candidates = []
    for outcome in OUTCOMES:
        edge = model[outcome] - market[outcome]
        expected_return = model[outcome] * median_odds[outcome] - 1.0
        if edge >= edge_threshold and expected_return > 0:
            candidates.append((expected_return, edge, outcome))
    if not candidates:
        return None
    expected_return, edge, outcome = max(candidates)
    return {
        "outcome": outcome,
        "model_probability": model[outcome],
        "market_probability": market[outcome],
        "probability_edge": edge,
        "model_expected_return_median": expected_return,
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    selections = [row for row in rows if row.get("selection")]
    if not selections:
        return {
            "matches": len(rows), "selections": 0, "wins": 0, "losses": 0,
            "median_price_profit_units": 0.0, "median_price_roi": None,
            "best_price_profit_units": 0.0, "best_price_roi": None,
            "average_probability_edge": None, "average_model_expected_return": None,
            "closing_line_comparisons": 0, "average_closing_probability_value": None,
        }
    closing = [row for row in selections if row["selection"].get("closing_probability_value") is not None]
    median_profit = sum(float(row["selection"]["median_price_profit_units"]) for row in selections)
    best_profit = sum(float(row["selection"]["best_price_profit_units"]) for row in selections)
    return {
        "matches": len(rows),
        "selections": len(selections),
        "wins": sum(bool(row["selection"]["won"]) for row in selections),
        "losses": sum(not bool(row["selection"]["won"]) for row in selections),
        "median_price_profit_units": median_profit,
        "median_price_roi": median_profit / len(selections),
        "best_price_profit_units": best_profit,
        "best_price_roi": best_profit / len(selections),
        "average_probability_edge": statistics.fmean(
            float(row["selection"]["probability_edge"]) for row in selections
        ),
        "average_model_expected_return": statistics.fmean(
            float(row["selection"]["model_expected_return_median"]) for row in selections
        ),
        "closing_line_comparisons": len(closing),
        "average_closing_probability_value": (
            statistics.fmean(float(row["selection"]["closing_probability_value"]) for row in closing)
            if closing else None
        ),
    }


def markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    pct = lambda value: "—" if value is None else f"{value:.1%}"
    lines = [
        "# Frozen-slate value-bet ledger",
        "",
        "This is a retrospective exploratory research ledger, not betting advice. The selection rule was applied without using match outcomes, but it was not prospectively registered for this weekend.",
        "",
        "## Policy",
        "",
        f"- Entry line: first capture after the frozen forecast, before kickoff, with at least {report['minimum_books']} bookmakers.",
        f"- Trigger: model probability exceeds de-vigged market consensus by at least {report['edge_threshold']:.1%} and median-price model EV is positive.",
        "- One selection per match: the qualifying outcome with the highest median-price model EV.",
        "- Primary return: flat one-unit stake at the median available price. Best price is only a line-shopping sensitivity.",
        "",
        "## Headline",
        "",
        f"- Matches evaluated: **{summary['matches']}**",
        f"- Qualifying selections: **{summary['selections']}**",
        f"- Record: **{summary['wins']}–{summary['losses']}**",
        f"- Median-price profit: **{summary['median_price_profit_units']:+.2f} units**",
        f"- Median-price ROI: **{pct(summary['median_price_roi'])}**",
        f"- Best-price sensitivity: **{summary['best_price_profit_units']:+.2f} units ({pct(summary['best_price_roi'])})**",
        f"- Closing-line comparisons: **{summary['closing_line_comparisons']}**",
        "",
        "## Match ledger",
        "",
        "| Match | Pick | Model / market | Median odds | Result | P/L | CLV p.p. |",
        "|---|---|---:|---:|---|---:|---:|",
    ]
    for row in report["matches"]:
        selection = row.get("selection")
        if not selection:
            lines.append(
                f"| {row['home_team']}–{row['away_team']} | No bet | — | — | "
                f"{row['actual_outcome']} | 0.00 | — |"
            )
            continue
        clv = selection.get("closing_probability_value")
        lines.append(
            f"| {row['home_team']}–{row['away_team']} | {selection['outcome']} | "
            f"{selection['model_probability']:.1%} / {selection['market_probability']:.1%} | "
            f"{selection['median_odds']:.2f} | {'Win' if selection['won'] else 'Loss'} | "
            f"{selection['median_price_profit_units']:+.2f} | "
            f"{'—' if clv is None else f'{100 * clv:+.1f}'} |"
        )
    lines += [
        "",
        "A losing selection remains a losing bet. Positive pre-match EV or positive CLV describes the quality of the decision process, not the realised outcome.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions-file", type=Path, required=True)
    parser.add_argument("--weekend-report", type=Path, required=True)
    parser.add_argument("--odds-dir", type=Path, default=Path("artifacts/market_odds"))
    parser.add_argument("--edge-threshold", type=float, default=0.05)
    parser.add_argument("--minimum-books", type=int, default=3)
    parser.add_argument(
        "--policy-file", type=Path,
        default=Path("pipeline/value_selection_policy_v1.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    if not 0 < args.edge_threshold < 1:
        raise ValueError("--edge-threshold must be in (0, 1)")
    if args.minimum_books < 1:
        raise ValueError("--minimum-books must be positive")

    prediction_payload = json.loads(args.predictions_file.read_text(encoding="utf-8"))
    policy = (
        json.loads(args.policy_file.read_text(encoding="utf-8"))
        if args.policy_file.is_file() else None
    )
    predictions, _ = scoring.evaluation_predictions(prediction_payload)
    weekend = json.loads(args.weekend_report.read_text(encoding="utf-8"))
    result_by_game = {str(row["game_id"]): row for row in weekend["all_matches"]}
    raw_rows = load_odds_rows(args.odds_dir)
    captures: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw_rows:
        captures[(str(row["game_id"]), str(row["captured_at"]))].append(row)

    rows = []
    for prediction in predictions:
        game_id = str(prediction["game_id"])
        result = result_by_game.get(game_id)
        if result is None:
            continue
        kickoff = prediction_kickoff(prediction)
        frozen_at = instant(prediction_payload["as_of"])
        summaries = [
            capture_summary(group, kickoff)
            for (capture_game, _), group in captures.items()
            if capture_game == game_id
            and frozen_at <= instant(group[0]["captured_at"]) < kickoff
        ]
        summaries = [item for item in summaries if item["bookmaker_count"] >= args.minimum_books]
        summaries.sort(key=lambda item: instant(item["captured_at"]))
        model = dict(zip(OUTCOMES, (float(prediction[key]) for key in MODEL_KEYS), strict=True))
        row = {
            "game_id": game_id,
            "league": prediction["league"],
            "home_team": prediction["home_team"],
            "away_team": prediction["away_team"],
            "kickoff_at": kickoff.isoformat(),
            "actual_outcome": {"H": "home", "D": "draw", "A": "away"}[result["actual_outcome"]],
            "model_probabilities": model,
            "entry_market": summaries[0] if summaries else None,
            "closing_market": next((item for item in reversed(summaries) if item["closing_eligible"]), None),
            "selection": None,
        }
        if summaries:
            entry = summaries[0]
            selection = choose_selection(
                model, entry["market_probabilities"], entry["median_odds"],
                edge_threshold=args.edge_threshold,
                minimum_books=args.minimum_books,
                bookmaker_count=entry["bookmaker_count"],
            )
            if selection:
                selected = selection["outcome"]
                won = selected == row["actual_outcome"]
                median_odds = float(entry["median_odds"][selected])
                best_odds = float(entry["best_odds"][selected])
                closing = row["closing_market"]
                selection.update({
                    "median_odds": median_odds,
                    "best_odds": best_odds,
                    "best_price_model_expected_return": model[selected] * best_odds - 1.0,
                    "won": won,
                    "median_price_profit_units": median_odds - 1.0 if won else -1.0,
                    "best_price_profit_units": best_odds - 1.0 if won else -1.0,
                    "closing_market_probability": (
                        closing["market_probabilities"][selected] if closing else None
                    ),
                    "closing_probability_value": (
                        closing["market_probabilities"][selected]
                        - entry["market_probabilities"][selected]
                        if closing else None
                    ),
                })
                row["selection"] = selection
        rows.append(row)

    by_outcome = {
        outcome: aggregate([
            row for row in rows
            if row.get("selection") and row["selection"]["outcome"] == outcome
        ])
        for outcome in OUTCOMES
    }
    by_league = {
        league: aggregate([row for row in rows if row["league"] == league])
        for league in sorted({row["league"] for row in rows})
    }
    report = {
        "report_schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "prediction_snapshot": str(args.predictions_file.resolve()),
        "weekend_report": str(args.weekend_report.resolve()),
        "policy_file": str(args.policy_file.resolve()) if policy else None,
        "policy_version": policy.get("policy_version") if policy else None,
        "evaluation_status": (
            "retrospective_exploratory"
            if instant(prediction_payload["as_of"])
            < instant(policy["effective_for_frozen_as_of_on_or_after"])
            else "prospective_pre_registered"
        ) if policy else "unregistered",
        "edge_threshold": args.edge_threshold,
        "minimum_books": args.minimum_books,
        "entry_policy": "first eligible market capture at or after frozen as-of and before kickoff",
        "selection_policy": "largest positive median-price model EV among outcomes with model-minus-market fair probability at least threshold; maximum one selection per match",
        "return_policy": "flat one-unit stakes; median bookmaker price is primary; best available price is sensitivity only",
        "summary": aggregate(rows),
        "by_outcome": by_outcome,
        "by_league": by_league,
        "matches": sorted(rows, key=lambda row: (row["kickoff_at"], row["league"], row["game_id"])),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path = args.markdown_output or args.output.with_suffix(".md")
    markdown_path.write_text(markdown(report), encoding="utf-8")
    print(
        f"Value ledger: matches={report['summary']['matches']} "
        f"selections={report['summary']['selections']} "
        f"profit={report['summary']['median_price_profit_units']:+.2f}u"
    )
    print(f"JSON: {args.output}")
    print(f"Markdown: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
