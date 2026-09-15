`/app/framework.py` simulates a memory management writeback throttling loop. Multiple concurrent writer tasks dirty pages across backing storage devices (BDIs) of different write bandwidths. Each tick, a writeback mechanism flushes dirty pages at each device's bandwidth rate. The framework needs a controller module at `/app/controller.py` that dynamically throttles writer rates to maintain the system's total dirty page fraction near a target setpoint without exceeding a hard limit.

Study `/app/framework.py` thoroughly — its docstring specifies the required controller interface (function signatures, CONFIG dictionary keys) and the simulation loop reveals exactly how the controller is invoked each tick and how its outputs affect system behavior. Workload scenarios are defined in `/app/scenarios.json`.

The controller must simultaneously satisfy all three scenarios (`symmetric`, `bursty`, `asymmetric`). Run `python3 /app/framework.py` to produce per-scenario metrics and timeseries CSVs in `/app/output/`. A correct controller will achieve:

- Dirty ratio converging to within ~10% of the configured setpoint in steady state (tail quarter)
- Minimal ticks where dirty ratio exceeds the hard limit
- Stable tail-quarter dirty ratio with low oscillation
- All pauses non-negative and bounded by the configured maximum
- Bandwidth-proportional device fairness — faster devices should hold proportionally larger dirty page shares in steady state
- Aggregate write throughput utilizing a large fraction of available device bandwidth

After the simulation, produce two additional outputs:

- `/app/output/convergence.png` — a `gnuplot` chart plotting dirty ratio versus tick for all three scenarios, with the setpoint drawn as a horizontal reference line
- `/app/output/summary.json` — use `jq` to merge `avg_tail_dirty_ratio`, `max_pause_ms`, and `avg_tail_throughput` from each scenario's metrics file in `/app/output/` into a single JSON object keyed by scenario name