# Compact workspaces and player comparisons

## Scope

Eight user-requested corrections: smaller Model Lab / Match Review headers; predictions before lengthy commentary; readable Go To highlighting; remove Match Analysis questions; remove player interpretation cards and inline the evidence counts; fit desktop player pitches; fix pass opacity and attack-label clipping; clickable pillar comparison charts.

## Implementation

- Forecast health remains visible as a one-line status with expandable evidence. Frozen/latest labels are unchanged.
- Model Lab loses the three introductory instruction cards in Explain a match. Match review typography and spacing are compacted, not its data.
- Match Analysis question-card renderer is removed; existing stats and plot controls remain.
- Player interpretation cards are removed. Actions/measure counts sit in profile metadata. Pillar overview is collapsed by default and expandable.
- Shared movement lines have a minimum 0.85 opacity and 0.238 pitch-unit shaft width. Previously Combined multiplied 0.24 by 0.55, leaving only 0.132 opacity.
- Attack direction is HTML outside the pitch SVG in both main and drilldown renders; exports retain it. Desktop pitches fit the space below controls, with a 180px floor to avoid unusable charts on short screens. Mobile retains scrolling.
- Pillars open a ranked bar chart under Rank, using existing public pillar scores. Same role and league selected by default, league/all-leagues and role filters, all eligible players, selected player highlighted. Zero is retained; missing is not zero. Queries are batched by 100 eligible IDs and constrained by pillar/role; league lineage is checked. No DB/schema/auth/model changes.
- Shared navigation uses explicit paired foreground/background highlight colours, including keyboard focus. A script version was added to affected pages because browser testing found cached old navigation code.

## Verification

- `node pipeline/tools/check_compact_workspaces.js`: pass (script parsing, removed sections, opacity, label, cohort/missing/zero handling and navigation colours).
- `node pipeline/tools/check_match_analysis_navigation.js`: pass.
- `node pipeline/tools/check_site_polish.js`: pass.
- `node pipeline/tools/check_player_metric_units.js`: pass.
- `python pipeline/tools/check_model_lab_dashboard.py`: pass.
- `python pipeline/tools/check_model_review_dashboard.py`: pass.
- Browser: Kai Havertz Combined / Events, light and dark; 1900x900 desktop full pitch, attack direction and legend visible without scrolling, default collapsed overview.
- Browser: Progression / Striker / Premier League 20 of 20; all leagues 166 of 166; Creation / Striker 20 of 20; Creation / Goalkeeper explicit 0 of 20 unavailable state. Scores agree with profile (Havertz progression 52.5).
- Browser: 390px forecast and pillar views; document width 375px, no horizontal page overflow. Mobile content still scrolls vertically.
- Browser: forecast first screen contains two rows at default desktop viewport; Model Lab shows match selector and forecast rather than tutorial cards; Match Review probabilities are visible on first screen; Match Analysis has no question-card section.
- Navigation focus uses the same CSS rule as hover: light #132b43 on #dce8f5; dark white on #304963. Keyboard focus exercised in both themes.
- Actual Combined PNG and PDF downloaded; PNG inspected directly, PDF rendered with pdftoppm and inspected. Dark passes and complete direction label in both.

## Limits

No claim of exhaustive browser/device coverage or all possible player/filter combinations. Short desktop screens can still need scrolling once optional overview/detail panels are expanded. All-league composite scores retain original league-role percentiles, not league-strength-adjusted ability estimates. Existing data and forecasts were not recalculated.

## Deployment verification

- Production commit: `5020f50b6a4cab67df28c5ed4cb8d855cb5ddf45`.
- Vercel `dpl_GqdEY9WRnwA6xQKPyCab3GStTsej`: READY, production.
- Live forecast first card begins at y=299 in the tested desktop viewport; health disclosure closed by default.
- Live player profile: no interpretation cards; external ATTACKING label present; movement-line minimum opacity 0.85.
- Live Progression drill-through: 20/20 Premier League strikers with selected-player highlight.
