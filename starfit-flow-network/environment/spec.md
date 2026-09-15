# STARFIT Reservoir Network Simulator -- Mathematical Specification

## 1. Overview

This document specifies the STARFIT (Storage Targets And Release Function Inference Tool) reservoir management model and the DAG-based flow routing algorithm for a multi-node river network. The STARFIT model uses seasonal sinusoidal operating rules to determine reservoir release decisions based on current storage conditions relative to a Normal Operating Range (NOR).

Reference: Turner, S.W.D., Steyaert, J.C., Condon, L., Voisin, N. (2021). Water storage and release policies for all large reservoirs of conterminous United States. Journal of Hydrology, 603(A), 126843.

## 2. Network Topology

The network is defined in `/app/config.json`. Each node has:
- `id`: integer node identifier (0 through 4)
- `type`: `"reservoir"` (STARFIT model) or `"passthrough"` (channel segment)
- `to`: downstream node id, or `-1` for the network outlet
- `reservoir_key`: (reservoirs only) key into the `"reservoirs"` config section

Nodes must be processed in **topological order** within each substep, ensuring all upstream nodes compute their outflow before any downstream node that depends on them.

## 3. Constants and Unit Conversions

- omega = 1/52 (weekly angular frequency)
- Hourly substep flow-to-storage conversion: `m3ps_to_MCM = 3600 / 1,000,000 = 0.0036`
- Storage-to-flow conversion: `MCM_to_m3ps = 1,000,000 / 3600`
- MCM = million cubic meters
- cms = cubic meters per second

## 4. Epiweek Computation

For simulation day `d` (1-indexed, 1 to 365):

    epiweek(d) = min(1 + floor((d - 1) / 7), 52)

## 5. Normal Operating Range (NOR) Bounds

The NOR defines upper and lower bounds on reservoir storage as a percentage of capacity (values in the 0--100 range). These bounds vary seasonally with epiweek `w`.

**Upper bound (max_NOR):**

    max_NOR(w) = min(NORhi_max, max(NORhi_min, NORhi_mu + NORhi_alpha * sin(2*pi*omega*w) + NORhi_beta * cos(2*pi*omega*w)))

**Lower bound (min_NOR):**

    min_NOR(w) = min(NORlo_max, max(NORlo_min, NORlo_mu + NORlo_alpha * sin(2*pi*omega*w) + NORlo_beta * cos(2*pi*omega*w)))

## 6. Initial Storage

For each reservoir, initial storage is the midpoint of the NOR range at epiweek 1, expressed as a fraction of capacity:

    initial_storage_MCM = GRanD_CAP_MCM * (max_NOR(1) + min_NOR(1)) / 2 / 100

## 7. STARFIT Release Function

Given the current epiweek `w`, reservoir capacity `GRanD_CAP_MCM` (MCM), current storage (MCM), current inflow (m^3/s), and observed mean flow `Obs_MEANFLOW_CUMECS` (m^3/s), compute the release in m^3/day.

### 7.1 Intermediate Quantities

    forecasted_weekly_volume = 7.0 * inflow_cms * 24.0 * 60.0 * 60.0     (m^3/week)
    mean_weekly_volume = 7.0 * Obs_MEANFLOW_CUMECS * 24.0 * 60.0 * 60.0  (m^3/week)
    standardized_inflow = forecasted_weekly_volume / mean_weekly_volume - 1.0

    standardized_weekly_release = Release_alpha1 * sin(2*pi*omega*w)
                                + Release_alpha2 * sin(4*pi*omega*w)
                                + Release_beta1 * cos(2*pi*omega*w)
                                + Release_beta2 * cos(4*pi*omega*w)

### 7.2 Release Bounds (m^3/day)

    release_min_vol = mean_weekly_volume * (1 + Release_min) / 7.0
    release_max_vol = mean_weekly_volume * (1 + Release_max) / 7.0

### 7.3 Availability Status

Compute the storage level relative to the NOR range:

    storage_m3 = storage_MCM * 1,000,000
    capacity_m3 = GRanD_CAP_MCM * 1,000,000
    max_normal = max_NOR(w)
    min_normal = min_NOR(w)
    availability_status = (100.0 * storage_m3 / capacity_m3 - min_normal) / (max_normal - min_normal)

### 7.4 Base Release (m^3/day)

    release = mean_weekly_volume * (1 + (standardized_weekly_release + Release_c + Release_p1 * availability_status + Release_p2 * standardized_inflow)) / 7.0

