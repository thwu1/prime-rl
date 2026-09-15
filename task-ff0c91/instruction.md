Build a regime-aware market-making risk pipeline at `/app/` that processes synthetic market data through quantitative finance models, persists results to a SQLite database, and produces a JSON summary report.

## Pre-populated Data

- `/app/data/returns.csv` — 500 daily log returns exhibiting volatility clustering
- `/app/data/orderbook.csv` — 3000 L1 order book ticks with embedded regime shifts and informed-trading episodes
- `/app/config.json` — Pipeline configuration (data paths, risk parameters, quoting parameters, output paths)
- `/app/schema.sql` — SQLite schema defining four output tables (`volatility_forecast`, `regime_state`, `quoting_decision`, `risk_metrics`)

## Deliverables

- A Python package at `/app/pipeline/` implementing the quantitative models required by the test suite
- A pipeline runner that reads config, processes both data files through all models, and populates `/app/results.db` per the schema
- A Makefile at `/app/Makefile` whose `pipeline` target orchestrates the full workflow using `jq` and `sqlite3` CLI tools, and produces `/app/report.json` with keys: `volatility_forecast_count`, `regime_distribution`, `active_quotes_count`, `halted_quotes_count`, `var_99_1d`, `cvar_95`

## Success Criteria

All 44 tests in `/tests/test_state.py` must pass. The test suite is the authoritative specification — it defines every class, method signature, and mathematical invariant the pipeline modules must satisfy, as well as the database and report structure.