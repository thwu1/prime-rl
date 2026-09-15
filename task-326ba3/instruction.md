Competition data from a multi-period financial forecasting tournament is at `/app/data/`. Ten teams submitted probabilistic quintile forecasts and portfolio weight decisions for 50 assets across 4 evaluation periods.

Produce `/app/output/evaluation.json` containing a complete competition evaluation with these fields:

- `team_rps`: Per-team average Ranked Probability Score (lower is better)
- `team_ir`: Per-team Information Ratio (higher is better)
- `or_ranking`: Overall competition ranking combining forecasting and investment performance
- `crowd_rps`: RPS of the consensus forecast aggregated from all teams
- `optimal_weights`: Per-asset portfolio weights derived from crowd return expectations and historical covariance, subject to leverage and position size constraints
- `connection_scores`: Per-team coherence between probability forecasts and investment decisions

A competition rules document at `/app/data/competition_spec.txt` describes the data format and output requirements. Some data contains edge cases requiring careful handling.