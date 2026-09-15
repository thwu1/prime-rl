Two SPICE netlists model a 5V-to-12V boost converter using different rectification topologies:

- `/app/async_boost.cir` -- asynchronous design with a Schottky freewheeling diode
- `/app/sync_boost.cir` -- synchronous design replacing the diode with a second MOSFET as synchronous rectifier, with source-referenced gate drive and a `dead_time` parameter

Both were written for PSPICE and contain multiple compatibility issues that prevent simulation in ngspice (unsupported MOSFET model type, incorrect instance pin ordering, incompatible behavioral source syntax, missing convergence directives). The synchronous design has its dead-time set to zero, permitting destructive shoot-through.

Fix both netlists for ngspice. Then conduct a comparative topology evaluation across the full load range:

1. Optimize the sync converter's dead-time by sweeping at least 5 values between 10 ns and 200 ns at the nominal 60 ohm load.
2. Using the optimal dead-time, evaluate both topologies at five load resistances: 30, 60, 120, 240, and 600 ohm -- spanning heavy load (~400 mA) to light load (~20 mA).
3. Determine whether an efficiency crossover exists across this range -- a load level where the superior topology changes -- and if so, interpolate the crossover resistance from the data.
4. Produce a design evaluation identifying which physical rectification loss mechanisms (diode forward voltage drop, MOSFET channel conduction loss, switching losses, body-diode conduction during dead-time) dominate at each operating extreme and how they shift the topology preference.

Write results to `/app/results/`:

- `deadtime_sweep.csv` -- CSV with header `dead_time_ns,efficiency_pct` and at least 5 data rows with distinct dead-time values
- `optimal_deadtime_ns.txt` -- selected optimal dead-time in nanoseconds
- `efficiency_map.csv` -- CSV with header `load_ohms,async_eff_pct,sync_eff_pct` and exactly 5 rows for loads 30, 60, 120, 240, 600 ohm
- `topology_report.txt`:
  - Line 1: overall recommendation -- `async`, `sync`, or `load-dependent`
  - Line 2: crossover load resistance in ohms if load-dependent, else `N/A`
  - Line 3: one sentence on the dominant rectification loss mechanism at light load (600 ohm) and which topology it favors
  - Line 4: one sentence on the dominant rectification loss mechanism at heavy load (30 ohm) and which topology it favors
  - Lines 5+: engineering recommendation with quantitative justification referencing measured efficiency values at multiple load points

All numeric values should be plain decimal numbers (e.g. `11.87`). Current through a voltage source in ngspice follows passive sign convention. Measurements should be taken over the last 500 us of a 2 ms transient simulation. Leave both netlists at 60 ohm load after all evaluations complete.