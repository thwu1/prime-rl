A SQLite database at `/app/data/market.db` contains a synthetic financial time-series dataset with three normalized tables. Each observation has a classification signal and a temporal event window; many event windows overlap across observations. Configuration parameters are in `/app/data/config.yaml`.

Standard cross-validation on this data produces misleading performance estimates because temporally overlapping event windows allow information to leak between training and test periods.

Build a pipeline, runnable via `make -C /app all` (a stub Makefile exists at `/app/Makefile`), that produces temporal-leakage-free cross-validation splits, evaluates classifier strategies defined in the configuration, and quantifies the probability that the selected backtest strategy is overfit.

Write results to `/app/results/`:

- `cpcv_splits.json` — JSON array of split objects, each containing `"train"` and `"test"` (sorted integer observation-ID lists) and `"test_groups"` (list of integer group indices forming the test partition). Every valid group combination must appear exactly once.

- `pbo_result.json` — `{"pbo": <float in [0,1]>, "num_splits": <int>, "num_strategies": <int>}`