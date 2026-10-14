# Player-to-team strength experiment - 14 October 2026

An offline player layer is implemented, trained and tested. Team goal models now have a research path that incorporates expected players' lagged ratings, minutes and roles, relative to the team's recent lineup. The tested proxy does not improve forecasts and is not suitable for production injury/counterfactual adjustments. No production model or historical frozen output was changed.

## Data and player lineage

The existing WhoScored cache supplies stable player IDs, match starters, substitution minutes, dismissals, formation goalkeeper slots, nominal roles and final retrospective performance ratings. The private v2 export covers 4,333 players and 162,592 appearances, with all recorded appearances having ratings. It has 10,502 complete team observations and eight explicit missing sides among 10,510 target sides. No current target participant, actual minutes, role or rating enters its prediction inputs.

The six missing sides from the advanced source audit remain quarantined. Two additional usage exceptions are saved with exact paths:

| Source | Issue | Consequence |
|---|---|---|
| `ITA-Serie A_2425/1834886.json`, Napoli-Parma, 31 Aug 2024, away side | Goalkeeper role coverage cannot satisfy the minute contract | Missing usage marker; affected prior-ten-game histories trigger baseline fallback |
| `ITA-Serie A_2425/1834982.json`, Monza-AC Milan, 2 Nov 2024, home side | The cached starting-XI flags do not contain eleven starters | Same explicit fallback, no inferred extra starter |

The first audit also found substitute-goalkeeper role ambiguities. Existing formation goalkeeper slots resolved 19 additional sides. The first player export remains an audit checkpoint at `artifacts/soccer_research_players_20261014/`; only `artifacts/soccer_research_players_20261014_v2/` was used for modeling. The latter includes observations, prior-date feature rows, expected-player plans, code snapshots and SHA-256 manifests linked to all 5,252 rehashed usable event sources.

Player minutes are approximate equivalent-90 exposure: from start/substitution to substitution-off, dismissal or full time, divided by expanded match duration and multiplied by 90. These are not official league minutes. Formation data resolve goalkeeper roles; other substitute roles inherit the replaced player's nominal role, which does not prove exact tactical responsibility.

## Construction and learned relationship

For each player, use at most 20 earlier appearances. Weight final performance ratings by exposure and shrink toward the earlier role mean with a fixed 900-minute prior. The role replacement anchor is the 25th percentile of earlier role-match ratings. This is an explicit operational assumption, not an empirically identified replacement-level footballer or causal value estimate. Player role, rating history and replacement distribution update only after all forecasts on that date have been constructed.

Expected participation uses the previous three team observations with weights 0.5/0.3/0.2, normalized to 990 equivalent player-minutes. The reference lineup is the prior ten team observations with equal match weight. Both are scored using the same current-cutoff player ratings:

`rating_delta = sum((expected_minutes - reference_minutes) / 990 * (shrunk_player_rating - role_replacement_rating))`

This supplies a change from the team strength already represented by recent performance and Elo. A stable lineup contributes zero extra rating regardless of its absolute quality. The downstream model learns home/away log-goal-rate coefficients for each team's change, conditional on the original baseline inputs. The individual provider-derived rating is a lagged performance proxy; only this downstream association is learned here. There is no claim of independently identified attacking/defensive player goal impact, adjusted plus-minus or causal absence value.

Every plan records player IDs, expected/reference minutes, role, rating cutoff, prior exposure, shrinkage and replacement anchor. The code exposes `scenario_delta(...)` for explicitly supplied hypothetical minutes, requires exactly 990 accounted minutes and the exact saved cutoff, and treats unknown/replacement slots as zero excess rating. It produces a rating feature, not an injury fact or validated goal effect.

## Uncertainty and fallback

Saved uncertainty comprises dispersion across the last three lineup scenarios and an approximate independent-player rating standard error. Neither is a calibrated forecast interval or a reliable injury probability. Participation is uncertain when players transfer, return from injury, are suspended, rotate or change role. No historical publication-time injury/availability/expected-lineup records were found in the inspected local artifacts. The existing Transfermarkt importer was inspected as source only; it was not run and no paid/provider-key call was made.

