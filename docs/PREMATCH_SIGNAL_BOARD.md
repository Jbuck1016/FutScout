# Pre-match signal board

## Purpose

The signal board explains what a broad set of tactical indicators said at an immutable forecast timestamp. It is deliberately separate from the production prediction and from post-match diagnostics.

It answers three questions:

1. Which side did each observable tactical metric lean toward before kickoff?
2. Was that metric used by the active model or only retained as research context?
3. Did the 3-, 5-, and 10-match views agree, or was the apparent signal unstable?

The board must never turn the metrics into a second, undocumented probability or imply that a descriptive lean caused the result.

## Data artifact

Run `pipeline/build_prematch_signal_audit.py` against an immutable prediction file. The JSON output is the frontend contract. Each match contains:

- immutable home/draw/away probabilities;
- one record per metric;
- raw 3-, 5-, and 10-match values for both teams;
- the number of valid observations in every window;
- league-relative percentiles;
- a signed standardized home edge;
- a categorical `home`, `away`, `balanced`, or `unavailable` lean;
- an `active_model_input` flag.

## Recommended visual

### Primary: diverging signal matrix

- One row per metric, grouped by Threat, Chance quality, Territory, Central access, Progression, Sequences, and Pressing.
- A centered diverging bar or cell: left favours the away team, right favours the home team.
- Position uses `standardized_home_edge`; clip the displayed scale at ±2 while retaining the exact value in the tooltip.
- Use shape or an explicit `MODEL` badge—not colour alone—to identify active inputs.
- Show raw home and away rolling values plus their league percentiles in the tooltip.
- Default to the 5-match window, with 3 and 10 as user-selectable comparisons.
- Preserve unavailable data as an outlined `N/A` cell; never display missing data as zero.

### Secondary: window-stability strips

For a selected metric, show the signed standardized edge for 3, 5, and 10 matches. This reveals whether a signal is persistent or a short-run spike. All three points share one centered scale.

### Optional: team profile comparison

Use a grouped percentile dot plot rather than a radar chart for precise comparison. Plot the home and away league percentiles on the same horizontal 0–100 scale, one row per metric. Radar/pizza form can be offered as an export view, but the dot plot should remain the analytical default.

## Interaction

- Filters: `All signals`, `Active model inputs`, and `Research-only signals`.
- Family filter for the seven groups above.
- Window control: 3 / 5 / 10.
- Hover/focus text must define the metric, show both raw values, sample counts, percentiles, and the direction convention.
- Link the board to the immutable forecast timestamp and model version.
- Never use the final score or post-match process to reorder the pre-match board.

## Interpretation copy

Use this fixed framing near the visual:

> These are pre-match descriptive indicators, not independent probability contributions. Several measures overlap and may disagree. A metric earns model inclusion only when it adds stable out-of-season predictive lift after team strength and existing inputs are controlled.

## Metric definitions

- **xT difference:** expected threat created minus expected threat conceded per match.
- **Open-play xT difference:** the same measure excluding dead-ball sequences.
- **Non-penalty xG difference:** non-penalty expected goals for minus against.
- **Non-penalty xG per shot:** non-penalty expected goals divided by total shots; a shot-quality proxy.
- **Field tilt:** the team's share of both teams' attacking-third touch proxies.
- **Final-third touch difference:** final-third touches for minus against.
- **Penalty-area touch difference:** penalty-area touches for minus against.
- **Completed-pass box entries:** completed passes entering the penalty area.
- **Zone 14 passes:** passes ending centrally between x=66 and x=83 under the existing site definition.
- **Progressive passes:** passes satisfying the existing distance-and-field-position progression rules.
- **Shot-ending sequences:** possessions ending in a shot.
- **Progressive sequences:** possessions classified as progressive by the sequence pipeline.
- **Box-entry sequences:** possessions reaching the penalty area.
- **Pressing intensity:** inverse PPDA for display, so a higher percentile always means more intense pressing.
- **Defensive height:** average location of defensive actions under the existing event-coordinate definition.

## Promotion boundary

The board is diagnostic. Adding a metric to a model requires, at minimum:

1. complete and stable historical coverage;
2. leakage-safe multi-season walk-forward testing;
3. residual lift after Elo/team strength and existing features;
4. coefficient or importance stability across holdouts;
5. calibration and goal-rate checks by league and favourite band;
6. a shadow period before any lifecycle promotion.
