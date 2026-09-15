/app/strategies.py, /app/stopping.py, and /app/pipeline.py form an active learning evaluation pipeline. Some functions contain algorithmic bugs, others are unimplemented stubs, and the library integration code has API usage errors.

Running `python3 /app/pipeline.py` must produce three files in /app/results/:

**/app/results/strategy_rankings.json** — JSON object with keys: `least_confidence`, `breaking_ties`, `prediction_entropy`, `bald`, `greedy_coreset`, `lightweight_coreset`. Each value is a sorted list of 5 selected sample indices.

**/app/results/stopping_decisions.json** — JSON object with keys: `kappa_average` (list of 6 booleans), `overall_uncertainty` (single boolean), `classification_change` (single boolean).

**/app/results/validation.json** — Cross-validates custom stopping criteria against the `small-text` Python library's stopping criterion classes (`KappaAverage`, `OverallUncertainty`, `ClassificationChange` from `small_text.stopping_criteria`). The pipeline's `run_validation()` function attempts to use these classes but contains API misuse errors that must be diagnosed and corrected. The output must contain:

- `kappa_average_match`: boolean (true when custom and library outputs agree)
- `overall_uncertainty_match`: boolean
- `classification_change_match`: boolean
- `all_match`: boolean (true when all three match)

All match values must be `true`.

Function signatures and docstrings are the authoritative specification for correct behavior. The pipeline's TODO comments specify all call parameters.

Tests verify exact numerical outputs against deterministic reference implementations.
