`/app/src.tar.gz` contains archived Rust source from an HFT backtesting framework. The framework implements several distinct models — each with different assumptions about market microstructure — for estimating whether resting limit orders would have been filled during historical market activity on a reconstructed L2 order book.

Binary market event data, order specifications, and configuration are in `/app/data/`. The event record layout is documented in `/app/data/layout.txt`. Required output schemas are in `/app/data/output_schema.json`.

Produce `/app/fill_simulator.py` that writes:

- `/app/results.json` — per-order simulation output under every model specified in `/app/data/config.json`
- `/app/analysis.json` — comparative model analytics

Both files must conform to `/app/data/output_schema.json`. Results must faithfully reproduce the behavior of the Rust implementations when applied to the provided event stream and orders. Quantities should be rounded to 6 decimal places.