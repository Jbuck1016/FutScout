"""Versioned training and inference helpers for the domestic match model."""

from __future__ import annotations

import hashlib
import json
import math
import pickle
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.stats import poisson

import evaluate_multiseason_model as multiseason
import train_match_baselines as baseline


ARTIFACT_SCHEMA_VERSION = 1
MODEL_KEY = "domestic_match_poisson"

# Every typed observation currently available to prediction-time rolling
# features.  Keeping this contract here prevents training from seeing richer
# historical fields that live fixture scoring silently omits.
V1_ROLLING_OBSERVATION_METRICS = (
    "passes",
    "passes_completed",
    "shots",
    "open_play_shots",
    "goals_for",
    "goals_against",
    "shots_against",
    "possession_proxy_pct",
    "field_tilt_pct",
    "ppda",
    "defensive_height",
    "average_touch_x",
    "long_ball_pct",
    "build_from_back_pct",
    "directness",
    "progressive_passes",
    "box_entries_pass",
    "crosses",
    "defensive_actions",
    "open_play_shot_pct",
)

V2_ROLLING_OBSERVATION_METRICS = V1_ROLLING_OBSERVATION_METRICS + (
    "final_third_touches",
    "final_third_touches_against",
    "final_third_touch_difference",
    "penalty_area_touches",
    "penalty_area_touches_against",
    "penalty_area_touch_difference",
    "successful_takeons",
    "successful_takeons_against",
    "xt_created",
    "xt_conceded",
    "xt_difference",
    "open_play_xt_created",
    "open_play_xt_conceded",
    "open_play_xt_difference",
    "sequence_count",
    "sequence_count_against",
    "shot_ending_sequences",
    "shot_ending_sequences_against",
    "box_entry_sequences",
    "box_entry_sequences_against",
    "progressive_sequences",
    "progressive_sequences_against",
    "npxg_for",
    "npxg_against",
    "npxg_difference",
    "set_piece_xg_for",
    "set_piece_xg_against",
)

# Backward-compatible alias for callers and tests that explicitly mean schema 1.
ROLLING_OBSERVATION_METRICS = V1_ROLLING_OBSERVATION_METRICS


def observation_metrics(feature_schema_version: int) -> tuple[str, ...]:
    if feature_schema_version == 1:
        return V1_ROLLING_OBSERVATION_METRICS
    if feature_schema_version == 2:
        return V2_ROLLING_OBSERVATION_METRICS
    raise RuntimeError(f"unsupported feature schema version: {feature_schema_version}")