### 7.5 Out-of-Range Adjustments

    release_above_normal = (storage_m3 - capacity_m3 * max_normal / 100.0 + forecasted_weekly_volume) / 7.0
    release_below_normal = (storage_m3 - capacity_m3 * min_normal / 100.0 + forecasted_weekly_volume) / 7.0

Apply in this order:
1. If `availability_status > 1.0`: set `release = release_above_normal`
2. If `availability_status < 0.0`: set `release = release_below_normal`

### 7.6 Clamping

    release = clamp(release, release_min_vol, release_max_vol)

i.e., `release = max(release_min_vol, min(release_max_vol, release))`

The function returns `release` (m^3/day) and `availability_status` (dimensionless).

## 8. Hourly Substep Simulation Algorithm

Each daily timestep consists of 24 hourly substeps. Within each substep, nodes are processed in topological order of the DAG.

### 8.1 Reservoir Node Substep

For each substep:

1. **Total inflow**: `inflow_sub = upstream_inflow + lateral_inflow` (m^3/s)
2. **Compute STARFIT release**: `release_m3pd, availability_status = STARFIT_release(epiweek, ...)` returns m^3/day
3. **Convert to flow rate**: `release_sub = release_m3pd / 86400.0` (m^3/s)
4. **Storage change**: `storage_change = (inflow_sub - release_sub) * m3ps_to_MCM` (MCM)
5. **Prevent negative storage**: if `(storage + storage_change) < 0`:
   - `potential_release = release_sub + (storage + storage_change) * MCM_to_m3ps`
   - `release_sub = max(potential_release, 0.0)`
   - Recompute: `storage_change = (inflow_sub - release_sub) * m3ps_to_MCM`
6. **Update storage**: `storage = max(storage + storage_change, 0.0)` (MCM)
7. **Spill check**: if `storage > GRanD_CAP_MCM`:
   - `spill_sub = (storage - GRanD_CAP_MCM) * MCM_to_m3ps` (m^3/s)
   - `storage = GRanD_CAP_MCM`
   - Otherwise: `spill_sub = 0.0`
8. **Outflow**: `outflow_sub = release_sub + spill_sub` (m^3/s)

The reservoir's storage state persists across substeps and across days.

### 8.2 Pass-through Node Substep

- `outflow_sub = upstream_inflow + lateral_inflow` (m^3/s)
- No storage, release, or spill tracking

### 8.3 Flow Propagation

After computing a node's outflow on a substep, propagate downstream:
- If `to_graph_index >= 0`: `upstream_inflow[to_graph_index] += outflow_sub`

Upstream inflows are reset to zero at the start of each substep (not each day).

### 8.4 Daily Aggregation

After all 24 substeps, compute daily values:
- `outflow_cms` = mean of 24 substep outflows (m^3/s)
- `release_cms` = mean of 24 substep releases (m^3/s)
- `spill_cms` = mean of 24 substep spills (m^3/s)
- `storage_MCM` = storage after the 24th substep (MCM), **not** the average

For pass-through nodes: `outflow_cms` = mean of substep outflows; `storage_MCM = 0`; `release_cms = outflow_cms`; `spill_cms = 0`.

## 9. Forcing Data

Lateral inflows are provided in `/app/forcing/inflows.csv` with columns `day, node_0, node_1, ..., node_4`. Values are in m^3/s. Each node receives the same lateral inflow on every substep within a given day.

## 10. Output Format

Write results to `/app/output/results.csv` with the following CSV columns:

    day,node_id,outflow_cms,storage_MCM,release_cms,spill_cms

- `day`: integer, 1 to 365
- `node_id`: integer, 0 to 4
- `outflow_cms`: daily average outflow (m^3/s)
- `storage_MCM`: end-of-day storage (MCM); 0 for pass-through nodes
- `release_cms`: daily average release (m^3/s)
- `spill_cms`: daily average spill (m^3/s); 0 for pass-through nodes

Rows must be ordered by day, then by node_id within each day (i.e., 5 rows per day, 1825 rows total).

## 11. Mass Balance Constraint

Conservation of mass must hold at each daily timestep:

    sum(lateral_inflows) = boundary_outflow + sum(delta_storage * 1e6 / 86400)

where the first sum is over all nodes' lateral inflows, `boundary_outflow` is the outflow at the network outlet (node with `to = -1`), and the second sum is over all reservoir nodes' daily storage changes in MCM.