Readiness requires two prior team observations, at least 80% expected rating coverage, no missing usage in the prior ten games and a most-recent observation within 60 days. Otherwise the delta is neutral and the entire non-baseline forecast uses the baseline's exact goal rates and probabilities. There are 10,047 ready team targets before the common event-quality filter. Non-baseline evaluation fallbacks total 82 of 1,714 fixtures in 2024/25 and 57 of 1,751 in 2025/26.

## Fixed ablations and results

Four candidates were declared before evaluating player features. Same population and chronological folds as the advanced-feature report: 1,751 training matches before 2024/25, 3,465 before 2025/26, with 5,216 in final research refits. No historical test-season result was used to tune weights, priors or hyperparameters.

| Candidate | 2024/25 log loss | 2025/26 log loss |
|---|---:|---:|
| [baseline29](baseline29.md) | 0.98806927 | 0.99234392 |
| [usage33](usage33.md) | 0.98790229 | 0.99282664 |
| [ratings31](ratings31.md) | 0.99074761 | 0.99281557 |
| [ratings_usage35](ratings_usage35.md) | 0.99054967 | 0.99327173 |

The rating-only ablation worsens 2024/25 log loss by +0.00267834 (exploratory interval [+0.00039156, +0.00483236]) and 2025/26 by +0.00047165. Usage alone is inconsistent. These results do not establish that player information is useless; they reject promotion of this specific retrospective-rating/usage proxy.

The learned rating coefficients have implausible counterfactual signs. For example, the 2025/26 ratings31 model's own home-player delta coefficient is -0.61298 in log-goal-rate units. A prespecified demonstration takes the first eligible 2025/26 Arsenal home fixture by date, 13 Sep 2025 against Nottingham Forest. Replacing Declan Rice's 87.42 expected minutes with role-replacement minutes raises predicted Arsenal goal rate from 2.10481 to 2.21116 and home-win probability from 64.35% to 67.27%. This was hypothetical, not a claim he was absent. The model was trained through 25 May 2025. This wrong-direction behavior is a concrete reason to reject causal/scenario deployment, rather than conceal the coefficient or force a sign after looking at test outcomes.

## Verification and next evidence needed

Independent checks reconcile 10,510 expected-player plans, 249,525 lagged rating records and all 13,860 held-out prediction rows. Eight fold models were reloaded and reproduced their full saved test predictions; four final model hashes were checked. Seven synthetic regressions cover target/same-date mutation isolation, stable-lineup zero delta, replacement/cutoff accounting, missing/stale usage, substitutions/red cards and exact baseline fallback.

To build a stronger lineup model, the missing inputs are timestamped historical availability and expected participation, reliable transfer/squad membership dates, and validated role/exposure histories. Event-derived or separately estimated player impact remains a distinct next research hypothesis; retrospective performance ratings must not be relabeled as causal impact. New specifications should be fixed before evaluation, with a prospective frozen test rather than repeated tuning on these reused seasons. The future holdout from 15 Oct 2026 remains reserved; no new scheduled job or 2026/27 outcome evaluation was performed.

Deliverables: `pipeline/local_player_strength.py`, `pipeline/export_local_player_strength.py`, `pipeline/research_player_strength.py`, regression and validation tools, four model cards, `artifacts/soccer_research_players_20261014_v2/` and `artifacts/soccer_research_player_models_20261014/`. The latter contains the protocol, all predictions, eight fold models, four final models, metrics, learned coefficients, calibration, bootstrap intervals and the hypothetical scenario evidence. These private artifacts remain git-ignored.

The earlier [advanced-feature report](../soccer_local_features_20261014/README.md), [probability patch review](../soccer_local_features_20261014/PATCH_REVIEW.md), baseline repair and all evaluation outputs remain available. No merge, deployment, provider call, job change or interaction with Claude occurred.
