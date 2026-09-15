Implement a market microstructure fill simulation engine at `/app/` that determines when passive limit orders would be filled against Level-2 market data for high-frequency trading backtesting.

A Rust reference implementation of the core models is provided at `/app/reference/queue.rs`. A complete behavioral specification is at `/app/reference/spec.md`. Market data is at `/app/market_data.npz` and order configuration at `/app/orders.json`.

Implement `/app/microstructure.py` and `/app/run_simulation.py` so that `python3 /app/run_simulation.py` produces correct results in `/app/results.json`.

The engine must reconstruct a live order book from the event stream, track queue positions for each pending order under three distinct models described in the Rust reference code, determine fill outcomes based on market conditions, and compute aggregate trading statistics. All three models must run on the same market data and order set, producing model-specific fill outcomes that match the reference implementation's numerical behavior exactly.