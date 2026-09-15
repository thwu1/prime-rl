#!/usr/bin/env python3
"""
Fix bugs in base simulation and implement cascade components.

"""
import subprocess
import sys

# =====================================================================
# Bug Fix 1: nor.py - sin/cos swap in nor_lower
# The lower NOR bound has alpha*cos and beta*sin, but the standard
# Fourier decomposition (matching nor_upper) uses alpha*sin + beta*cos.
# =====================================================================

with open("/app/reservoir/nor.py") as f:
    content = f.read()

content = content.replace(
    'params["NORlo_alpha"] * math.cos(2 * math.pi * OMEGA * week)',
    'params["NORlo_alpha"] * math.sin(2 * math.pi * OMEGA * week)',
)
content = content.replace(
    'params["NORlo_beta"] * math.sin(2 * math.pi * OMEGA * week)',
    'params["NORlo_beta"] * math.cos(2 * math.pi * OMEGA * week)',
)

with open("/app/reservoir/nor.py", "w") as f:
    f.write(content)
print("Fixed nor.py: sin/cos swap in nor_lower")


# =====================================================================
# Bug Fix 2: release.py - standardized inflow should be deviation
# i_std = v_f/v_m - 1.0 (deviation from mean), not v_f/v_m (ratio)
# =====================================================================

with open("/app/reservoir/release.py") as f:
    content = f.read()

content = content.replace(
    "    i_std = v_f / v_m\n",
    "    i_std = v_f / v_m - 1.0\n",
)

with open("/app/reservoir/release.py", "w") as f:
    f.write(content)
print("Fixed release.py: standardized inflow deviation")


# =====================================================================
# Bug Fix 3: simulation.py - negative storage protection must adjust
# release to preserve mass conservation
# =====================================================================

with open("/app/reservoir/simulation.py") as f:
    content = f.read()

old_block = """\
    # Negative storage protection
    if (storage + ds) < 0.0:
        ds = -storage
        storage = 0.0
    else:
        storage = storage + ds"""

new_block = """\
    # Negative storage protection
    if (storage + ds) < 0.0:
        release_cms = q_in + storage * MCM_TO_M3PS_DAY
        release_cms = max(release_cms, 0.0)
        ds = (q_in - release_cms) * M3PS_TO_MCM_DAY

    storage = max(storage + ds, 0.0)"""

content = content.replace(old_block, new_block)

with open("/app/reservoir/simulation.py", "w") as f:
    f.write(content)
print("Fixed simulation.py: mass-conserving negative storage protection")


# =====================================================================
# Implementation 1: routing.py - Muskingum channel routing
# =====================================================================

routing_code = '''"""Muskingum channel routing between reservoirs."""


def compute_muskingum_coefficients(K, x, dt=1.0):
    """Compute Muskingum routing coefficients C0, C1, C2.

    Args:
        K: travel time parameter (days)
        x: weighting factor (dimensionless, 0 to 0.5)
        dt: time step (days)

    Returns:
        (C0, C1, C2) tuple
    """
    D = K * (1.0 - x) + dt / 2.0
    C0 = (dt / 2.0 - K * x) / D
    C1 = (dt / 2.0 + K * x) / D
    C2 = (K * (1.0 - x) - dt / 2.0) / D
    return C0, C1, C2


def route_flow(inflows, C0, C1, C2, initial_outflow=None):
    """Route a flow timeseries through a channel reach.

    Args:
        inflows: list of inflow rates (m3/s), length T
        C0, C1, C2: Muskingum coefficients
        initial_outflow: outflow at t=0 (m3/s); defaults to inflows[0]

    Returns:
        list of routed outflow rates (m3/s), length T
    """
    if not inflows:
        return []

    if initial_outflow is None:
        initial_outflow = inflows[0]

    outflows = [initial_outflow]

    for t in range(1, len(inflows)):
        q_out = C0 * inflows[t] + C1 * inflows[t - 1] + C2 * outflows[t - 1]
        outflows.append(max(q_out, 0.0))

    return outflows
'''

with open("/app/reservoir/routing.py", "w") as f:
    f.write(routing_code)
print("Implemented routing.py")


# =====================================================================
# Implementation 2: metrics.py - performance evaluation
# =====================================================================

metrics_code = '''"""Reservoir system performance evaluation metrics."""


def compute_metrics(downstream_outflows, demand_target):
    """Compute performance metrics for the cascade system.

    Args:
        downstream_outflows: list of daily outflow rates (m3/s)
        demand_target: required flow rate (m3/s)

    Returns:
        dict with keys: reliability, resilience, vulnerability
    """
    T = len(downstream_outflows)
    if T == 0:
        return {"reliability": 0.0, "resilience": 0.0, "vulnerability": 0.0}

    satisfactory = [q >= demand_target for q in downstream_outflows]

    # Reliability: fraction of satisfactory days
    reliability = sum(satisfactory) / T

    # Resilience: P(satisfactory at t+1 | unsatisfactory at t)
    n_unsat = 0
    n_recovery = 0
    for t in range(T - 1):
        if not satisfactory[t]:
            n_unsat += 1
            if satisfactory[t + 1]:
                n_recovery += 1
    resilience = n_recovery / n_unsat if n_unsat > 0 else 1.0

    # Vulnerability: mean relative deficit during unsatisfactory periods
    deficits = []
    for t in range(T):
        if not satisfactory[t]:
            deficit = (demand_target - downstream_outflows[t]) / demand_target
            deficits.append(deficit)
    vulnerability = sum(deficits) / len(deficits) if deficits else 0.0

    return {
        "reliability": reliability,
        "resilience": resilience,
        "vulnerability": vulnerability,
    }
'''

