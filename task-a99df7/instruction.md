Build a tool that analyzes chess engine test results using the Sequential Probability Ratio Test (SPRT) and produces statistically rigorous accept/reject/continue decisions. The implementation must produce results that are numerically compatible with the Fishtest distributed testing framework used by the Stockfish chess engine project.

The tool must be invocable as `python3 /app/sprt_analyzer.py`, read test run configurations from `/app/test_runs.json`, and write computed analysis to `/app/results.json`.

## Input format

`/app/test_runs.json` contains an array of test run objects. Each has:
- `id`: string identifier
- `alpha`, `beta`: type I/II error probabilities (typically 0.05)
- `elo0`, `elo1`: SPRT hypothesis bounds (H0: elo=elo0, H1: elo=elo1)
- `elo_model`: one of `"logistic"`, `"normalized"`, or `"BayesElo"`
- `results`: object with optional keys `wins`, `losses`, `draws` (trinomial) and/or `pentanomial` (5-element array of game-pair frequencies ordered LL, LD+DL, DD+WL+LW, WD+DW, WW)

## Output format

`/app/results.json` must be a JSON array of objects, one per input run (same order), each containing:
- `id`: matching input id
- `LLR`: log-likelihood ratio (float)
- `decision`: one of `"accepted"`, `"rejected"`, or `"continue"`
- `elo`: Elo point estimate (float)
- `ci`: 95% confidence interval as `[lower, upper]` (floats)
- `LOS`: likelihood of superiority (float, 0-1)
- `lower_bound`: SPRT lower decision boundary (float)
- `upper_bound`: SPRT upper decision boundary (float)

## Requirements

- All three Elo models (`logistic`, `normalized`, `BayesElo`) must be supported.
- Both trinomial and pentanomial result formats must be handled. When both are present, pentanomial takes precedence for LLR and related computations.
- Numerical results must match Fishtest's production SPRT implementation, which uses a generalized LLR formulation for multinomial distributions rather than the classical binomial approximation.
- scipy is available in the environment.