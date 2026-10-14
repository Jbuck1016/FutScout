"""Write reviewable model cards from an already completed offline run."""
import argparse
import json
from pathlib import Path

DESCRIPTIONS = {
    "baseline29": "Existing 29-input territory Poisson model; the goal-rate fit is unchanged. Score probabilities now use the shared adaptive grid.",
    "compact17": "Control using Elo, rest, shots and shots allowed; excludes field tilt and completed box passes.",
    "raw_advanced35": "Baseline plus five-match PPDA, progressive passes and defensive height for both teams.",
    "adjusted_advanced35": "Baseline plus six residual features. Five-match PPDA/progressive passes are log1p transformed; defensive height stays in coordinate units. Training-only ridge models (alpha=100) adjust each metric for own Elo, mean prior opponents' pre-game Elo, prior home-match share, league, shots and shots allowed. These are adjustments to lagged rolling metrics, not reconstructed opponent-adjusted event totals or causal effects.",
    "decay365_baseline29": "Baseline with a fixed 365-day exponential half-life on training-match weights; no half-life search.",
    "dc_baseline29": "Baseline rates with a Dixon–Coles low-score correction. Rho is fitted on the last 20% of training dates, using rates fitted on earlier dates, then carried into a full-training refit. Fixed bounds [-0.15, 0.025] guarantee positive correction factors throughout the clipped goal-rate domain. This tests a bounded post-fit correction, not a full joint attack/defence Dixon–Coles model.",
}


