A systematic futures trading backtest system at `/app/` produces incorrect portfolio positions. The Python package at `/app/trading_system/` implements a Carver-style futures backtest across three instruments (BOND, EQUITY, COMMODITY) using EWMAC trend-following and carry rules with vol-target portfolio construction. Market data is in SQLite at `/app/market.db`; configuration is in `/app/system_config.yaml`.

Running `python3 /app/run_backtest.py` executes the pipeline and writes results to `/app/output/`, but the output has multiple errors spanning data access, volatility estimation, signal generation, forecast combination, and position sizing. Some modules contain implementation bugs that silently produce wrong numbers. At least one critical computation is missing entirely — replaced with a non-functional placeholder that must be designed and correctly implemented using quantitative finance domain knowledge. The defects interact across pipeline stages, so upstream errors cascade into downstream outputs. Most defects produce silently wrong numerical output rather than crashes or exceptions.

Produce correct output in `/app/output/`:
- `positions.csv` — DATETIME index, columns: BOND, EQUITY, COMMODITY
- `diagnostics.json` — per-instrument: fdm, last_vol, last_combined_forecast, last_subsystem_position, last_portfolio_position, instrument_weight, idm
- `{INSTRUMENT}_vol.csv` — DATETIME index, column: vol
- `{INSTRUMENT}_raw_forecasts.csv` — DATETIME index, one column per trading rule
- `{INSTRUMENT}_scaled_forecasts.csv` — DATETIME index, one column per trading rule
- `{INSTRUMENT}_combined_forecast.csv` — DATETIME index, column: combined