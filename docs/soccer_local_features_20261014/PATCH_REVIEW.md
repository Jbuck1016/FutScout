# Scoped probability and metric review

The private file `artifacts/soccer_research_review_20261014/probability_metric_review.patch` contains the exact diff from committed backend base `21b7f3c` to this isolated branch's probability/metric implementation. It has not been applied to either operational checkout. Review individual hunks against the backend's uncommitted work; do not replace whole files or automatically apply this base-relative patch to a dirty checkout.

| File | Exact behavior to review |
|---|---|
| `pipeline/score_probabilities.py` | New shared adaptive Poisson matrix, joint omitted tail at most 1e-12, minimum score extent 12; finite nonnegative rates; optional bounded DC correction; no artificial overflow bucket |
| `pipeline/train_match_baselines.py` | H/D/A aggregation calls the shared matrix; validates paired one-dimensional rate arrays |
| `pipeline/model_artifact.py` | Saved scorelines call the same matrix and keep full precision; local score-contract marker; label 'Completed box passes', no false outside-to-inside or open-play assertion |
| `pipeline/generate_match_predictions.py` | Excludes local score-contract metadata from the database payload so no schema migration is needed |
| `pipeline/simulate_league_table.py` | Rate-derived simulation uses the same scores; legacy explicit score distributions retain their existing interpretation |
| `pipeline/soccer_metric_contracts.py` | Separate predicates for successful open-play box completions and true outside-to-inside entries; preserves the old data field |

Regression entry points: `python pipeline/tools/check_soccer_forecast_research.py`, `python pipeline/tools/check_model_artifact.py`, `python pipeline/tools/check_league_table_simulator.py`. The first regression suite also imports the offline research modules, so the scoped implementation patch alone is not a complete test package; the isolated branch contains all tests and dependencies.

Probability repair and label correction can be reviewed independently of advanced-feature selection. No new model has earned promotion. Existing frozen forecasts, model registry entries and jobs are unchanged. Expanded grids increase saved payload size; assess whole-schedule snapshot runtime/size before integration. numpy/scipy are already pipeline dependencies but now also required by the simulator's shared helper.
