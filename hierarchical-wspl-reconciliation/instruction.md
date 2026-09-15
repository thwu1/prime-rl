Implement a Weighted Scaled Pinball Loss (WSPL) evaluation system and a hierarchical quantile forecast reconciliation algorithm for a synthetic retail sales dataset inspired by the M5 forecasting competition.

## Data

- `/app/data/spec.md` — Formal WSPL metric specification with all formulas
- `/app/data/hierarchy.json` — Hierarchy definition (6 aggregation levels, 40 total series, 18 bottom-level Store_Category series)
- `/app/data/history.csv` — Historical sales (365 days) for all 40 series
- `/app/data/actuals.csv` — Ground truth for the 28-day forecast horizon
- `/app/data/base_forecasts.csv` — Incoherent base quantile forecasts (9 quantiles x 40 series); these forecasts were generated independently at each hierarchy level and are neither coherent across levels nor monotonic across quantiles at all levels
- `/app/data/weights.json` — Dollar-value-based weights per series within each aggregation level (weights sum to 1.0 within each level)

## Requirements

Implement the WSPL metric exactly as defined in `/app/data/spec.md`, evaluate the provided base forecasts, then build a reconciliation algorithm that produces hierarchically coherent quantile forecasts and demonstrably lowers the WSPL score. Coherence means that every upper-level quantile forecast equals the sum of the corresponding bottom-level (Store_Category) quantile forecasts for its constituent series. Quantile monotonicity must hold: for each series and horizon, lower quantile levels must have values <= higher quantile levels.

## Output

Write these files:

- `/app/output/scores.json` — JSON object with keys:
  - `base_wspl` (float): WSPL of the original base forecasts
  - `reconciled_wspl` (float): WSPL of the reconciled forecasts
  - `level_wspls` (dict): mapping each level name from hierarchy.json's `level_order` to its per-level WSPL for the reconciled forecasts
- `/app/output/reconciled_forecasts.csv` — Reconciled quantile forecasts in the same CSV format as `base_forecasts.csv` (columns: series_name, quantile, h_1, ..., h_28)