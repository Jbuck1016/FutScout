"""Write reviewable cards from the saved, immutable advanced-feature run."""
import argparse
import json
from pathlib import Path

DESCRIPTIONS = {
    'baseline29':'The original 29 numeric inputs, refitted on the common audited population; Elo omits quarantined results.',
    'npxg33':'Add each side\'s five-game non-penalty xG for/against, scored with strictly prior-date empirical shot bins.',
    'geometry_npxg33':'The same xG ablation with BigChance omitted from the shot bins; geometry and header only.',
    'pass_xt31':'Add each side\'s five-game signed completed-pass xT differential from the repository static grid.',
    'true_entries29':'Replace six legacy box-pass inputs with genuinely open-play outside-to-inside entries. This changes both the phase contract and the origin test.',
    'rich37':'Add npxG for/against, signed pass-xT differential and genuine open-play entries for each side over five games.',
    'adjusted_rich37':'Residualize those eight lagged features against own Elo, prior opponents\' pre-match Elo, past home share, league, shots and shots allowed; Ridge alpha=100 on training rows only.',
}


def write(output, destination):
    report=json.loads((output/'report.json').read_text(encoding='utf-8'))
    validation=json.loads((output/'validation.json').read_text(encoding='utf-8'))
    phase=json.loads((output/'phase_reconciliation.json').read_text(encoding='utf-8'))
    destination.mkdir(parents=True,exist_ok=True)
    table=['| Candidate | 2024/25 log loss | 2025/26 log loss |','|---|---:|---:|']
    for name,meta in report['models'].items():
        scores=[report['folds'][s]['candidates'][name] for s in ('2425','2526')]
        table.append(f"| [{name}]({name}.md) | {scores[0]['log_loss']:.8f} | {scores[1]['log_loss']:.8f} |")
        lines=[f'# {name}', '', DESCRIPTIONS[name], '',
               'Research only. Two independent PoissonRegressor(alpha=1) goal models; training-only median imputation, missing indicators, scaling and league encoding. Rates retain the baseline clipping [0.05, 6]. No hyperparameter search or promotion.', '',
               '| Test season | Train / test matches | Log loss | Brier | RPS | Delta vs baseline [95% interval] |',
               '|---|---:|---:|---:|---:|---|']
        for season,score in zip(('2425','2526'),scores):
            fold=report['folds'][season]; paired=score['paired_vs_baseline']; lo,hi=paired['ci95']
            lines.append(f"| {season} | {fold['train_matches']} / {fold['test_matches']} | {score['log_loss']:.8f} | {score['brier']:.8f} | {score['ranked_probability_score']:.8f} | {paired['delta_log_loss']:+.8f} [{lo:+.8f}, {hi:+.8f}] |")
        lines += ['', 'Paired circular blocks of four observed calendar weeks, 2,000 replicates, seed 20261014. Intervals are exploratory, not adjusted for multiple comparisons. Both seasons were reused before this experiment. Per-league metrics, reliability bins with Wilson intervals, goal errors, scoreline loss and discrete 90% goal-interval coverage are in the saved report.', '',
                  f"Final research refit: {meta['training_matches']} matches. SHA-256: `{meta['sha256']}`.",
                  f"Artifact: `{meta['path']}`. Export manifest: `{validation['export_manifest_sha256']}`.", '',
                  'Cold-start values remain missing and are imputed using training data. Raw cache publication timestamps are unavailable: this proves prior-match chronology, not that every annotation was available at a particular historical forecast cutoff. The xG is an internal bin estimate and the xT is a static pass-value proxy, not independently validated provider models.', '', 'Numeric inputs:', '']
        lines += [f'- `{column}`' for column in meta['columns']]
        (destination/f'{name}.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    text='''# Local advanced-feature reconstruction - 14 October 2026

The existing cache resolves the historical xG/xT export gap. Seven fixed comparisons are complete. None improves both seasons, and every non-baseline log-loss interval crosses zero. No candidate is promoted.

## Sources and lineage

Read-only source: `C:\\Users\\jbuck\\soccerdata\\data\\WhoScored\\events\\<league>_<season>\\<game_id>.json`. All 5,255 snapshot-selected source files exist, totaling 6,686,961,653 bytes. A new private versioned export has 10,510 team-match rows, 10,504 usable rows and 131,836 non-penalty shots (45,215 / 43,128 / 43,493 by season). Six team rows are explicitly quarantined. This is a local reconstruction, not a claim that an old v2 database export was found or verified.

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

TABLE

The strongest 2024/25 point estimate is adjusted_rich37 (delta -0.00172031, interval [-0.00372009, +0.00018206]); its 2025/26 delta is +0.00060762. This supports no promotion. The baseline29 control here also differs from the earlier control because of the population and Elo quality correction.

## Verification and remaining gaps

Independent reconciliation passed for all 131,836 shot priors, 536,010 rolling values, 24,255 saved prediction rows, seven artifact hashes and reloads. Initial post-export source stat checks found no changes; 53 sample file hashes were rechecked, followed by full rehashing of all 5,252 usable files during phase reconciliation. Six synthetic tests cover temporal isolation, same-date updates, missingness, coordinate bins and administrative collisions.

Remaining inputs: a complete existing event file for 1834391; provider publication/availability timestamps; verified historical roster/injury/lineup feeds for a fully informed player layer; sequence provenance if sequence xT is later tested; written provider rights for any new collection, external distribution or deployment use. No new service, credential or provider-key call was used. Existing private offline data rights were not expanded or certified. No football-data.co.uk files were trained on, and no Wyscout API or FBref advanced-feed availability was assumed.

The future holdout remains reserved from 15 Oct 2026, with at least 500 genuine frozen forecasts over 12 weeks before a planned review. No collection job was installed, no 2026/27 results were scored and no historical market odds were used. The worktree is isolated; nothing was merged, pushed or deployed.

Private results: `artifacts/soccer_research_rich_20261014/` (report, protocol, predictions, seven models, validation and phase reconciliation). Probability/metric integration instructions and the scoped patch are in [PATCH_REVIEW.md](PATCH_REVIEW.md). Earlier six-candidate results remain [unchanged in their original report](../soccer_forecast_research_20261014/README.md).
'''.replace('TABLE','\n'.join(table))
    (destination/'README.md').write_text(text,encoding='utf-8',newline='\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    write(args.output,args.destination)
