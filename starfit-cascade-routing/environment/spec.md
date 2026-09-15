# STARFIT Cascade Reservoir Simulation — Mathematical Specification

## Overview

Implement a cascade simulation of two reservoirs using the STARFIT (Storage Targets And Release Function Inference Tool) algorithm based on Turner et al. (2021). The upstream reservoir ("Highland") discharges into the downstream reservoir ("Lowland"). Each reservoir independently computes daily release decisions based on STARFIT operating rules, but the downstream reservoir receives the upstream reservoir's total outflow as additional inflow.

## Units

- **Storage**: MCM (million cubic meters)
- **Flow**: m^3/s (cubic meters per second)
- **NOR bounds**: dimensionless fractions of capacity [0, 1]
- **Time step**: 1 day = 86400 seconds

To convert flow to storage change per timestep:

```
delta_storage [MCM] = flow [m^3/s] * 86400 / 1e6
```

## Algorithm

### ISO Week Number

The STARFIT algorithm uses the ISO 8601 week number (1–53) of the current date for seasonal computations. The simulation starts on 2020-01-01. Use the standard ISO calendar week (Python: `date.isocalendar()[1]`).

### Normal Operating Range (NOR)

Each reservoir has upper and lower operating range bounds that vary seasonally as clipped sinusoidal functions of the ISO week number `w`:

```
NOR_hi(w) = clip(alpha_hi * cos(2 * pi * w / 52 - mu_hi) + beta_hi,  min_hi,  max_hi)
NOR_lo(w) = clip(alpha_lo * cos(2 * pi * w / 52 - mu_lo) + beta_lo,  min_lo,  max_lo)
```

where `clip(x, lo, hi) = max(lo, min(hi, x))`.

NOR bounds are dimensionless fractions of capacity — i.e., `NOR_hi = 0.7` means the upper target is 70% of total capacity.

### Release Function

Given current storage `S` (MCM), reservoir capacity `C` (MCM), and mean inflow `Q_mean` (m^3/s):

1. Compute normalized storage: `s = S / C`

2. Compute release based on which regime `s` falls into:

   **Above NOR** (`s > NOR_hi`):
   ```
   R = R_max * (alpha_1 * (s - NOR_hi)^p_1 + beta_1) * Q_mean     [m^3/s]
   ```

   **Below NOR** (`s < NOR_lo`):
   ```
   R = R_min * (alpha_2 * (NOR_lo - s)^p_2 + beta_2) * Q_mean     [m^3/s]
   ```

   **Within NOR** (`NOR_lo <= s <= NOR_hi`):
   ```
   R = c * Q_mean     [m^3/s]
   ```

3. Enforce non-negativity: `R = max(0, R)`

Note: `R_max`, `R_min`, `alpha_1`, `alpha_2`, `beta_1`, `beta_2`, `p_1`, `p_2`, and `c` are per-reservoir release parameters specified in the parameter file.

### Storage Update (per timestep)

For each reservoir, in upstream-to-downstream order:

1. **Compute total inflow** `I_total` (m^3/s):
   - Upstream reservoir: `I_total = inflow from data file`
   - Downstream reservoir: `I_total = local_inflow from data file + upstream_reservoir_outflow`

2. **Compute release** `R` (m^3/s) using the release function with current storage and NOR bounds.

3. **Compute preliminary updated storage**:
   ```
   S_new = S_old + (I_total - R) * 86400 / 1e6     [MCM]
   ```

4. **Handle spill and negative storage**:
   ```
   if S_new > C:
       spill = (S_new - C) * 1e6 / 86400     [m^3/s]
       S_new = C
   elif S_new < 0:
       R = R + S_new * 1e6 / 86400     (reduce release)
       R = max(0, R)
       S_new = 0
       spill = 0
   else:
       spill = 0
   ```

5. **Total outflow**:
   ```
   outflow = R + spill     [m^3/s]
   ```

### Mass Balance

At every timestep, the following conservation law must hold for each reservoir:

```
S(t) - S(t-1) = (I_total(t) - outflow(t)) * 86400 / 1e6
```

within numerical precision (tolerance: 1e-6 MCM).

## Input Files

- `/app/data/reservoirs.json` — Reservoir parameters (capacity, NOR, release coefficients, initial storage)
- `/app/data/inflows.csv` — Daily inflow timeseries with columns: `day`, `res1_inflow_cms`, `res2_local_inflow_cms`

## Output Requirements

Write results to `/app/results/simulation.csv` with the following columns in this order:

| Column | Description | Units |
|--------|-------------|-------|
| `day` | 0-indexed day number | integer |
| `date` | Date in YYYY-MM-DD format | string |
| `res1_inflow` | Upstream reservoir total inflow | m^3/s |
| `res1_storage` | Upstream reservoir storage (end of timestep) | MCM |
| `res1_release` | Upstream reservoir release (possibly adjusted) | m^3/s |
| `res1_spill` | Upstream reservoir spill | m^3/s |
| `res1_outflow` | Upstream reservoir total outflow (release + spill) | m^3/s |
| `res1_nor_hi` | Upstream NOR upper bound | fraction |
| `res1_nor_lo` | Upstream NOR lower bound | fraction |
| `res2_inflow` | Downstream reservoir total inflow | m^3/s |
| `res2_storage` | Downstream reservoir storage (end of timestep) | MCM |
| `res2_release` | Downstream reservoir release (possibly adjusted) | m^3/s |
| `res2_spill` | Downstream reservoir spill | m^3/s |
| `res2_outflow` | Downstream reservoir total outflow | m^3/s |
| `res2_nor_hi` | Downstream NOR upper bound | fraction |
| `res2_nor_lo` | Downstream NOR lower bound | fraction |

The file must have exactly 731 lines: 1 header line + 730 data rows.
