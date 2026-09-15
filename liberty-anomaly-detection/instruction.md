A 4-bit pipelined ripple-carry adder has been synthesized targeting a 45nm standard cell library. The following files are provided in `/app/`:

- `netlist.v` — gate-level netlist using cells from the library
- `cells.lib` — Liberty (.lib) timing characterization for the standard cells
- `design.v` — original RTL source
- `cells_sim.v` — Verilog behavioral models for the standard cells
- `constraints.sdc` — SDC timing constraints (target clock period: 0.250 ns / 4 GHz)

The ripple-carry implementation is suspected to violate timing at the target frequency due to its carry-chain structure.

Produce the following deliverables:

1. **`/app/timing_report.json`** conforming to this schema:

```json
{
  "original": {
    "total_cells": <int>,
    "cell_counts": {"<cell_type>": <count>, ...},
    "total_area_um2": <float>,
    "critical_path_delay_ns": <float>,
    "critical_path_stages": [{"cell": "<type>", "instance": "<name>", "arc": "<from>-><to>"}],
    "setup_time_ns": <float>,
    "clock_period_ns": <float>,
    "worst_slack_ns": <float>,
    "meets_timing": <bool>
  },
  "optimized": {
    "netlist_path": "/app/optimized_netlist.v",
    "total_cells": <int>,
    "total_area_um2": <float>,
    "critical_path_delay_ns": <float>,
    "meets_timing": <bool>,
    "worst_slack_ns": <float>
  },
  "simulation_verified": <bool>,
  "max_frequency_mhz": <float>
}
```

All timing values must be derived from the Liberty characterization data provided in `cells.lib`, not estimated or hardcoded. Cell area values must likewise come from the library.

2. **`/app/optimized_netlist.v`** — a re-synthesized gate-level netlist of the same design that achieves lower critical path delay than the original ripple-carry implementation.

Both the original and optimized gate-level netlists must be verified for functional correctness through simulation against the RTL behavior.