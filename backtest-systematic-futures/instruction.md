A quantitative trading desk's backtesting pipeline was lost during a server migration. The surviving artifacts are spread across multiple storage formats:

- `/app/market.duckdb` — DuckDB database containing historical daily prices (with volume and open interest) across four futures instruments
- `/app/instruments.parquet` — Apache Parquet file with instrument specifications (symbol, point size, portfolio weight)
- `/app/forecast_weights.parquet` — Apache Parquet file with per-instrument, per-rule forecast combination weights
- `/app/config.yaml` — YAML file with global computation parameters (volatility estimation, position sizing, diversification settings)
- `/app/rules.toml` — TOML file with trading rule definitions and forecast scalar estimation settings

The DuckDB CLI is available at `/usr/local/bin/duckdb` for inspecting the database and Parquet files. No algorithmic descriptions or formulas are provided — you must infer the backtesting algorithms from parameter names and your knowledge of systematic futures trading systems.

The database, Parquet, YAML, and TOML data must all be integrated to reconstruct the full pipeline. Write results to `/app/output/`:

- `combined_forecasts.csv` — `date` column plus one column per instrument containing daily combined forecast values
- `positions.csv` — `date` column plus one column per instrument containing daily portfolio positions (unrounded float, in contracts)
- `daily_pnl.csv` — `date` column, `total_pnl` column, and per-instrument `{symbol}_pnl` columns
- `stats.json` — JSON with keys: `sharpe_ratio`, `annual_return_pct`, `max_drawdown_pct`, `calmar_ratio`

All instruments must be aligned on their common date range.