def write_cards(run: Path, destination: Path):
    report = json.loads((run/'report.json').read_text(encoding='utf-8'))
    validation = json.loads((run/'validation.json').read_text(encoding='utf-8'))
    destination.mkdir(parents=True, exist_ok=True)
    table = ['| Candidate | 2024/25 log loss | 2025/26 log loss |', '|---|---:|---:|']
    for name, model in report['models'].items():
        first, second = [report['folds'][s]['candidates'][name] for s in ('2425', '2526')]
        table.append(f"| [{name}]({name}.md) | {first['log_loss']:.6f} | {second['log_loss']:.6f} |")
        lines = [f'# Model card: {name}', '', DESCRIPTIONS[name], '',
            '**Status: offline research only. No model promoted, registered, merged or deployed.**', '',
            '## Intended use and population', '',
            'Pre-match home/draw/away and scoreline forecasts for the five covered European domestic leagues. '
            'One row per match, with home/away goals as training targets. This is a reconstruction using prior completed match dates, '
            'not a genuinely frozen Thursday slate; publication delays and provider revisions cannot be reconstructed from this export.', '',
            f"Final fit: {model['training_matches']:,} matches, 2023-08-11 through 2026-05-24. "
            'Earlier seasons train each fold; all candidates use the identical 1,752 fixtures per evaluation season. '
            'These seasons were already reused by earlier research and are development evaluations.', '',
            '## Training and feature contract', '',
            'Two scikit-learn PoissonRegressor(alpha=1, max_iter=2000) pipelines. Numeric medians, missingness indicators, '
            'standardization and league one-hot encoding fit on training rows only. Rest is clipped to 0–30 days; predicted goal rates '
            'are clipped to 0.05–6.0. Elo starts at 1500 with K=20 and home adjustment 55, updating after prior matches. '
            'Five-match schedule context excludes the target date and uses opponents’ ratings before those historical matches. '
            'Rolling snapshot features may use fewer than five games at cold starts; missing values remain missing until training-only imputation.', '',
            'The field named box_entries_pass means completed open-play passes ending in the box, including within-box passes. '
            'Field tilt is share of final-third touch proxies; PPDA uses this repository’s broad defensive-action set. '
            'Metric names must not be treated as provider-standard definitions.', '',
            '## Results', '',
            '| Evaluation season | Log loss | Brier (sum over 3 classes) | RPS | Top-label ECE | Δ log loss vs baseline [95% interval] |',
            '|---|---:|---:|---:|---:|---|']
        for season in ('2425', '2526'):
            value = report['folds'][season]['candidates'][name]
            paired = value['paired_vs_baseline']
            low, high = paired['ci95']
            lines.append(f"| {season} | {value['log_loss']:.6f} | {value['brier']:.6f} | "
                         f"{value['ranked_probability_score']:.6f} | {value['calibration_error']:.6f} | "
                         f"{paired['delta_log_loss']:+.6f} [{low:+.6f}, {high:+.6f}] |")
        lines += ['', 'Lower proper scores are better. Paired uncertainty uses 2,000 circular moving-block draws of four observed '
            'calendar weeks. Intervals are exploratory and not adjusted for trying multiple candidates. Full JSON includes per-league '
            'scores, classwise reliability bins with counts and descriptive Wilson intervals, scoreline log loss, goal MAE, and '
            '90% discrete goal interval coverage/width. Sparse bins and only two season transitions limit inference.', '',
            '## Decision and deployment limits', '',
            'Retain the existing model. No new challenger improves both seasons. All new feature/decay/DC variants worsen 2025/26. '
            'Do not select a winner from one favorable metric, league or fold. DC rho changes sign across folds and reaches its '
            'positive bound in the second fold, so this result does not establish that all Dixon–Coles formulations fail.', '',
            'The research artifact requires the offline research inference helper and its feature contract; it is deliberately '
            'not a drop-in production model_artifact bundle. Advanced adjustments need an auditable live schedule/history feature '
            'builder and identical cutoff before any shadow rollout. Genuine forecasts must be frozen prospectively.', '',
            'No odds entered training, adjustment, calibration or selection. Closing odds from earlier reports are not a fair '
            'same-time Thursday comparison. No profit claim follows from these scores.', '',
            '## Artifact and reproducibility', '',
            f"- Local artifact: `artifacts/soccer_research_20261014/{name}.pkl`",
            f"- SHA256: `{model['sha256']}`",
            f"- Snapshot SHA256: `{report['protocol']['snapshot_sha256']}`",
            f"- Full-data rho: `{model['rho']}`",
            f"- Reload check: {validation['model_reloads'][name]['matches']} historical rows, passed.",
            '- Environment and code hashes: local `report.json` and `validation.json`.', '',
            '## Numeric feature list', '', *[f'- `{column}`' for column in model['columns']], '']
        (destination/f'{name}.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    summary = [
        '# Soccer forecast research checkpoint — 14 October 2026', '',
        'The isolated branch fixes inconsistent score probabilities and reproduces the current model exactly. '
        'Six historical comparisons are complete; the new feature, decay and low-score candidates do not earn promotion.', '',
        '## Location and scope', '',
        '- Branch: `research/soccer-forecast-20261014`, starting from backend commit `21b7f3c`.',
        '- Worktree: `C:\\Users\\jbuck\\Documents\\Codex\\2026-10-13\\task-2\\soccer-forecast`.',
        '- Operational, backend and Claude design worktrees were only read; no source checkout changes, jobs, directory renames, database writes, provider-key calls, merge, push or deployment.',
        '- Public web reads checked method references and data-use restrictions. No provider data was downloaded.', '',
        '## Verified repairs', '',
        'Headline H/D/A, saved scorelines and rate-based simulation now share one Poisson score calculation. '
        'The grid expands until omitted joint mass is at most 1e-12; no tail is collapsed into an artificial maximum-score bucket. '
        'New saved probabilities retain full precision and carry a local score-contract marker. The marker is excluded from '
        'database columns, avoiding an unrequested schema change. Existing frozen files are untouched.', '',
        'The box-pass explanation now correctly includes within-box completions. The legacy feature values are preserved; '
        'a separately named, tested outside-to-inside predicate is available for a future versioned raw-event rebuild.', '',
        '## Reproduction and validation', '',
        '- Data: 5,255 matches (1,751 / 1,752 / 1,752), five leagues, 2023-08-11 through 2026-05-24; saved historical data-quality gates pass.',
        '- Original 0–12 calculation reproduced both archived baseline log losses exactly: 0.9872384997052166 and 0.9926423175874235.',
        '- Full-data baseline goal rates match the saved primary model exactly on 143 spread-out rows (maximum difference 0).',
        '- Independently reconciled 21,024 prediction rows, equal evaluation populations, proper scores, six artifact hashes and reloads.',
        '- Regression checks: shared result/scoreline/simulation mass, independent Skellam agreement, tails, zero/extreme/invalid rates, DC marginals, old explicit distributions, chronology, missingness, box-entry definition and serialization.',
        '- Existing model-artifact and league-table checks also pass.', '',
        '## Candidate comparisons', '', *table, '',
        'These are exploratory evaluations on previously reused seasons. The tiny baseline score change after the repair is due '
        'to removal of 0–12 truncation, not retraining improvement. The 2025/26 maximum H/D/A change from 0–12 is 0.00003146. '
        'The larger 0–8 versus 0–12 defect exceeds one percentage point for some rates within the supported range.', '',
        'The new advanced candidates use reliable lagged PPDA, progression and defensive-height fields. Adjustment reduces '
        'their 2025/26 regression but does not beat the baseline. The 365-day decay and bounded DC correction also regress. '
        'More complexity is deferred until a new hypothesis has independent data and a clean prospective test.', '',
        '## Prospective gate and remaining gaps', '',
        'A protocol was saved before this run: reserve forecasts from 15 October 2026 onward; require at least 500 matched '
        'forecasts across 12 genuine frozen weeks before a planned review. This is a reserved evaluation design, not an '
        'installed collection job or already completed holdout. The present run never scores 2026/27 outcomes. '
        'Same eligible fixtures, same publication cutoff, model/data hashes and pre-kickoff market snapshots are required. '
        'Do not reconstruct missed slates after results.', '',
        'Read [the feature and rights gap report](FEATURE_GAPS.md) before extending data or integrating a candidate. '
        'Historical xG/xT evidence exists in prior reports, but a complete versioned offline feature/observation export is missing. '
        'A WhoScored commercial/training rights grant was not found in inspected files. No new data service was purchased.', '',
        '## Local outputs and commands', '',
        '`artifacts/soccer_research_20261014/` contains protocol.json, report.json, validation.json, historical_predictions.csv '
        'and six .pkl research artifacts. These local private outputs are git-ignored. Model cards and implementation are committed separately.', '',
        '```powershell',
        'python pipeline/tools/check_soccer_forecast_research.py',
        'python pipeline/tools/check_model_artifact.py',
        'python pipeline/tools/check_league_table_simulator.py',
        'python pipeline/tools/validate_soccer_research_run.py --source C:\\Users\\jbuck\\arsenal-analytics-backend --output artifacts/soccer_research_20261014',
        '# Re-run into a NEW directory; existing run outputs are never overwritten:',
        'python pipeline/research_soccer_forecasts.py --source C:\\Users\\jbuck\\arsenal-analytics-backend --output artifacts/soccer_research_new',
        '```', '',
    ]
    (destination/'README.md').write_text('\n'.join(summary), encoding='utf-8', newline='\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    write_cards(args.run, args.destination)
