A market microstructure analysis pipeline at `/app/engine.py` processes L3 order book events from `/data/events.csv` (configured via `/data/config.json`) and writes analytics to `/app/results.json`.

The pipeline computes:

- **Order book snapshots** at configured nanosecond timestamps: top-5 bid/ask depth levels, best bid/ask, mid-price, spread
- **Aggregate trade metrics**: total volume, buy/sell-initiated volume, VWAP
- **Effective spread** and **realized spread** (volume-weighted, basis points), with price impact as their difference
- **Volume bars**: OHLCV bars triggered when cumulative trade volume reaches a configurable threshold
- **VPIN** (Volume-Synchronized Probability of Informed Trading): order flow toxicity metric computed over fixed-volume buckets
- **Kyle's lambda**: price impact coefficient from regressing mid-price changes on signed order flow

The pipeline contains multiple distinct implementation errors. Each bug produces numerically wrong output in a different analytical component. None are syntax errors or crashes — the code runs and produces plausible-looking but incorrect results.

An independent audit database at `/data/audit.db` (SQLite) stores the same event stream under different column names (`ts_ns`, `evt_type`, `oid`, `direction`, `px`, `sz`, `tid`), plus a `reference_checkpoints` table with verified aggregate statistics (trade counts, volumes, volume bar counts, VPIN bucket counts, first-snapshot book state). These checkpoints can help isolate which components are broken.

Diagnose all bugs in `/app/engine.py`, fix them, and run the corrected pipeline to produce a valid `/app/results.json`.