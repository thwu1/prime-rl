#!/usr/bin/env python3
"""
Geotechnical Settlement Analysis Tool

Computes multi-layer primary consolidation settlement under a shallow
foundation and optionally performs 1D finite-difference pore pressure
dissipation.
"""
import sys
import json
import math


# ---------------------------------------------------------------------------
# Phase relations
# ---------------------------------------------------------------------------

def void_ratio_from_unit_weight(gamma, S, Gs, gamma_w):
    """Void ratio from bulk unit weight using three-phase relationship.

    gamma = (Gs + S*e) / (1+e) * gamma_w
    => e = (Gs*gamma_w - gamma) / (gamma - S*gamma_w)
    """
    return (Gs * gamma_w - gamma) / (gamma - S * gamma_w)


# ---------------------------------------------------------------------------
# Boussinesq stress distribution
# ---------------------------------------------------------------------------

def stress_rect_corner(q, L, B, z):
    """Vertical stress below corner of a uniformly loaded rectangle (Budhu)."""
    if z <= 1e-12:
        return q
    R1 = math.sqrt(L ** 2 + z ** 2)
    R2 = math.sqrt(B ** 2 + z ** 2)
    R3 = math.sqrt(L ** 2 + B ** 2 + z ** 2)
    return (q / (2.0 * math.pi)) * (
        math.atan(L * B / (z * R3))
        + L * B * z / R3 * (1.0 / (R1 ** 2) + 1.0 / (R2 ** 2))
    )


def stress_circle_center(q, r0, z):
    """Vertical stress below center of a uniformly loaded circle (Budhu)."""
    if z <= 1e-12:
        return q
    return q * (1.0 - (1.0 / (1.0 + (r0 / z) ** 2)) ** 1.5)


def stress_strip_center(q, B, z):
    """Vertical stress below center of a uniformly loaded strip (Budhu)."""
    if z <= 1e-12:
        return q
    x = B / 2.0
    R1 = math.sqrt(x ** 2 + z ** 2)
    R2 = math.sqrt((x - B) ** 2 + z ** 2)
    theta1 = math.acos(min(1.0, max(-1.0, z / R1)))
    theta2 = math.acos(min(1.0, max(-1.0, z / R2)))
    if x < B:
        theta2 = -theta2
    beta = theta2
    alpha = theta1 - beta
    return (q / math.pi) * (
        alpha + math.sin(alpha) * math.cos(alpha + 2.0 * beta)
    )


def foundation_stress(foundation, z):
    """Vertical stress increase below foundation center at depth z."""
    shape = foundation["shape"]
    q = foundation["applied_stress"]
    if shape == "rectangular":
        half_L = foundation["length"] / 2.0
        half_B = foundation["width"] / 2.0
        return 4.0 * stress_rect_corner(q, half_L, half_B, z)
    elif shape == "circular":
        r0 = foundation["width"] / 2.0
        return stress_circle_center(q, r0, z)
    elif shape == "strip":
        return stress_strip_center(q, foundation["width"], z)
    else:
        raise ValueError(f"Unknown foundation shape: {shape}")


# ---------------------------------------------------------------------------
# Settlement computation
# ---------------------------------------------------------------------------

