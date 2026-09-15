# STARFIT Reservoir Simulation Specification

## Overview

STARFIT (Storage Targets And Release Function Inference Tool) models the
release policy of a regulated reservoir. Given daily inflows, reservoir
parameters, and capacity, the algorithm computes daily releases, spill,
storage, and outflows while maintaining strict mass conservation.

Reference: Turner, S.W.D., Steyaert, J.C., Condon, L., Voisin, N. (2021).
Water storage and release policies for all large reservoirs of conterminous
United States. Journal of Hydrology, 603(A), 126843.

## Units

| Quantity     | Symbol  | Unit                  |
|-------------|---------|------------------------|
| Storage      | S       | MCM (million m³)      |
| Capacity     | C       | MCM                    |
| Inflow       | Q_in    | m³/s (cumecs)         |
| Release      | r       | m³/s                   |
| Spill        | s       | m³/s                   |
| Mean flow    | Q_bar   | m³/s                   |
| NOR bounds   | —       | % of capacity          |
| Week number  | w       | ISO week (1–52)        |

Conversion constant: 1 day = 86400 seconds.

## Week Number

Use the ISO 8601 week number of each date, capped at 52:

    w(t) = min(date(t).isocalendar().week, 52)

## 1. Normal Operating Range (NOR)

The upper and lower operating targets vary sinusoidally with the week of year.
Let omega = 1/52.

    NOR_hi(w) = clamp(mu_hi + alpha_hi * sin(2*pi*omega*w) + beta_hi * cos(2*pi*omega*w),
                       NOR_hi_min, NOR_hi_max)

    NOR_lo(w) = clamp(mu_lo + alpha_lo * sin(2*pi*omega*w) + beta_lo * cos(2*pi*omega*w),
                       NOR_lo_min, NOR_lo_max)

where clamp(x, lo, hi) = min(hi, max(lo, x)).

NOR values are percentages of reservoir capacity (e.g., 70 means 70% of C).

## 2. Availability Status

Computed from start-of-day storage (before any updates):

    A(t) = (100 * S(t) / C  -  NOR_lo(w(t)))  /  (NOR_hi(w(t)) - NOR_lo(w(t)))

A(t) indicates the reservoir's fill level relative to the NOR band:
- A in [0, 1]: storage is within the normal operating range
- A > 1: storage is above the upper NOR bound
- A < 0: storage is below the lower NOR bound

## 3. Release Calculation

### 3.1 Standardized seasonal release

    R_std(w) = alpha_R1 * sin(2*pi*omega*w) + alpha_R2 * sin(4*pi*omega*w)
             + beta_R1 * cos(2*pi*omega*w) + beta_R2 * cos(4*pi*omega*w)

### 3.2 Volume computations

    V_f = 7 * Q_in(t) * 86400        forecasted weekly inflow volume (m³/week)
    V_m = 7 * Q_bar   * 86400        mean weekly inflow volume (m³/week)
    I_std = V_f / V_m - 1             standardized inflow (dimensionless)

### 3.3 Base release (m³/day)

    R_base = V_m * (1 + R_std(w) + c + p1*A(t) + p2*I_std) / 7

### 3.4 Override conditions

When the reservoir is outside the NOR, release is overridden:

    R_above = (S(t)*1e6 - C*1e6*NOR_hi(w)/100 + V_f) / 7      if A(t) > 1
    R_below = (S(t)*1e6 - C*1e6*NOR_lo(w)/100 + V_f) / 7      if A(t) < 0

Apply overrides in order:
1. If A(t) > 1: R = R_above
2. If A(t) < 0: R = R_below

### 3.5 Release bounds (m³/day)

    R_min = V_m * (1 + Release_min) / 7
    R_max = V_m * (1 + Release_max) / 7

    R = clamp(R, R_min, R_max)

### 3.6 Convert to m³/s

    r = R / 86400

## 4. Storage Update

### 4.1 Storage change (MCM)

    dS = (Q_in(t) - r) * 86400 / 1e6

### 4.2 Negative storage protection

If S(t) + dS < 0:

    r' = r + (S(t) + dS) * 1e6 / 86400
    r  = max(r', 0)
    dS = (Q_in(t) - r) * 86400 / 1e6

### 4.3 Update storage

    S(t+1) = max(S(t) + dS, 0)

## 5. Spill

If S(t+1) > C:

    spill = (S(t+1) - C) * 1e6 / 86400      [m³/s]
    S(t+1) = C

Otherwise spill = 0.

## 6. Total Outflow

    outflow = r + spill      [m³/s]

## 7. Mass Conservation

Over any period, the following must hold to within relative error < 1e-8:

    sum(Q_in * 86400/1e6)  =  sum(outflow * 86400/1e6) + S_final - S_initial

## 8. Initialization

If initial_storage_MCM is provided (not null), use it directly.

If initial_storage_MCM is null or NaN, compute it as the midpoint of the NOR
at the start week:

    S_0 = C * (NOR_lo(w_0) + NOR_hi(w_0)) / 200

## 9. Simulation Parameters

All parameters are provided in `/app/data/params.json`. The daily inflow
timeseries is in `/app/data/inflows.csv` (columns: date, inflow_cms).

## 10. Required Outputs

### 10.1 Daily results: `/app/output/results.csv`

Columns: date, storage_MCM, release_cms, spill_cms, outflow_cms, availability_status

- storage_MCM: end-of-day storage after release and spill (MCM)
- release_cms: daily average release (m³/s)
- spill_cms: daily spill (m³/s)
- outflow_cms: release + spill (m³/s)
- availability_status: computed from start-of-day storage (before updates)

### 10.2 NOR envelope: `/app/output/nor_envelope.csv`

Columns: week, nor_upper_pct, nor_lower_pct

One row for each ISO week 1 through 52, giving the upper and lower NOR
values as percentages of capacity.

### 10.3 Sensitivity analysis: `/app/output/sensitivity.json`

Run the full simulation with the reservoir capacity multiplied by each of
[0.5, 0.75, 1.0, 1.25, 1.5, 2.0]. Use the same initial_storage_MCM for
all runs. Report a JSON array where each element contains:

    {
        "capacity_multiplier": <float>,
        "total_spill_volume_MCM": <float>,
        "num_spill_days": <int>,
        "mean_availability_status": <float>,
        "final_storage_MCM": <float>,
        "mass_balance_relative_error": <float>
    }

total_spill_volume_MCM = sum of (spill_cms * 86400 / 1e6) over all days.
num_spill_days = count of days where spill_cms > 1e-12.
mean_availability_status = arithmetic mean over all days.
mass_balance_relative_error = |total_in - total_out - delta_S| / total_in.