def _day(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_localize(None)
    return timestamp.normalize()


def _instant(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def completed_training_frame(db: Any, seasons: list[str], feature_schema_version: int) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for season in seasons:
        frame = baseline.load_matches(db, season, feature_schema_version)
        frame["season"] = season
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True).sort_values(["date", "game_id"]).reset_index(drop=True)
    baseline.add_pre_match_elo(combined)
    return combined


def train_poisson(frame: pd.DataFrame, feature_schema_version: int,
                  numeric_columns: list[str], algorithm: str) -> dict[str, Any]:
    normalized = multiseason.normalize_model_features(frame)
    missing = sorted(set(numeric_columns) - set(normalized.columns))
    if missing:
        raise RuntimeError(f"training frame is missing requested fields: {missing}")
    home_model = baseline.poisson_model(numeric_columns).fit(normalized, normalized["home_goals"])
    away_model = baseline.poisson_model(numeric_columns).fit(normalized, normalized["away_goals"])
    return {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "model_key": MODEL_KEY,
        "algorithm": algorithm,
        "feature_schema_version": feature_schema_version,
        "class_order": list(baseline.CLASS_ORDER),
        "numeric_columns": list(numeric_columns),
        "training_seasons": sorted(frame["season"].unique().tolist()),
        "trained_through": str(frame["date"].max().date()),
        "training_match_count": int(len(frame)),
        "created_at": datetime.now(UTC).isoformat(),
        "home_model": home_model,
        "away_model": away_model,
    }


def train_compact_poisson(frame: pd.DataFrame, feature_schema_version: int) -> dict[str, Any]:
    numeric = multiseason.select_features(frame, "core_shooting")
    return train_poisson(frame, feature_schema_version, numeric, "compact_poisson")


def save_artifact(artifact: dict[str, Any], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(artifact, handle, protocol=5)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_artifact(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        artifact = pickle.load(handle)  # noqa: S301 - trusted, private model artifact only
    if artifact.get("artifact_schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise RuntimeError("unsupported model artifact schema")
    if artifact.get("model_key") != MODEL_KEY:
        raise RuntimeError("unexpected model key")
    return artifact


def elo_ratings(matches: Iterable[dict[str, Any]], cutoff: pd.Timestamp,
                k: float = 20.0, home_advantage: float = 55.0) -> defaultdict[str, float]:
    ratings: defaultdict[str, float] = defaultdict(lambda: 1500.0)
    cutoff_instant = _instant(cutoff)
    ordered = sorted(
        matches,
        key=lambda row: (
            _instant(row.get("kickoff_at") or f"{row['date']}T12:00:00+00:00"),
            str(row["game_id"]),
        ),
    )
    for row in ordered:
        match_instant = _instant(row.get("kickoff_at") or f"{row['date']}T12:00:00+00:00")
        if match_instant > cutoff_instant:
            continue
        if row.get("home_score") is None or row.get("away_score") is None:
            continue
        home, away = ratings[row["home_team"]], ratings[row["away_team"]]
        expected = 1.0 / (1.0 + 10.0 ** (-((home + home_advantage) - away) / 400.0))
        hg, ag = int(row["home_score"]), int(row["away_score"])
        actual = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
        margin = math.log1p(abs(hg - ag)) if hg != ag else 1.0
        change = k * margin * (actual - expected)
        ratings[row["home_team"]] += change
        ratings[row["away_team"]] -= change
    return ratings


def _prior(rows: list[dict[str, Any]], team: str, league: str, date: pd.Timestamp) -> list[dict[str, Any]]:
    return sorted(
        [row for row in rows if row["league"] == league and row["team"] == team
         and _day(row["match_date"]) < _day(date)],
        key=lambda row: (_day(row["match_date"]), str(row["game_id"])), reverse=True,
    )


def fixture_row(fixture: dict[str, Any], observations: list[dict[str, Any]],
                matches: list[dict[str, Any]], prediction_as_of: pd.Timestamp | None = None,
                feature_schema_version: int = 1) -> dict[str, Any]:
    date = pd.Timestamp(fixture.get("kickoff_at") or fixture["date"])
    history_cutoff = prediction_as_of if prediction_as_of is not None else date
    home_prior = _prior(observations, fixture["home_team"], fixture["league"], history_cutoff)
    away_prior = _prior(observations, fixture["away_team"], fixture["league"], history_cutoff)
    ratings = elo_ratings(matches, history_cutoff)
    record: dict[str, Any] = {
        "game_id": str(fixture["game_id"]), "date": date, "league": fixture["league"],
        "home_team": fixture["home_team"], "away_team": fixture["away_team"],
        "source_match_count": len(home_prior) + len(away_prior),
        "context.team_prior_matches": len(home_prior),
        "context.opponent_prior_matches": len(away_prior),
        "context.team_current_season_matches": sum(
            str(row.get("season")) == str(fixture.get("season")) for row in home_prior
        ),
        "context.opponent_current_season_matches": sum(
            str(row.get("season")) == str(fixture.get("season")) for row in away_prior
        ),
        "context.team_rest_days": None if not home_prior else (_day(date) - _day(home_prior[0]["match_date"])).days,
        "context.opponent_rest_days": None if not away_prior else (_day(date) - _day(away_prior[0]["match_date"])).days,
        "context.team_matches_last_14_days": sum(
            0 < (_day(history_cutoff) - _day(row["match_date"])).days <= 14 for row in home_prior
        ),
        "context.opponent_matches_last_14_days": sum(
            0 < (_day(history_cutoff) - _day(row["match_date"])).days <= 14 for row in away_prior
        ),
        "context.team_matches_last_21_days": sum(
            0 < (_day(history_cutoff) - _day(row["match_date"])).days <= 21 for row in home_prior
        ),
        "context.opponent_matches_last_21_days": sum(
            0 < (_day(history_cutoff) - _day(row["match_date"])).days <= 21 for row in away_prior
        ),
        "elo_home": ratings[fixture["home_team"]], "elo_away": ratings[fixture["away_team"]],
    }
    record["elo_diff"] = record["elo_home"] + 55.0 - record["elo_away"]
    for prefix, prior in (("team", home_prior), ("opponent", away_prior)):
        for metric in observation_metrics(feature_schema_version):
            for window in (3, 5, 10):
                values = [float(row[metric]) for row in prior[:window] if row.get(metric) is not None]
                record[f"{prefix}.{metric}_{window}"] = float(np.mean(values)) if values else None
    # These four predeclared research interactions use the same frozen rolling
    # observations as the ordinary territory and shooting inputs.
    tilt = record["team.field_tilt_pct_5"] - record["opponent.field_tilt_pct_5"] if (
        record["team.field_tilt_pct_5"] is not None and record["opponent.field_tilt_pct_5"] is not None
    ) else None
    boxes = record["team.box_entries_pass_5"] - record["opponent.box_entries_pass_5"] if (
        record["team.box_entries_pass_5"] is not None and record["opponent.box_entries_pass_5"] is not None
    ) else None
    shots = record["team.shots_5"] - record["opponent.shots_5"] if (
        record["team.shots_5"] is not None and record["opponent.shots_5"] is not None
    ) else None
    record["interaction.elo_x_tilt_5"] = None if tilt is None else record["elo_diff"] * tilt
    record["interaction.elo_x_boxes_5"] = None if boxes is None else record["elo_diff"] * boxes
    record["interaction.shots_x_tilt_5"] = None if shots is None or tilt is None else shots * tilt
    record["interaction.shots_x_boxes_5"] = None if shots is None or boxes is None else shots * boxes
    return record


def _explanation_group(feature_name: str) -> str | None:
    name = feature_name.removeprefix("numeric__")
    if name.startswith("missingindicator_"):
        return None
    if name.startswith("interaction."):
        return "Tactical interactions"
    if name.startswith("elo_"):
        return "Team strength"
    if "shots_against_" in name:
        return "Shots allowed"
    if ".shots_" in name:
        return "Shot volume"
    if "field_tilt_pct_" in name:
        return "Field tilt"
    if "box_entries_pass_" in name:
        return "Box entries"
    if "npxg_" in name or "set_piece_xg_" in name:
        return "Chance quality"
    if "xt_" in name:
        return "Expected threat"
    if "penalty_area_touch" in name:
        return "Penalty-area presence"
    if "final_third_touch" in name:
        return "Final-third presence"
    if "sequence_count" in name or "shot_ending_sequences" in name or "box_entry_sequences" in name:
        return "Possession sequences"
    if "progressive_passes_" in name or "directness_" in name:
        return "Progression"
    if "ppda_" in name or "defensive_actions_" in name or "defensive_height_" in name:
        return "Pressing and defensive height"
    if "possession_proxy_pct_" in name or "pass_completion_pct_" in name:
        return "Possession"
    if name.endswith("rest_days"):
        return "Rest"
    return None


def _match_explanation(artifact: dict[str, Any], model_frame: pd.DataFrame,
                       row: pd.Series, probabilities: np.ndarray) -> dict[str, Any]:
    """Summarize exact linear-model contributions in football language."""
    home_model = artifact["home_model"]
    away_model = artifact["away_model"]
    home_prepared = home_model.named_steps["prepare"]
    away_prepared = away_model.named_steps["prepare"]
    home_transformed = np.asarray(home_prepared.transform(model_frame), dtype=float)[0]
    away_transformed = np.asarray(away_prepared.transform(model_frame), dtype=float)[0]
    names = home_prepared.get_feature_names_out()
    home_coefficients = home_model.named_steps["model"].coef_
    away_coefficients = away_model.named_steps["model"].coef_
    away_values = dict(zip(away_prepared.get_feature_names_out(), away_transformed))
    away_coefficient_map = dict(zip(away_prepared.get_feature_names_out(), away_coefficients))
    feature_ledger = []
    grouped: defaultdict[str, float] = defaultdict(float)
    for name, value, home_coefficient, away_coefficient in zip(
        names, home_transformed, home_coefficients, away_coefficients
    ):
        group = _explanation_group(str(name))
        if group is not None:
            away_value = away_values[str(name)]
            away_coefficient = away_coefficient_map[str(name)]
            effect = float(value * home_coefficient - away_value * away_coefficient)
            grouped[group] += effect
            original_name = str(name).split('__', 1)[-1]
            raw_value = row.get(original_name)
            normalized_value = model_frame.iloc[0].get(original_name)
            feature_ledger.append({
                'feature': original_name, 'family': group,
                'raw_value': None if raw_value is None or pd.isna(raw_value) else float(raw_value),
                'model_input': None if normalized_value is None or pd.isna(normalized_value) else float(normalized_value),
                'home_transformed': float(value), 'away_transformed': float(away_value),
                'home_coefficient': float(home_coefficient), 'away_coefficient': float(away_coefficient),
                'home_log_rate_contribution': float(value * home_coefficient),
                'away_log_rate_contribution': float(away_value * away_coefficient),
                'log_rate_balance_contribution': effect,
            })

    home_team, away_team = str(row["home_team"]), str(row["away_team"])
    def number(value: Any, decimals: int = 1) -> str:
        return "not available" if pd.isna(value) else f"{float(value):.{decimals}f}"

    def days(value: Any) -> str:
        return "not available" if pd.isna(value) else str(int(value))

    def rolling_context(text: str) -> str:
        return (
            "The contribution combines the model's standardized 3-, 5-, and 10-match "
            f"inputs for both teams. Last-3 context: {text}"
        )

    detail = {
        "Team strength": (
            f"Pre-match rating: {home_team} {float(row['elo_home']):.0f}, "
            f"{away_team} {float(row['elo_away']):.0f}; the home adjustment is included."
        ),
        "Shot volume": rolling_context(
            f"{home_team} {number(row['team.shots_3'])} shots per match; "
            f"{away_team} {number(row['opponent.shots_3'])}."
        ),
        "Shots allowed": rolling_context(
            f"{home_team} allowed {number(row['team.shots_against_3'])} shots per match; "
            f"{away_team} {number(row['opponent.shots_against_3'])}."
        ),
        "Rest": (
            f"Rest before kickoff: {home_team} {days(row['context.team_rest_days'])} days, "
            f"{away_team} {days(row['context.opponent_rest_days'])} days."
        ),
        "Field tilt": rolling_context(
            f"territorial share was {home_team} {number(row.get('team.field_tilt_pct_3'))}%; "
            f"{away_team} {number(row.get('opponent.field_tilt_pct_3'))}%."
        ),
        "Box entries": rolling_context(
            f"completed pass entries into the box per match were {home_team} "
            f"{number(row.get('team.box_entries_pass_3'))}; {away_team} "
            f"{number(row.get('opponent.box_entries_pass_3'))}."
        ),
        "Progression": rolling_context(
            f"progressive passes per match were {home_team} "
            f"{number(row.get('team.progressive_passes_3'))}; {away_team} "
            f"{number(row.get('opponent.progressive_passes_3'))}."
        ),
        "Pressing and defensive height": rolling_context(
            f"PPDA was {home_team} {number(row.get('team.ppda_3'))}; "
            f"{away_team} {number(row.get('opponent.ppda_3'))}."
        ),
        "Possession": rolling_context(
            f"possession proxy was {home_team} "
            f"{number(row.get('team.possession_proxy_pct_3'))}%; {away_team} "
            f"{number(row.get('opponent.possession_proxy_pct_3'))}%."
        ),
        "Chance quality": rolling_context(
            f"non-penalty xG per match was {home_team} "
            f"{number(row.get('team.npxg_for_3'), 2)}; {away_team} "
            f"{number(row.get('opponent.npxg_for_3'), 2)}."
        ),
        "Expected threat": rolling_context(
            f"xT difference per match was {home_team} "
            f"{number(row.get('team.xt_difference_3'), 2)}; {away_team} "
            f"{number(row.get('opponent.xt_difference_3'), 2)}."
        ),
        "Final-third presence": rolling_context(
            f"final-third touches per match were {home_team} "
            f"{number(row.get('team.final_third_touches_3'))}; {away_team} "
            f"{number(row.get('opponent.final_third_touches_3'))}."
        ),
        "Penalty-area presence": rolling_context(
            f"penalty-area touches per match were {home_team} "
            f"{number(row.get('team.penalty_area_touches_3'))}; {away_team} "
            f"{number(row.get('opponent.penalty_area_touches_3'))}."
        ),
        "Possession sequences": rolling_context(
            f"shot-ending possessions per match were {home_team} "
            f"{number(row.get('team.shot_ending_sequences_3'))}; {away_team} "
            f"{number(row.get('opponent.shot_ending_sequences_3'))}."
        ),
        "Tactical interactions": (
            "This research model combines five-match territory or box-entry differences "
            "with pre-match Elo or shot-volume differences. The reported contribution is "
            "on the standardized goal-rate equations, not a causal effect."
        ),
    }
    drivers = []
    for label, effect in sorted(grouped.items(), key=lambda item: abs(item[1]), reverse=True):
        if abs(effect) < 0.005:
            continue
        drivers.append({
            "label": label,
            "favors": home_team if effect > 0 else away_team,
            "strength": "strong" if abs(effect) >= 0.15 else "moderate" if abs(effect) >= 0.05 else "slight",
            "goal_balance_effect": round(effect, 4),
            "detail": detail[label],
        })

    labels = [home_team, "Draw", away_team]
    favourite = labels[int(np.argmax(probabilities))]
    if favourite == "Draw":
        lead = "The draw is the single most likely result"
    else:
        margin = sorted(probabilities, reverse=True)[0] - sorted(probabilities, reverse=True)[1]
        qualifier = "narrow" if margin < 0.08 else "clear"
        lead = f"{favourite} are {qualifier} favourites"
    driver_clause = "; ".join(
        f"{driver['label'].lower()} favors {driver['favors']}"
        for driver in drivers[:2]
    )
    return {
        "summary": (
            f"{lead}. {driver_clause[0].upper() + driver_clause[1:]}."
            if driver_clause else f"{lead}."
        ),
        "drivers": drivers,
        "feature_ledger": feature_ledger,
        "contribution_units": "home-minus-away log goal rate (not goals or probability points)",
        "explanation_schema_version": 2,
        "inputs": {
            "home_current_season_matches": int(row["context.team_current_season_matches"]),
            "away_current_season_matches": int(row["context.opponent_current_season_matches"]),
            "home_rating": round(float(row["elo_home"]), 1),
            "away_rating": round(float(row["elo_away"]), 1),
            "home_shots_last_3": None if pd.isna(row["team.shots_3"]) else round(float(row["team.shots_3"]), 1),
            "away_shots_last_3": None if pd.isna(row["opponent.shots_3"]) else round(float(row["opponent.shots_3"]), 1),
            "home_shots_allowed_last_3": None if pd.isna(row["team.shots_against_3"]) else round(float(row["team.shots_against_3"]), 1),
            "away_shots_allowed_last_3": None if pd.isna(row["opponent.shots_against_3"]) else round(float(row["opponent.shots_against_3"]), 1),
            "home_field_tilt_last_3": (
                None if pd.isna(row.get("team.field_tilt_pct_3"))
                else round(float(row["team.field_tilt_pct_3"]), 1)
            ),
            "away_field_tilt_last_3": (
                None if pd.isna(row.get("opponent.field_tilt_pct_3"))
                else round(float(row["opponent.field_tilt_pct_3"]), 1)
            ),
            "home_box_entries_last_3": (
                None if pd.isna(row.get("team.box_entries_pass_3"))
                else round(float(row["team.box_entries_pass_3"]), 1)
            ),
            "away_box_entries_last_3": (
                None if pd.isna(row.get("opponent.box_entries_pass_3"))
                else round(float(row["opponent.box_entries_pass_3"]), 1)
            ),
        },
        "method": (
            "The model estimates each team's goal rate, then converts the two goal rates into "
            "home/draw/away probabilities with a Poisson score model."
        ),
        "scope": (
            "This forecast uses only the feature contract embedded in the named model artifact. "
            "The explanation lists grouped contributions to home-minus-away log goal rate, "
            "not literal goals or probability points. The feature ledger retains exact numeric inputs and transformations."
        ),
    }


def scoreline_distribution(home_xg: float, away_xg: float, maximum: int = 8) -> dict[str, float]:
    values: dict[str, float] = {}
    total = 0.0
    for home in range(maximum + 1):
        for away in range(maximum + 1):
            probability = float(poisson.pmf(home, home_xg) * poisson.pmf(away, away_xg))
            values[f"{home}-{away}"] = probability
            total += probability
    return {score: probability / total for score, probability in values.items()}


def build_fixture_frame(fixtures: list[dict[str, Any]], observations: list[dict[str, Any]],
                        matches: list[dict[str, Any]], prediction_as_of: pd.Timestamp | None,
                        feature_schema_version: int) -> pd.DataFrame:
    return pd.DataFrame([
        fixture_row(
            row, observations, matches, prediction_as_of=prediction_as_of,
            feature_schema_version=feature_schema_version,
        )
        for row in fixtures
    ])


def predict_feature_frame(artifact: dict[str, Any], frame: pd.DataFrame,
                          *, include_scorelines: bool = True) -> list[dict[str, Any]]:
    """Score the exact same materialized pre-match frame with different models."""
    if frame.empty:
        return []
    frame = frame.reset_index(drop=True)
    missing = sorted(set(artifact["numeric_columns"]) - set(frame.columns))
    if missing:
        raise RuntimeError(f"fixture builder is missing artifact fields: {missing}")
    model_frame = multiseason.normalize_model_features(frame)
    home = np.clip(artifact["home_model"].predict(model_frame), 0.05, 6.0)
    away = np.clip(artifact["away_model"].predict(model_frame), 0.05, 6.0)
    probabilities = baseline.poisson_result_probabilities(home, away)
    output = []
    for index, row in frame.iterrows():
        one_row = model_frame.iloc[[index]]
        prediction = {
            "game_id": row["game_id"], "league": row["league"], "date": row["date"].isoformat(),
            "home_team": row["home_team"], "away_team": row["away_team"],
            "home_expected_goals": round(float(home[index]), 4),
            "away_expected_goals": round(float(away[index]), 4),
            "home_win_probability": round(float(probabilities[index, 0]), 7),
            "draw_probability": round(float(probabilities[index, 1]), 7),
            "away_win_probability": round(float(probabilities[index, 2]), 7),
            "explanation": _match_explanation(artifact, one_row, row, probabilities[index]),
        }
        if include_scorelines:
            prediction["scoreline_distribution"] = scoreline_distribution(float(home[index]), float(away[index]))
        output.append(prediction)
    return output


def predict_rows(artifact: dict[str, Any], fixtures: list[dict[str, Any]],
                 observations: list[dict[str, Any]], matches: list[dict[str, Any]],
                 prediction_as_of: pd.Timestamp | None = None) -> list[dict[str, Any]]:
    frame = build_fixture_frame(
        fixtures, observations, matches, prediction_as_of,
        int(artifact["feature_schema_version"]),
    )
    return predict_feature_frame(artifact, frame)


def metadata_json(artifact: dict[str, Any], sha256: str) -> dict[str, Any]:
    return {key: value for key, value in artifact.items() if key not in {"home_model", "away_model"}} | {"artifact_sha256": sha256}