with open("/app/reservoir/metrics.py", "w") as f:
    f.write(metrics_code)
print("Implemented metrics.py")


# =====================================================================
# Implementation 3: cascade.py - multi-reservoir cascade simulation
# =====================================================================

cascade_code = '''"""Multi-reservoir cascade simulation."""

from .simulation import simulate_day, iso_week, M3PS_TO_MCM_DAY, MCM_TO_M3PS_DAY
from .nor import nor_upper, nor_lower
from .routing import compute_muskingum_coefficients


def run_cascade(reservoir_params, reach_params, dates, lateral_inflows,
                mode="independent", demand_target=None):
    """Run the 3-reservoir cascade simulation.

    Args:
        reservoir_params: list of 3 parameter dicts
        reach_params: list of 2 dicts with keys 'K' and 'x'
        dates: list of date objects
        lateral_inflows: list of 3 inflow arrays (m3/s)
        mode: "independent" or "coordinated"
        demand_target: downstream demand (m3/s), used in coordinated mode

    Returns:
        results: list of 3 lists of daily result dicts
        routed: list of 2 lists of daily routed flow dicts
        balance: dict with system-wide mass balance info
    """
    n_days = len(dates)
    n_res = 3
    n_reaches = 2

    storage = [p["initial_storage_MCM"] for p in reservoir_params]
    caps = [p["GRanD_CAP_MCM"] for p in reservoir_params]
    initial_storage = list(storage)

    # Muskingum coefficients per reach
    musk_coeffs = []
    for rp in reach_params:
        C0, C1, C2 = compute_muskingum_coefficients(rp["K"], rp["x"])
        musk_coeffs.append((C0, C1, C2))

    # Routing state: previous upstream outflow and previous routed outflow
    prev_upstream_outflow = [None] * n_reaches
    prev_routed_outflow = [None] * n_reaches

    results = [[] for _ in range(n_res)]
    routed = [[] for _ in range(n_reaches)]

    total_lateral = [0.0] * n_res
    total_outflow_vol = [0.0] * n_res

    for t in range(n_days):
        d = dates[t]
        ew = iso_week(d)

        # Record start-of-day storage for coordination
        start_storage = list(storage)

        for r in range(n_res):
            q_lateral = lateral_inflows[r][t]
            q_routed = 0.0

            if r > 0:
                reach_idx = r - 1
                C0, C1, C2 = musk_coeffs[reach_idx]
                upstream_outflow = results[r - 1][-1]["outflow_cms"]

                if t == 0:
                    q_routed = upstream_outflow
                else:
                    q_routed = (
                        C0 * upstream_outflow
                        + C1 * prev_upstream_outflow[reach_idx]
                        + C2 * prev_routed_outflow[reach_idx]
                    )
                    q_routed = max(q_routed, 0.0)

                prev_upstream_outflow[reach_idx] = upstream_outflow
                prev_routed_outflow[reach_idx] = q_routed

                routed[reach_idx].append({
                    "date": d.isoformat(),
                    "inflow_cms": upstream_outflow,
                    "outflow_cms": q_routed,
                })

            q_in = q_lateral + q_routed
            total_lateral[r] += q_lateral * M3PS_TO_MCM_DAY

            # --- Simulate this reservoir for the day ---

            if mode == "coordinated" and r < n_res - 1:
                # Coordinated: adjust release based on downstream state
                new_s, rel, spl, out, avail = simulate_day(
                    reservoir_params[r], q_in, storage[r], caps[r], ew
                )

                # Downstream availability from start-of-day storage
                ds_idx = r + 1
                ds_p = reservoir_params[ds_idx]
                ds_hi = nor_upper(ds_p, ew)
                ds_lo = nor_lower(ds_p, ew)
                ds_avail = (
                    100.0 * start_storage[ds_idx] / caps[ds_idx] - ds_lo
                ) / (ds_hi - ds_lo)

                factor = 1.0 + 0.5 * (0.5 - ds_avail)
                factor = max(0.5, min(1.5, factor))

                rel_adj = rel * factor

                # Recompute mass balance with adjusted release
                ds_adj = (q_in - rel_adj) * M3PS_TO_MCM_DAY
                new_s_adj = storage[r] + ds_adj

                if new_s_adj < 0:
                    max_rel_mcm = storage[r] + q_in * M3PS_TO_MCM_DAY
                    rel_adj = max(max_rel_mcm * MCM_TO_M3PS_DAY, 0.0)
                    ds_adj = (q_in - rel_adj) * M3PS_TO_MCM_DAY
                    new_s_adj = max(storage[r] + ds_adj, 0.0)

                spl_adj = 0.0
                if new_s_adj > caps[r]:
                    spl_adj = (new_s_adj - caps[r]) * MCM_TO_M3PS_DAY
                    new_s_adj = caps[r]

                out_adj = rel_adj + spl_adj
                storage[r] = new_s_adj
                total_outflow_vol[r] += out_adj * M3PS_TO_MCM_DAY

                results[r].append({
                    "date": d.isoformat(),
                    "storage_MCM": new_s_adj,
                    "release_cms": rel_adj,
                    "spill_cms": spl_adj,
                    "outflow_cms": out_adj,
                    "availability_status": avail,
                    "total_inflow_cms": q_in,
                })

            elif mode == "coordinated" and r == n_res - 1:
                # Downstream reservoir: demand awareness
                new_s, rel, spl, out, avail = simulate_day(
                    reservoir_params[r], q_in, storage[r], caps[r], ew
                )

                if demand_target is not None and out < demand_target:
                    hi = nor_upper(reservoir_params[r], ew)
                    lo = nor_lower(reservoir_params[r], ew)
                    min_s = caps[r] * lo / 100.0

                    if storage[r] > min_s:
                        excess_mcm = storage[r] - min_s
                        excess_cms = excess_mcm * MCM_TO_M3PS_DAY
                        needed = demand_target - out
                        extra = min(needed, excess_cms)

                        rel += extra
                        ds_adj = (q_in - rel) * M3PS_TO_MCM_DAY
                        new_s = storage[r] + ds_adj

                        if new_s < 0:
                            max_mcm = storage[r] + q_in * M3PS_TO_MCM_DAY
                            rel = max(max_mcm * MCM_TO_M3PS_DAY, 0.0)
                            ds_adj = (q_in - rel) * M3PS_TO_MCM_DAY
                            new_s = max(storage[r] + ds_adj, 0.0)

                        spl = 0.0
                        if new_s > caps[r]:
                            spl = (new_s - caps[r]) * MCM_TO_M3PS_DAY
                            new_s = caps[r]

                        out = rel + spl

                storage[r] = new_s
                total_outflow_vol[r] += out * M3PS_TO_MCM_DAY

                results[r].append({
                    "date": d.isoformat(),
                    "storage_MCM": new_s,
                    "release_cms": rel,
                    "spill_cms": spl,
                    "outflow_cms": out,
                    "availability_status": avail,
                    "total_inflow_cms": q_in,
                })

            else:
                # Independent mode
                new_s, rel, spl, out, avail = simulate_day(
                    reservoir_params[r], q_in, storage[r], caps[r], ew
                )
                storage[r] = new_s
                total_outflow_vol[r] += out * M3PS_TO_MCM_DAY

                results[r].append({
                    "date": d.isoformat(),
                    "storage_MCM": new_s,
                    "release_cms": rel,
                    "spill_cms": spl,
                    "outflow_cms": out,
                    "availability_status": avail,
                    "total_inflow_cms": q_in,
                })

    # System-wide mass balance
    total_lat_all = sum(total_lateral)
    total_out_sys = total_outflow_vol[2]
    delta_s = sum(storage[r] - initial_storage[r] for r in range(n_res))

    route_imbalance = 0.0
    for reach_idx in range(n_reaches):
        ri = sum(row["inflow_cms"] * M3PS_TO_MCM_DAY
                 for row in routed[reach_idx])
        ro = sum(row["outflow_cms"] * M3PS_TO_MCM_DAY
                 for row in routed[reach_idx])
        route_imbalance += (ri - ro)

    sys_err = abs(total_lat_all - total_out_sys - delta_s - route_imbalance)
    sys_rel = sys_err / total_lat_all if total_lat_all > 0 else 0.0

    balance = {
        "system_mass_balance_relative_error": sys_rel,
        "total_lateral_inflow_MCM": total_lat_all,
        "total_downstream_outflow_MCM": total_out_sys,
        "total_storage_change_MCM": delta_s,
        "routing_volume_imbalance_MCM": route_imbalance,
    }

    return results, routed, balance
'''

with open("/app/reservoir/cascade.py", "w") as f:
    f.write(cascade_code)
print("Implemented cascade.py")


# =====================================================================
# Run the cascade pipeline
# =====================================================================

print("\nRunning cascade simulation pipeline...")
result = subprocess.run(
    ["python3", "/app/run_cascade.py"],
    capture_output=True, text=True,
)
print(result.stdout)
if result.stderr:
    print(result.stderr, file=sys.stderr)
if result.returncode != 0:
    sys.exit(1)
print("All outputs generated successfully.")
