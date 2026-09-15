# STARFIT: Storage Targets And Release Function Inference Tool

Adapted from: Turner, S.W.D., Steyaert, J.C., Condon, L., Voisin, N. (2021).
*Water storage and release policies for all large reservoirs of conterminous
United States.* Journal of Hydrology, 603(A), 126843.

See also the pywatershed implementation (DOI-USGS/pywatershed) and the
original STARFIT repository (IMMM-SFA/starfit).

## 1. Epidemiological Week

The STARFIT model uses a weekly seasonal index called "epiweek":

    epiweek(d) = min(1 + floor((d - 1) / 7), 52)

where `d` is the 1-indexed simulation day. The angular frequency for the
52-week cycle is `omega = 1/52`.

## 2. Normal Operating Range

The NOR defines seasonally-varying upper and lower bounds on reservoir
storage as a **percentage of capacity** (values on the 0–100 scale):

Upper bound:

    max_NOR(w) = clamp(
        NORhi_mu + NORhi_alpha * sin(2*pi*omega*w) + NORhi_beta * cos(2*pi*omega*w),
        NORhi_min,
        NORhi_max
    )

Lower bound:

    min_NOR(w) = clamp(
        NORlo_mu + NORlo_alpha * sin(2*pi*omega*w) + NORlo_beta * cos(2*pi*omega*w),
        NORlo_min,
        NORlo_max
    )

where `clamp(x, lo, hi) = max(lo, min(hi, x))`.

## 3. Initial Storage

Reservoir storage is initialised at the midpoint of the NOR at epiweek 1:

    S_0 = capacity_MCM * (max_NOR(1) + min_NOR(1)) / 200

## 4. Availability Status

Availability status measures the reservoir's current fill level relative
to the NOR:

    AS = (100 * S_MCM / capacity_MCM - min_NOR(w)) / (max_NOR(w) - min_NOR(w))

where `S_MCM` is current storage in MCM. Values above 1.0 indicate storage
exceeding the upper NOR bound; values below 0.0 indicate storage below the
lower bound.

## 5. Release Function

Given current inflow `Q_in` (m³/s) and observed long-term mean flow
`Q_mean` (m³/s):

    V_week_forecast = 7 * Q_in * 86400          (m³/week)
    V_week_mean     = 7 * Q_mean * 86400         (m³/week)
    I_std           = V_week_forecast / V_week_mean - 1

Standardised seasonal release signal (dimensionless):

    R_std = alpha1 * sin(2*pi*omega*w) + alpha2 * sin(4*pi*omega*w)
          + beta1  * cos(2*pi*omega*w) + beta2  * cos(4*pi*omega*w)

Base release (m³/day):

    R = V_week_mean * (1 + R_std + c + p1*AS + p2*I_std) / 7

### 5.1 Out-of-Range Adjustments

When storage departs from the NOR, alternative release targets are used:

    R_above = (S_m3 - capacity_m3 * max_NOR(w)/100 + V_week_forecast) / 7
    R_below = (S_m3 - capacity_m3 * min_NOR(w)/100 + V_week_forecast) / 7

Apply in order:

  1. If AS > 1.0 : R ← R_above
  2. If AS < 0.0 : R ← R_below

### 5.2 Release Bounds

    R_min = V_week_mean * (1 + Release_min) / 7
    R_max = V_week_mean * (1 + Release_max) / 7

    R ← clamp(R, R_min, R_max)

The function returns R in m³/day.

## 6. Storage Mass Balance

At each computational time step of duration `dt` seconds, storage is
updated from the net flux:

    release_rate = R / 86400                             (m³/s)
    dS           = (inflow - release_rate) * dt / 1e6    (MCM)
    S            = S + dS

### 6.1 Negative Storage Prevention

If the update would cause S to become negative, the release must be
curtailed. The adjusted release rate is:

    release_rate_adj = release_rate + (S + dS) * 1e6 / dt
    release_rate_adj = max(release_rate_adj, 0)

Then recompute dS with the adjusted release rate and apply:

    S = max(S + dS_adjusted, 0)

### 6.2 Spill

If storage exceeds capacity after the update:

    spill_rate = (S - capacity_MCM) * 1e6 / dt     (m³/s)
    S          = capacity_MCM

Total outflow at each computational step is `release_rate + spill_rate`.

## 7. Passthrough Nodes

Channel segments with no reservoir simply pass through all received water:
outflow equals the sum of upstream inflow plus lateral inflow. Storage,
release, and spill are zero.

## 8. Units Reference

| Symbol              | Unit               |
|---------------------|--------------------|
| MCM                 | 10⁶ m³             |
| capacity_MCM        | MCM                |
| Q (flow rates)      | m³/s               |
| R (release)         | m³/day             |
| V (volumes)         | m³                 |
| NOR bounds          | % of capacity      |
| dt                  | seconds            |
