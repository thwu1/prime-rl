Implement a Carver-style systematic trend-following forecast calibration pipeline. Daily price data for four synthetic futures instruments is at `/data/INSTR_{A,B,C,D}.csv` (columns: `date`, `price`). System parameters are in `/data/config.yaml`.

## Methodology

**Blended Volatility Estimation**: Compute daily returns as `price.diff()`. Fast volatility: `ewm(span=days, min_periods=min_periods).std()` on daily returns. Slow volatility: `expanding(min_periods=min_periods).std()` on daily returns. Final vol = `proportion_of_slow_vol * slow_vol + (1 - proportion_of_slow_vol) * fast_vol`, floored at `vol_abs_min`. All parameters under `volatility_calculation` in config.

**EWMAC Raw Forecasts**: For each trading rule with speeds `(Lfast, Lslow)`, the raw forecast is `(ewm(price, span=Lfast).mean() - ewm(price, span=Lslow).mean()) / blended_vol`. This is a vol-normalized EMA crossover producing a dimensionless signal. Three rules in config under `trading_rules`.

**Forecast Scalar Calibration**: For each rule, pool raw forecasts across all instruments by concatenation. Scalar = `average_absolute_forecast / mean(abs(pooled_raw))` after dropping NaN. Apply: `scaled = raw * scalar`, then clip to `[-forecast_cap, +forecast_cap]`.

**Forecast Diversification Multiplier (FDM)**: For each instrument, build a correlation matrix of the scaled+capped forecasts across the three rules (drop rows with any NaN). Average these correlation matrices across instruments element-wise. FDM = `1 / sqrt(w^T * C * w)` where `w` is the forecast weight vector (ordered as in config `forecast_weights`) and `C` is the averaged correlation matrix. Cap FDM at 2.5.

**Combined Forecast**: For each instrument: `FDM * sum(weight_i * scaled_capped_forecast_i)`, clipped to `[-forecast_cap, +forecast_cap]`.

**Subsystem Position**: `(combined_forecast / average_absolute_forecast) * (notional_trading_capital * percentage_vol_target / 100) / (blended_vol * sqrt(252))`.

## Output

Write `/app/output/results.json` with this exact structure:

```json
{
  "forecast_scalars": {
    "ewmac8_32": <float>,
    "ewmac16_64": <float>,
    "ewmac32_128": <float>
  },
  "forecast_diversification_multiplier": <float>,
  "combined_forecasts_last": {
    "INSTR_A": <float>,
    "INSTR_B": <float>,
    "INSTR_C": <float>,
    "INSTR_D": <float>
  },
  "subsystem_positions_last": {
    "INSTR_A": <float>,
    "INSTR_B": <float>,
    "INSTR_C": <float>,
    "INSTR_D": <float>
  },
  "vol_on_last_date": {
    "INSTR_A": <float>,
    "INSTR_B": <float>,
    "INSTR_C": <float>,
    "INSTR_D": <float>
  }
}
```

All `*_last` values use the last non-NaN value in the respective time series. Do not round values; write full float precision.