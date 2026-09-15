# Scoring Reference Library

Reference implementations of forecaster evaluation models for prediction market analysis.

## Files

- `scoring.py` — Four scoring models:
  - `CalibrationScorer` — Measures forecast accuracy via Brier (quadratic proper scoring) rule
  - `RiskNeutralTrader` — Simulates risk-neutral all-in trading returns (CRRA gamma=0)
  - `KellyTrader` — Simulates Kelly criterion (log-utility, CRRA gamma=1) fractional betting
  - `CRRATrader` — Simulates CRRA utility-optimal betting with configurable risk aversion gamma

- `pairwise.py` — Pairwise comparison model:
  - `SkillEstimator` — Estimates latent forecaster skill via iterative pairwise fitting (Generalized Bradley-Terry)

## Scoring Family

The RiskNeutralTrader, KellyTrader, and CRRATrader form a unified parametric family
controlled by a single risk-aversion parameter gamma:
  - gamma=0 → risk neutral (all-in)
  - gamma=0.5 → moderate power utility
  - gamma=1 → Kelly/log utility

See individual class docstrings for expected input formats and formulas.

## Usage

Each scorer expects clean, pre-processed data. Data quality checks,
deduplication, and filtering of invalid records are the caller's responsibility.

All scorers return `dict[forecaster_id, float]` mappings.
