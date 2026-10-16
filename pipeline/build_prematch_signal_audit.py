#!/usr/bin/env python3
"""Build a leakage-safe pre-match tactical signal board for frozen forecasts.

The output is diagnostic research, not a replacement forecast.  It reconstructs
what selected tactical metrics said at the immutable prediction timestamp,
including fields that the registered model did not use.  Post-match information
is deliberately excluded from every rolling window and percentile calculation.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any, Callable

import model_artifact
import score_prediction_snapshot as scoring
import train_match_baselines as baseline


WINDOWS = (3, 5, 10)


def ratio(numerator: Any, denominator: Any) -> float | None:
    if numerator is None or denominator is None or float(denominator) <= 0:
        return None
    return float(numerator) / float(denominator)


def identity(row: dict[str, Any]) -> float | None:
    value = row.get("value")
    return None if value is None else float(value)


METRICS: tuple[dict[str, Any], ...] = (
    {
        "key": "xt_difference", "label": "xT difference", "family": "Threat",
        "source": "observations", "field": "xt_difference", "higher_is_better": True,
        "model_token": "xt_difference", "format": ".2f",
    },
    {
        "key": "open_play_xt_difference", "label": "Open-play xT difference", "family": "Threat",
        "source": "observations", "field": "open_play_xt_difference", "higher_is_better": True,
        "model_token": "open_play_xt_difference", "format": ".2f",
    },
    {
        "key": "npxg_difference", "label": "Non-penalty xG difference", "family": "Chance quality",
        "source": "observations", "field": "npxg_difference", "higher_is_better": True,
        "model_token": "npxg_difference", "format": ".2f",
    },
    {
        "key": "npxg_per_shot", "label": "Non-penalty xG per shot", "family": "Chance quality",
        "source": "observations", "derive": lambda row: ratio(row.get("npxg_for"), row.get("shots")),
        "higher_is_better": True, "model_token": "npxg_per_shot", "format": ".3f",
    },
    {
        "key": "field_tilt_pct", "label": "Field tilt", "family": "Territory",
        "source": "observations", "field": "field_tilt_pct", "higher_is_better": True,
        "model_token": "field_tilt_pct", "format": ".1f",
    },
    {
        "key": "final_third_touch_difference", "label": "Final-third touch difference", "family": "Territory",
        "source": "observations", "field": "final_third_touch_difference", "higher_is_better": True,
        "model_token": "final_third_touch_difference", "format": ".1f",
    },
    {
        "key": "penalty_area_touch_difference", "label": "Penalty-area touch difference", "family": "Territory",
        "source": "observations", "field": "penalty_area_touch_difference", "higher_is_better": True,
        "model_token": "penalty_area_touch_difference", "format": ".1f",
    },
    {
        "key": "box_entries_pass", "label": "Completed-pass box entries", "family": "Territory",
        "source": "observations", "field": "box_entries_pass", "higher_is_better": True,
        "model_token": "box_entries_pass", "format": ".1f",
    },
    {
        "key": "zone14_passes", "label": "Zone 14 passes", "family": "Central access",
        "source": "season_stats", "field": "zone14_passes", "higher_is_better": True,
        "model_token": "zone14_passes", "format": ".1f",
    },
    {
        "key": "final_third_passes", "label": "Final-third passes", "family": "Progression",
        "source": "season_stats", "field": "final_third_passes", "higher_is_better": True,
        "model_token": "final_third_passes", "format": ".1f",
    },
    {
        "key": "progressive_passes", "label": "Progressive passes", "family": "Progression",
        "source": "observations", "field": "progressive_passes", "higher_is_better": True,
        "model_token": "progressive_passes", "format": ".1f",
    },
    {
        "key": "shot_ending_sequences", "label": "Shot-ending sequences", "family": "Sequences",
        "source": "observations", "field": "shot_ending_sequences", "higher_is_better": True,
        "model_token": "shot_ending_sequences", "format": ".1f",
    },
    {
        "key": "progressive_sequences", "label": "Progressive sequences", "family": "Sequences",
        "source": "observations", "field": "progressive_sequences", "higher_is_better": True,
        "model_token": "progressive_sequences", "format": ".1f",
    },
    {
        "key": "box_entry_sequences", "label": "Box-entry sequences", "family": "Sequences",
        "source": "observations", "field": "box_entry_sequences", "higher_is_better": True,
        "model_token": "box_entry_sequences", "format": ".1f",
    },
    {
        "key": "ppda", "label": "Pressing intensity (inverse PPDA)", "family": "Pressing",
        "source": "observations", "field": "ppda", "higher_is_better": False,
        "model_token": "ppda", "format": ".1f",
    },
    {
        "key": "defensive_height", "label": "Defensive height", "family": "Pressing",
        "source": "observations", "field": "defensive_height", "higher_is_better": True,
        "model_token": "defensive_height", "format": ".1f",
    },
)


OBSERVATION_FIELDS = tuple(sorted({
    metric.get("field") for metric in METRICS if metric["source"] == "observations" and metric.get("field")
} | {"npxg_for", "shots"}))


def parse_day(value: Any) -> str:
    return str(value)[:10]


def metric_value(metric: dict[str, Any], row: dict[str, Any]) -> float | None:
    derive: Callable[[dict[str, Any]], float | None] | None = metric.get("derive")
    if derive is not None:
        return derive(row)
    value = row.get(str(metric["field"]))
    return None if value is None else float(value)


def mean(values: list[float]) -> float | None:
    return fmean(values) if values else None


def percentile(value: float | None, population: list[float], higher_is_better: bool) -> float | None:
    if value is None or not population:
        return None
    rank = sum(candidate <= value for candidate in population) / len(population)
    if not higher_is_better:
        rank = 1.0 - rank + (sum(candidate == value for candidate in population) / len(population))
    return round(100.0 * rank, 1)


def standardized_delta(home: float | None, away: float | None,
                       population: list[float], higher_is_better: bool) -> float | None:
    if home is None or away is None or len(population) < 2:
        return None
    spread = pstdev(population)
    if spread <= 1e-12:
        return 0.0
    result = (home - away) / spread
    return round(result if higher_is_better else -result, 3)


def active_numeric_columns(repo: Path, model_version: str) -> list[str]:
    metadata = repo / "artifacts" / "models" / f"{model_version}.json"
    if not metadata.is_file():
        return []
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    return [str(value) for value in payload.get("numeric_columns", [])]


def active_use(metric: dict[str, Any], numeric_columns: list[str]) -> bool:
    token = str(metric["model_token"])
    return any(token in column for column in numeric_columns)


def fetch_inputs(db: Any, leagues: list[str], as_of_day: str) -> tuple[list[dict], list[dict]]:
    observation_columns = (
        "game_id,season,league,match_date,team," + ",".join(OBSERVATION_FIELDS)
    )
    observations = baseline.fetch_pages(
        db.table("ml_team_match_observations")
        .select(observation_columns)
        .eq("observation_schema_version", 2)
        .in_("league", leagues)
        .lt("match_date", as_of_day)
        .order("match_date")
        .order("game_id")
    )
    matches = baseline.fetch_pages(
        db.table("matches")
        .select("game_id,league,date")
        .in_("league", leagues)
        .lt("date", as_of_day)
        .order("date")
        .order("game_id")
    )
    match_by_id = {str(row["game_id"]): row for row in matches}
    season_stats: list[dict] = []
    match_ids = sorted(match_by_id)
    # Keep each PostgREST URL bounded; a whole-history ``in`` predicate can
    # exceed the gateway request-line limit even though the query is valid.
    for offset in range(0, len(match_ids), 100):
        season_stats.extend(baseline.fetch_pages(
            db.table("v_season_stats")
            .select("game_id,team,zone14_passes,final_third_passes")
            .in_("game_id", match_ids[offset:offset + 100])
            .order("game_id")
            .order("team"),
            page_size=500,
        ))
    enriched = []
    for row in season_stats:
        match = match_by_id.get(str(row["game_id"]))
        if match is None:
            continue
        enriched.append(row | {"league": match["league"], "match_date": match["date"]})
    return observations, enriched


def build_metric(metric: dict[str, Any], home: str, away: str, league: str,
                 rows: list[dict], numeric_columns: list[str]) -> dict[str, Any]:
    league_rows = [row for row in rows if row.get("league") == league]
    team_rows: dict[str, list[dict]] = {}
    for team in (home, away):
        team_rows[team] = sorted(
            [row for row in league_rows if row.get("team") == team],
            key=lambda row: (parse_day(row.get("match_date")), str(row.get("game_id"))),
            reverse=True,
        )
    population = [
        value for row in league_rows
        if (value := metric_value(metric, row)) is not None and math.isfinite(value)
    ]
    windows: dict[str, Any] = {}
    for window in WINDOWS:
        values = {}
        counts = {}
        for side, team in (("home", home), ("away", away)):
            candidates = [
                value for row in team_rows[team][:window]
                if (value := metric_value(metric, row)) is not None and math.isfinite(value)
            ]
            values[side] = mean(candidates)
            counts[side] = len(candidates)
        delta = standardized_delta(
            values["home"], values["away"], population, bool(metric["higher_is_better"])
        )
        windows[str(window)] = {
            "home": values["home"], "away": values["away"],
            "home_matches": counts["home"], "away_matches": counts["away"],
            "standardized_home_edge": delta,
        }
    primary = windows["5"] if windows["5"]["home"] is not None and windows["5"]["away"] is not None else windows["3"]
    edge = primary["standardized_home_edge"]
    if edge is None:
        lean = "unavailable"
    elif edge >= 0.35:
        lean = "home"
    elif edge <= -0.35:
        lean = "away"
    else:
        lean = "balanced"
    return {
        "key": metric["key"], "label": metric["label"], "family": metric["family"],
        "source": metric["source"], "higher_is_better": metric["higher_is_better"],
        "active_model_input": active_use(metric, numeric_columns),
        "primary_window": 5 if primary is windows["5"] else 3,
        "lean": lean,
        "home_percentile": percentile(primary["home"], population, bool(metric["higher_is_better"])),
        "away_percentile": percentile(primary["away"], population, bool(metric["higher_is_better"])),
        "windows": windows,
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Pre-match tactical signal audit",
        "",
        f"Immutable forecast timestamp: `{report['as_of']}`.",
        "",
        "This board reconstructs only information available before the frozen forecast. It is a diagnostic comparison layer, not a second prediction model and not a post-match explanation.",
        "",
    ]
    for match in report["matches"]:
        lines += [
            f"## {match['home_team']} vs {match['away_team']}",
            "",
            f"Frozen probabilities: **{match['home_probability']:.1%} / {match['draw_probability']:.1%} / {match['away_probability']:.1%}** (home / draw / away).",
            "",
            f"Signal count: **{match['summary']['home']} home / {match['summary']['balanced']} balanced / {match['summary']['away']} away**; unavailable: {match['summary']['unavailable']}.",
            "",
            "| Family | Metric | Model input? | Home last 5 | Away last 5 | Home pct | Away pct | Lean |",
            "|---|---|---:|---:|---:|---:|---:|---|",
        ]
        for signal in match["signals"]:
            primary = signal["windows"][str(signal["primary_window"])]
            def show(value: Any, decimals: int = 2) -> str:
                return "—" if value is None else f"{float(value):.{decimals}f}"
            lines.append(
                f"| {signal['family']} | {signal['label']} | {'yes' if signal['active_model_input'] else 'no'} | "
                f"{show(primary['home'])} | {show(primary['away'])} | {show(signal['home_percentile'], 0)} | "
                f"{show(signal['away_percentile'], 0)} | {signal['lean']} |"
            )
        lines.append("")
    lines += [
        "## Interpretation guardrails",
        "",
        "- A lean is a standardized descriptive difference, not an estimated win-probability contribution.",
        "- Percentiles compare the rolling team value with same-league pre-cutoff match observations.",
        "- The 5-match window is primary when available; 3-match is the fallback. All 3/5/10 values remain in JSON.",
        "- Zone 14 is derived from completed passes ending centrally between x=66 and x=83 in the existing season-stat view.",
        "- Signals should earn model inclusion through repeated out-of-season lift, stability, calibration, and ablation tests.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--game-id", action="append")
    args = parser.parse_args()

    payload = json.loads(args.predictions_file.read_text(encoding="utf-8"))
    as_of = scoring.parse_utc_datetime(payload["as_of"])
    selected = list(payload.get("predictions", []))
    if args.game_id:
        requested = set(map(str, args.game_id))
        selected = [row for row in selected if str(row["game_id"]) in requested]
        missing = requested - {str(row["game_id"]) for row in selected}
        if missing:
            raise RuntimeError(f"requested game IDs are absent from the frozen slate: {sorted(missing)}")
    if not selected:
        raise RuntimeError("no predictions selected")

    repo = Path(__file__).resolve().parents[1]
    numeric_columns = active_numeric_columns(repo, str(payload["model_version"]))
    leagues = sorted({str(row["league"]) for row in selected})
    db = baseline.db_client()
    observations, season_stats = fetch_inputs(db, leagues, as_of.date().isoformat())
    source_rows = {"observations": observations, "season_stats": season_stats}

    matches = []
    for prediction in selected:
        signals = [
            build_metric(
                metric, str(prediction["home_team"]), str(prediction["away_team"]),
                str(prediction["league"]), source_rows[str(metric["source"])], numeric_columns,
            )
            for metric in METRICS
        ]
        counts = defaultdict(int)
        for signal in signals:
            counts[signal["lean"]] += 1
        matches.append({
            "game_id": str(prediction["game_id"]), "date": prediction["date"],
            "league": prediction["league"], "home_team": prediction["home_team"],
            "away_team": prediction["away_team"],
            "home_probability": float(prediction["home_win_probability"]),
            "draw_probability": float(prediction["draw_probability"]),
            "away_probability": float(prediction["away_win_probability"]),
            "summary": {key: counts[key] for key in ("home", "balanced", "away", "unavailable")},
            "signals": signals,
        })

    report = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "as_of": as_of.isoformat(),
        "season": payload["season"],
        "forecast_kind": payload.get("forecast_kind"),
        "model_version": payload["model_version"],
        "active_numeric_columns_found": len(numeric_columns),
        "method": {
            "primary_window": 5, "fallback_window": 3, "additional_window": 10,
            "lean_threshold_standard_deviations": 0.35,
            "cutoff_rule": "Only matches dated before the immutable forecast date are eligible.",
            "warning": "Descriptive signals are not causal effects or probability contributions.",
        },
        "matches": matches,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown(report), encoding="utf-8")
    print(f"Wrote {len(matches)} match signal boards to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
