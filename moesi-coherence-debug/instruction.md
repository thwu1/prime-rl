`/app/moesi_sim.py` is a directory-based MOESI cache coherence protocol simulator. It contains protocol bugs that cause data corruption — the trace `/app/diagnostic.trace` demonstrates the failures when run with `--cores 4 --capacity 8`. Fix `/app/moesi_sim.py` so that it passes its own coherence validation without violations on this trace.

`/app/topology.json` specifies a multi-chiplet NUMA system configuration. Create `/app/numa_coherence.py` implementing a `NUMACoherenceSimulator` class that faithfully models this topology, including its latency model and all configurable features.

Constructor: `NUMACoherenceSimulator(num_cores=8, l1_capacity=8, cores_per_chiplet=4, enable_owner_opt=True, enable_chiplet_cache=True, chiplet_cache_capacity=16)`

Required methods:
- `read(core_id, addr)` — returns the data value
- `write(core_id, addr, data)`
- `verify_coherence()` — returns a list of violation strings (empty if coherent)

Required `stats` dict keys: `total_cycles`, `inter_chiplet_messages`, `memory_writebacks`, `chiplet_cache_hits`, `owner_transitions`, `reads`, `writes`, `hits`, `misses`, `invalidations`

CLI mode: `python3 /app/numa_coherence.py <trace> [--json-stats] [--no-owner-opt] [--no-chiplet-cache]`. With `--json-stats`, output the stats dict as JSON to stdout.

Create `/app/run_comparison.sh` (executable) that drives the NUMA simulator against every `.trace` file in `/app/traces/` in baseline (both configurable features disabled) and optimized (both enabled) configurations, producing three artifacts:

`/app/coherence_analysis.db` — SQLite database with:
- Table `trace_stats` with columns `(trace TEXT, config TEXT, total_cycles INTEGER, inter_chiplet_messages INTEGER, memory_writebacks INTEGER)` and composite primary key `(trace, config)`. `config` values: `'baseline'` and `'optimized'`.
- View `optimization_impact` joining baseline and optimized rows per trace, computing columns `cycle_reduction_pct`, `writeback_reduction_pct`, and `inter_chiplet_reduction_pct` as percentage improvements.

`/app/comparison_chart.svg` — a grouped bar chart showing baseline vs optimized `total_cycles` per trace, with labeled axes and a legend distinguishing the two configurations.

`/app/results.json` — containing:
- `traces`: object keyed by trace filename, each with `baseline` and `optimized` sub-objects holding `total_cycles`, `inter_chiplet_messages`, `memory_writebacks`
- `summary`: object with `avg_cycle_reduction_pct`, `avg_writeback_reduction_pct`, `avg_inter_chiplet_reduction_pct`

Data in `/app/results.json` must be consistent with `/app/coherence_analysis.db`.