# Weighted Scaled Pinball Loss (WSPL) — Metric Specification

This document defines the WSPL metric used to evaluate probabilistic (quantile) forecasts organized in a hierarchical aggregation structure.

## 1. Notation

| Symbol | Description |
|--------|-------------|
| `L` | Number of aggregation levels |
| `l` | Index of an aggregation level (1 to L) |
| `N_l` | Number of series at level `l` |
| `i` | Series index within a level |
| `H` | Forecast horizon (H = 28) |
| `h` | Forecast step (1 to H) |
| `Q` | Set of quantile levels: {0.005, 0.025, 0.165, 0.25, 0.5, 0.75, 0.835, 0.975, 0.995} |
| `q` | A quantile level from Q |
| `y_{i,h}` | Actual value for series `i` at horizon `h` |
| `ŷ_{i,q,h}` | Predicted quantile `q` for series `i` at horizon `h` |
| `T` | Number of historical observations (T = 365) |
| `y_{i,t}` | Historical observation for series `i` at time `t` (1 to T) |
| `w_{i,l}` | Weight for series `i` at level `l` (weights sum to 1 within each level) |

## 2. Pinball Loss

For a single observation with actual value `y`, predicted quantile value `ŷ`, and quantile level `q`:

    PL(q, y, ŷ) = q × (y − ŷ)       if y ≥ ŷ
    PL(q, y, ŷ) = (1 − q) × (ŷ − y)  if y < ŷ

Equivalently: `PL(q, y, ŷ) = max(q × (y − ŷ), (1 − q) × (ŷ − y))`

Note: pinball loss is always non-negative.

## 3. Scale Factor

For each series `i`, compute the scale factor from its full historical data:

    s_i = (1 / (T − 1)) × Σ_{t=2}^{T} |y_{i,t} − y_{i,t−1}|

This is the mean absolute first difference of the historical observations.

**Edge case**: If `s_i = 0` (constant history), set `s_i = 1.0` to avoid division by zero.
**Minimum**: If `s_i < 1.0`, set `s_i = 1.0`.

## 4. Scaled Pinball Loss (SPL)

For series `i`, quantile `q`, and horizon `h`:

    SPL_{i,q,h} = PL(q, y_{i,h}, ŷ_{i,q,h}) / s_i

## 5. Per-Level WSPL

For aggregation level `l`:

    WSPL_l = (1 / |Q|) × Σ_{q ∈ Q} [ Σ_{i ∈ level_l} w_{i,l} × ( (1/H) × Σ_{h=1}^{H} SPL_{i,q,h} ) ]

Where:
- `|Q| = 9` (number of quantile levels)
- `w_{i,l}` are the dollar-value-based weights from `weights.json`, summing to 1 within level `l`
- The inner sum averages the SPL across all H forecast horizons
- The middle sum takes a weighted average across series within the level
- The outer sum averages across quantiles

## 6. Overall WSPL

    WSPL = (1 / L) × Σ_{l=1}^{L} WSPL_l

The overall WSPL is the simple average of per-level WSPLs across all L aggregation levels.

## 7. Summary of Computation Steps

1. Read historical data and compute scale factors `s_i` for every series
2. Read weights `w_{i,l}` for each series at each level
3. For each level, quantile, series, and horizon: compute the pinball loss and scale it
4. Average scaled pinball losses across horizons, weight across series, average across quantiles → per-level WSPL
5. Average per-level WSPLs → overall WSPL
