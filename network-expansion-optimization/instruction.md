A municipal water utility must expand its distribution network to serve four new demand zones. The EPANET hydraulic simulator is pre-built at `/usr/local/bin/runepanet` (usage: `runepanet <input.inp> <report.rpt>`).

The existing network model is at `/app/network.inp` (EPANET Example Network 1 with Hazen-Williams headloss, GPM flow units, 24-hour extended period simulation with time-varying demand pattern). Expansion requirements specifying new junction elevations, demands, pipe connections, and roughness coefficients are in `/app/expansion_spec.json`. Available pipe diameters and per-foot unit costs are in `/app/pipe_catalog.json`.

For each of the four new pipes, select a diameter from the catalog that satisfies the minimum pressure constraint at all junctions across all 24 simulation hours while minimizing total expansion pipe cost within the specified budget.

Write the complete expanded network (original + new components) to `/app/expanded_network.inp` and analysis results to `/app/analysis.json` with these keys:

- `baseline_min_pressure_psi` — minimum junction pressure (psi) across all time steps in the original network before expansion
- `baseline_min_pressure_node` — junction ID where that minimum occurs
- `expanded_min_pressure_psi` — minimum junction pressure across all time steps in the expanded network
- `expanded_min_pressure_node` — junction ID where that minimum occurs
- `pipe_diameters` — object mapping new pipe IDs to selected diameters in inches (e.g. `{"201": 10, ...}`)
- `total_cost_usd` — total expansion pipe cost in USD
- `critical_timestep_hr` — hour at which the system-wide minimum pressure occurs in the expanded network