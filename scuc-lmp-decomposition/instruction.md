A 24-hour optimal power system scheduling solution is required for the 4-bus network defined in `/app/data/`.

**Inputs:**
- `/app/data/network.m` — MATPOWER-format case file (version 2): buses, generators, branches, generator costs
- `/app/data/gen_config.json` — Generator operational parameters keyed G1–G4 (matching `mpc.gen` row order): minimum up/down times, startup/shutdown ramp limits, initial status (positive = hours-on, negative = hours-off), initial power
- `/app/data/load_profile.csv` — Hourly bus-level demand (hours 0–23, MW)
- `/app/data/reserve_req.json` — Hourly system-wide minimum spinning reserve requirements (MW)

**Required:** Create `/app/solve.py` that writes `/app/results/solution.json`.

The solution must jointly optimize generator commitment and dispatch over 24 hours using the DC power flow approximation, minimizing total cost (production + startup). Enforce: nodal power balance, generator capacity and minimum output when committed, inter-temporal ramp rates (`ramp_10` at column index 17 of `mpc.gen`; startup/shutdown ramps from gen_config), minimum up/down times honoring initial conditions, bidirectional thermal limits on lines with nonzero rateA, and spinning reserve (total committed capacity minus total dispatch must meet or exceed the hourly requirement).

Compute locational marginal prices at each bus. Decompose each LMP into an energy component (uniform across all buses each hour, equal to the marginal energy cost at the reference bus) and a congestion component (the locational premium arising from binding transmission constraints). The bus with `type=3` is the reference bus.

Perform N-1 contingency screening: for each transmission line, evaluate the post-contingency flows on all remaining lines when that line is removed, using the solved dispatch and the DC model. Emergency thermal rating = 130% of rateA.

**Output schema** (`/app/results/solution.json`):
```json
{
  "unit_commitment": {"G1": [1,...], ...},
  "dispatch_mw": {"G1": [200.0,...], ...},
  "line_flow_mw": {"1_2": [150.0,...], ...},
  "lmp": {"Bus1": [14.0,...], ...},
  "lmp_energy": {"Bus1": [14.0,...], ...},
  "lmp_congestion": {"Bus1": [0.0,...], ...},
  "reserve_mw": [50.0, ...],
  "contingency_results": {
    "1_2": {"max_overload_pct": 105.0, "violations": []},
    ...
  },
  "total_production_cost": 0.0,
  "total_startup_cost": 0.0,
  "total_cost": 0.0
}
```

All arrays: 24 entries. Generator keys G1–G4, bus keys Bus1–Bus4, line keys `{fbus}_{tbus}`. Power in MW, costs in $, LMPs in $/MWh.

`reserve_mw[t]`: spinning reserve available in hour t. `contingency_results` keys match `line_flow_mw` keys; `max_overload_pct` = worst |post-contingency flow| / rateA × 100 across all rated remaining lines and hours; `violations` lists `{"line": "x_y", "hour": h, "flow_mw": f, "limit_mw": l}` where flow exceeds the emergency rating.

Production cost includes no-load cost (c0) for committed hours. `total_cost` = production + startup. Solution must be cost-optimal within 0.5% of the LP relaxation bound.