def compute_settlement(scenario):
    layers = scenario["soil_profile"]["layers"]
    wt = scenario.get("water_table_depth", 0)
    Gs = scenario.get("specific_gravity", 2.65)
    gamma_w = scenario.get("unit_weight_water", 10.0)
    dz_grid = scenario.get("grid_spacing", 0.5)
    fdn = scenario["foundation"]

    profile_depth = max(l["depth_to"] for l in layers)

    # ---- build sorted unique node set ----
    nodes = set()
    z = 0.0
    while z <= profile_depth + 1e-10:
        nodes.add(round(z, 10))
        z += dz_grid
    for l in layers:
        nodes.add(round(l["depth_from"], 10))
        nodes.add(round(l["depth_to"], 10))
    nodes = sorted(nodes)

    # ---- void ratio per layer (evaluated at layer center) ----
    layer_e0 = []
    for l in layers:
        center = (l["depth_from"] + l["depth_to"]) / 2.0
        S = 0.0 if center < wt else 1.0
        e = void_ratio_from_unit_weight(l["total_unit_weight"], S, Gs, gamma_w)
        layer_e0.append(e)

    # ---- helpers ----
    def find_layer_idx(z_val):
        for idx, l in enumerate(layers):
            if l["depth_from"] <= z_val < l["depth_to"]:
                return idx
        return len(layers) - 1

    def total_stress_at(z_val):
        sigma = 0.0
        for l in layers:
            if l["depth_to"] <= z_val:
                sigma += l["total_unit_weight"] * (l["depth_to"] - l["depth_from"])
            elif l["depth_from"] < z_val:
                sigma += l["total_unit_weight"] * (z_val - l["depth_from"])
                break
            else:
                break
        return sigma

    # ---- build elements and compute settlement ----
    elements = []
    for k in range(len(nodes) - 1):
        z_from = nodes[k]
        z_to = nodes[k + 1]
        dz = z_to - z_from
        z_center = (z_from + z_to) / 2.0

        li = find_layer_idx(z_center)
        l = layers[li]
        e0 = layer_e0[li]

        sigma_total = total_stress_at(z_center)
        u = gamma_w * max(0.0, z_center - wt)
        sigma_eff = sigma_total - u

        delta_sigma = foundation_stress(fdn, z_center)

        Cc = l.get("Cc", 0)
        Cr = l.get("Cr", 0)
        OCR = l.get("OCR", 1)

        if Cc == 0 or sigma_eff <= 0 or delta_sigma <= 0:
            delta_z = 0.0
        elif OCR <= 1:
            # Normally consolidated
            delta_e = Cc * math.log10((sigma_eff + delta_sigma) / sigma_eff)
            delta_z = (dz / (1.0 + e0)) * delta_e
        else:
            # Overconsolidated
            pc = sigma_eff * OCR
            if (sigma_eff + delta_sigma) <= pc:
                delta_e = Cr * math.log10(
                    (sigma_eff + delta_sigma) / sigma_eff
                )
            else:
                delta_e = Cr * math.log10(pc / sigma_eff) + Cc * math.log10(
                    (sigma_eff + delta_sigma) / pc
                )
            delta_z = (dz / (1.0 + e0)) * delta_e

        elements.append(
            {"depth_from": z_from, "depth_to": z_to, "delta_z": delta_z}
        )

    total = sum(e["delta_z"] for e in elements)
    return {"total_settlement": total, "layer_settlements": elements}


# ---------------------------------------------------------------------------
# 1D finite-difference consolidation
# ---------------------------------------------------------------------------

def compute_consolidation(params):
    height = params["height"]
    total_time = params["total_time"]
    no_nodes = params["no_nodes"]
    cv_yr = params["cv"]  # m^2/yr
    top_drain = params["top_drainage"]
    bottom_drain = params["bottom_drainage"]
    initial_u = params["initial_excess_pore_pressure"]
    output_times = sorted(params["output_times_seconds"])

    cv_s = cv_yr / (365.0 * 24.0 * 3600.0)

    dz = height / (no_nodes - 1)

    # Stability: alpha = cv*dt/dz^2 = 0.25
    dt_stable = 0.25 * dz ** 2 / cv_s
    n = math.ceil(total_time / dt_stable)

    # Build time array and merge output times
    times = [i * total_time / n for i in range(n + 1)]
    all_times = sorted(set(times + output_times))
    dts = [all_times[i + 1] - all_times[i] for i in range(len(all_times) - 1)]

    # Initial pore pressure
    if isinstance(initial_u, (int, float)):
        u = [float(initial_u)] * no_nodes
    else:
        # Two-element array: linearly interpolate from top to bottom
        u = [
            initial_u[0] + (initial_u[1] - initial_u[0]) * i / (no_nodes - 1)
            for i in range(no_nodes)
        ]

    # Collect output times for fast lookup
    output_set = set()
    for t in output_times:
        # find closest time in all_times
        for at in all_times:
            if abs(at - t) < 1e-10:
                output_set.add(at)
                break

    pore_pressures = []

    for j in range(len(dts)):
        dt_j = dts[j]
        u_prev = u[:]
        u = [0.0] * no_nodes
        alpha = cv_s * dt_j / (dz ** 2)

        for i in range(no_nodes):
            if i == 0:
                if top_drain:
                    u[i] = 0.0
                else:
                    u[i] = u_prev[i] + alpha * (
                        -2.0 * u_prev[i] + 2.0 * u_prev[i + 1]
                    )
            elif i == no_nodes - 1:
                if bottom_drain:
                    u[i] = 0.0
                else:
                    u[i] = u_prev[i] + alpha * (
                        2.0 * u_prev[i - 1] - 2.0 * u_prev[i]
                    )
            else:
                u[i] = u_prev[i] + alpha * (
                    u_prev[i - 1] - 2.0 * u_prev[i] + u_prev[i + 1]
                )

        t_now = all_times[j + 1]
        if any(abs(t_now - ot) < 1e-10 for ot in output_set):
            pore_pressures.append({"time": t_now, "values": u[:]})

    return pore_pressures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open(sys.argv[1]) as f:
        scenario = json.load(f)

    results = {}

    if "foundation" in scenario:
        settlement = compute_settlement(scenario)
        results["total_settlement"] = settlement["total_settlement"]
        results["layer_settlements"] = settlement["layer_settlements"]

    if "consolidation" in scenario:
        results["pore_pressures"] = compute_consolidation(scenario["consolidation"])

    json.dump(results, sys.stdout)
    print()


if __name__ == "__main__":
    main()
