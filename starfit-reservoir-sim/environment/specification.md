# Cascade Reservoir System Specification

## System Architecture

Three reservoirs connected in series by river channel reaches:

```
[Lateral 0] --> [Reservoir 0] ---> (Reach 0) ---> [Reservoir 1] <-- [Lateral 1]
                                                        |
                                                   (Reach 1) ---> [Reservoir 2] <-- [Lateral 2]
                                                                       |
                                                                  [Downstream]
```

Each reservoir receives lateral inflows (from tributaries) plus routed outflows
from the upstream reservoir (if any). The downstream demand point is evaluated
at Reservoir 2's outflow.

## Data Format

Input data is at `/app/data/cascade.nc` (NetCDF4). Parameters are stored as
variables indexed by `n_reservoirs` (size 3) and `n_reaches` (size 2). The
global attribute `demand_target_cms` specifies the downstream demand. Load
with `/app/reservoir/io_utils.py`.

## Single Reservoir Simulation

Each reservoir is simulated day-by-day using modules in `/app/reservoir/`:

- **NOR** (`nor.py`): seasonal storage targets as % of capacity using Fourier
  decomposition. Both upper and lower bounds use: `mu + alpha*sin(2*pi*w/52) +
  beta*cos(2*pi*w/52)`, clamped to `[min, max]`.
- **Release** (`release.py`): STARFIT-based release with standardized inflow
  computed as deviation from mean: `i_std = (v_f / v_m) - 1.0`.
- **Simulation** (`simulation.py`): mass balance accounting where negative
  storage protection must adjust the recorded release to maintain conservation.

**Availability status** (dimensionless):
```
avail = (100 * storage / capacity - NOR_lo) / (NOR_hi - NOR_lo)
```

## Muskingum Channel Routing

Outflows from an upstream reservoir are routed through the connecting channel
reach using the Muskingum method before arriving at the downstream reservoir.

### Coefficients

Given travel time `K` (days), weighting factor `x` (dimensionless), and time
step `dt` (days):

```
D  = K*(1 - x) + dt/2
C0 = (dt/2 - K*x) / D
C1 = (dt/2 + K*x) / D
C2 = (K*(1-x) - dt/2) / D
```

Constraints: `C0 + C1 + C2 = 1` (mass conservation), all `Ci >= 0` (stability).

### Routing Equation

```
Q_out(t) = C0 * Q_in(t) + C1 * Q_in(t-1) + C2 * Q_out(t-1)
```

Initial condition: `Q_out(0) = Q_in(0)` (assumed steady state at start).

Use `dt = 1.0` day throughout.

## Cascade Simulation Loop

For each day `t = 0, 1, ..., T-1`:

1. Simulate Reservoir 0 with inflow = `lateral_inflow_0[t]`
2. Route Reservoir 0's outflow through Reach 0 to get `routed_0[t]`
3. Simulate Reservoir 1 with inflow = `lateral_inflow_1[t] + routed_0[t]`
4. Route Reservoir 1's outflow through Reach 1 to get `routed_1[t]`
5. Simulate Reservoir 2 with inflow = `lateral_inflow_2[t] + routed_1[t]`

The routing at each step uses the incrementally built outflow series. On day
`t`, the router computes routed outflow using:
- `Q_in(t)` = upstream outflow just computed for this day
- `Q_in(t-1)` = upstream outflow from previous day
- `Q_out(t-1)` = routed outflow from previous day

## Operating Policies

### Independent Policy

Each reservoir operates based solely on its own NOR and storage level, with
no inter-reservoir communication.

### Coordinated Policy

Upstream reservoirs adjust releases based on downstream reservoir states.

For reservoir `i` (where `i = 0` or `1`), after computing the independent
release via `simulate_day`:

1. Compute downstream reservoir `i+1`'s availability from its **start-of-day**
   storage (before any reservoir is simulated for that day):
   ```
   ds_avail = (100 * storage_{i+1}/cap_{i+1} - NOR_lo_{i+1}) / (NOR_hi_{i+1} - NOR_lo_{i+1})
   ```

2. Compute coordination factor:
   ```
   factor = 1.0 + 0.5 * (0.5 - ds_avail)
   factor = clamp(factor, 0.5, 1.5)
   ```

3. Apply to release (then recompute mass balance):
   ```
   release_coordinated = release_independent * factor
   ```
   Recompute storage change, enforce non-negative storage and capacity bounds,
   recalculate spill and outflow from the adjusted release.

**Reservoir 2** (most downstream) operates with demand awareness:
- After computing its standard release via `simulate_day`, if
  `outflow < demand_target` and `storage > cap * NOR_lo / 100`, increase
  release by the minimum of the demand deficit and the available excess
  storage converted to a daily flow rate:
  ```
  available_excess_mcm = max(0, storage - cap * NOR_lo / 100)
  available_excess_cms = available_excess_mcm * 1e6 / 86400
  extra = min(demand_target - outflow, available_excess_cms)
  release += extra
  ```
  Then recompute mass balance with the adjusted release.

**Important**: In coordinated mode, all three reservoirs must be simulated
in upstream-to-downstream order within each timestep.

## Performance Metrics

Evaluated at the downstream demand point (Reservoir 2's outflow):

### Reliability (R)
Fraction of days where outflow meets or exceeds the demand target:
```
R = (1/T) * sum( I(Q_out(t) >= demand_target) for t in 1..T )
```

### Resilience (Res)
Probability of transitioning from an unsatisfactory to a satisfactory state:
```
Res = count(t : Q_out(t) < demand AND Q_out(t+1) >= demand, t=1..T-1) /
      count(t : Q_out(t) < demand, t=1..T-1)
```
If there are no unsatisfactory periods, resilience = 1.0.

### Vulnerability (V)
Mean relative deficit during unsatisfactory periods:
```
V = mean( (demand - Q_out(t)) / demand ) for all t where Q_out(t) < demand
```
If there are no unsatisfactory periods, vulnerability = 0.0.

## Output Files

All outputs written to `/app/output/`:

1. **`cascade_independent.csv`** — daily results for independent policy
   Columns: `date, reservoir_id, storage_MCM, release_cms, spill_cms,
   outflow_cms, availability_status, total_inflow_cms`

2. **`cascade_coordinated.csv`** — daily results for coordinated policy
   (same columns)

3. **`routed_flows_independent.csv`** — routed channel flows, independent
   Columns: `date, reach_id, inflow_cms, outflow_cms`

4. **`routed_flows_coordinated.csv`** — routed channel flows, coordinated
   (same columns)

5. **`performance.json`** — comparative metrics:
   ```json
   {
     "independent": {
       "reliability": <float>,
       "resilience": <float>,
       "vulnerability": <float>,
       "system_mass_balance_relative_error": <float>
     },
     "coordinated": { ... }
   }
   ```
