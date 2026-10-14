# Local advanced-feature reconstruction - 14 October 2026

The existing cache resolves the historical xG/xT export gap. Seven fixed comparisons are complete. None improves both seasons, and every non-baseline log-loss interval crosses zero. No candidate is promoted.

## Sources and lineage

Read-only source: `C:\Users\jbuck\soccerdata\data\WhoScored\events\<league>_<season>\<game_id>.json`. All 5,255 snapshot-selected source files exist, totaling 6,686,961,653 bytes. A new private versioned export has 10,510 team-match rows, 10,504 usable rows and 131,836 non-penalty shots (45,215 / 43,128 / 43,493 by season). Six team rows are explicitly quarantined. This is a local reconstruction, not a claim that an old v2 database export was found or verified.

`artifacts/soccer_research_export_20261014_v1/` contains immutable source hashes, team-ID/name lineage, source definitions, prior-bin counts and goals, shot xG, match observations, and prior-date rolling 3/5/10 features. Every feature row lists source game IDs and its latest historical date. No missing event feed is filled with zero. The first failed audit remains separately at `artifacts/soccer_research_export_20261014/source_audit.json`; it is not a valid export.

The xG estimator uses distance/angle/header/BigChance bins, strictly earlier dates, a 20-shot prior at 0.10 and four-decimal half-up rounding. All shots on a date are scored before updating bins. The geometry ablation omits BigChance. Own goals and penalties are excluded. The xT uses the existing static 12x8 grid with clamped coordinates, successful-pass value changes and explicit signed/positive/open-play variants. No sequence xT model is claimed. Historical provider publication times are unavailable.

## Source exceptions

| Game ID | Exact source issue | Treatment / required input |
|---|---|---|
| 1834391 | `GER-Bundesliga_2425/1834391.json`, Holstein Kiel-Bochum, 9 Feb 2025: 22 cached events, ending at minute 0 | A complete local event file is missing. The club confirms the completed 2-2 result. Excluded from this event-model comparison. |
| 1824906 | `FRA-Ligue 1_2425/1824906.json`, Montpellier-Saint-Etienne, 16 Mar 2025: feed ends at minute 62 | Abandoned; 0-2 ratified 2 Apr. No full 90-minute feed exists for this match. Quarantine, not an invented backfill. |
| 1911525 | `FRA-Ligue 1_2526/1911525.json`, Nantes-Toulouse, 17 May 2026: feed ends at minute 21 | Abandoned in the 22nd minute; 0-0 ratified 27 May. The export's phrase 'not a verified full-match outcome' means no played full 90 minutes, not that the administrative score is unknown. |

Official evidence: [Holstein report](https://www.holstein-kiel.de/news-profis/22-gegen-bochum-punkteteilung-nach-intensivem-duell/), [Montpellier abandonment](https://www.asse.fr/fr/actualites/rencontre-definitivement-arretee-a-la-mosson-ac38333), [LFP 2 April decision](https://www.lfp.fr/article/commission-de-discipline-les-decisions-du-2-avril-2025), [Nantes abandonment](https://www.fcnantes.com/articles/article2809.php?num=49200), [Nantes ratification](https://www.fcnantes.com/articles/article2809.php?num=49229).

Rennes-Metz, game 1741059, was already excluded from the accepted 5,255-match snapshot and remains outside this export. The cache also contains 469 administrative OffsideGiven ID collisions in 436 fixtures. Real football events remain unique after excluding that administrative type from identity validation; no pass or shot was deleted to deduplicate across event types.

## Important metric correction

Re-reading and rehashing all 5,252 usable files established that the legacy snapshot box-pass features match **all-phase** completed passes, not the intended SQL open-play contract. All six side/window comparisons agree within rounding (maximum 0.00004445); genuine open-play values differ on nearly every eligible row. Raw totals are 134,024 all-phase completions versus 109,118 open-play completions. For example, Burnley's opening 2023/24 match has nine all-phase completions into the box, including four restarts, and five open-play completions; the next snapshot row uses nine.

The actual UI explanation therefore says 'Completed box passes' without promising open play. The old field's numeric values are untouched. New genuine entries have their own versioned name and exclude starts inside the box. `true_entries29` changes both phase handling and the origin requirement, so it is not a pure origin-only ablation. The earlier snapshot quality gates did not detect the three short/abandoned feeds or this phase mismatch.

## Chronological comparisons

All seven candidates share one population: exclude the three quarantined targets plus any target containing them in either prior-ten-game history. This removes 39 fixtures overall. Elo is recomputed without quarantined outcomes. Training/evaluation sizes: 1,751 -> 1,714 for 2024/25; 3,465 -> 1,751 for 2025/26. Final research refits use 5,216 matches. These scores must not be compared directly with the earlier unfiltered 1,752-match season tables.

| Candidate | 2024/25 log loss | 2025/26 log loss |
|---|---:|---:|
| [baseline29](baseline29.md) | 0.98806927 | 0.99234392 |
| [npxg33](npxg33.md) | 0.98737981 | 0.99243577 |
| [geometry_npxg33](geometry_npxg33.md) | 0.98816787 | 0.99244796 |
| [pass_xt31](pass_xt31.md) | 0.98766998 | 0.99261587 |
| [true_entries29](true_entries29.md) | 0.98776421 | 0.99309076 |
| [rich37](rich37.md) | 0.98707599 | 0.99284120 |
| [adjusted_rich37](adjusted_rich37.md) | 0.98634896 | 0.99295153 |

The strongest 2024/25 point estimate is adjusted_rich37 (delta -0.00172031, interval [-0.00372009, +0.00018206]); its 2025/26 delta is +0.00060762. This supports no promotion. The baseline29 control here also differs from the earlier control because of the population and Elo quality correction.

## Verification and remaining gaps

Independent reconciliation passed for all 131,836 shot priors, 536,010 rolling values, 24,255 saved prediction rows, seven artifact hashes and reloads. Initial post-export source stat checks found no changes; 53 sample file hashes were rechecked, followed by full rehashing of all 5,252 usable files during phase reconciliation. Six synthetic tests cover temporal isolation, same-date updates, missingness, coordinate bins and administrative collisions.

Remaining inputs: a complete existing event file for 1834391; provider publication/availability timestamps; verified historical roster/injury/lineup feeds for a fully informed player layer; sequence provenance if sequence xT is later tested; written provider rights for any new collection, external distribution or deployment use. No new service, credential or provider-key call was used. Existing private offline data rights were not expanded or certified. No football-data.co.uk files were trained on, and no Wyscout API or FBref advanced-feed availability was assumed.

The future holdout remains reserved from 15 Oct 2026, with at least 500 genuine frozen forecasts over 12 weeks before a planned review. No collection job was installed, no 2026/27 results were scored and no historical market odds were used. The worktree is isolated; nothing was merged, pushed or deployed.

Private results: `artifacts/soccer_research_rich_20261014/` (report, protocol, predictions, seven models, validation and phase reconciliation). Probability/metric integration instructions and the scoped patch are in [PATCH_REVIEW.md](PATCH_REVIEW.md). Earlier six-candidate results remain [unchanged in their original report](../soccer_forecast_research_20261014/README.md).
