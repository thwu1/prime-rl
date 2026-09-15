#!/usr/bin/env python3
"""
Solution: Compressible flow field reconstruction using Gmsh and physics derivation.

"""
import json
import math
import os
import sys

import numpy as np


def main():
    import gmsh

    sys.path.insert(0, "/app")
    from ci2_init import flow_state

    # ══════════════════════════════════════════════════════
    # Step 1: Gmsh mesh generation
    # ══════════════════════════════════════════════════════
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("domain")

    gmsh.model.occ.addRectangle(0, 0, 0, 1, 1)
    gmsh.model.occ.synchronize()

    lc = 0.00237  # target ~178k nodes
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", lc)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", lc * 0.8)
    gmsh.model.mesh.generate(2)

    node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
    num_nodes = len(node_tags)

    elem_types, elem_tags, _ = gmsh.model.mesh.getElements(dim=2)
    total_elements = 0
    all_qualities = []
    for etype, etags in zip(elem_types, elem_tags):
        total_elements += len(etags)
        q = gmsh.model.mesh.getElementQualities(etags.tolist())
        all_qualities.extend(q)
    min_quality = min(all_qualities) if all_qualities else 0.0

    os.makedirs("/app/results", exist_ok=True)
    gmsh.write("/app/results/mesh.msh")
    gmsh.finalize()

    # ══════════════════════════════════════════════════════
    # Step 2: Analytical shock conditions
    # ══════════════════════════════════════════════════════
    gamma = 1.4
    R_gas = 1.0
    Ms = 1.5
    Ms2 = Ms ** 2

    rho_u = 1.0
    u_u = 1.5 * math.sqrt(gamma)
    p_u = 1.0
    T_u = 1.0

    rho_d = rho_u * (gamma + 1) * Ms2 / (2 + (gamma - 1) * Ms2)
    u_d = u_u * (2 + (gamma - 1) * Ms2) / ((gamma + 1) * Ms2)
    p_d = p_u * (1 + 2 * gamma / (gamma + 1) * (Ms2 - 1))
    T_d = p_d / (rho_d * R_gas)
    a_d = math.sqrt(gamma * R_gas * T_d)
    M_d = u_d / a_d

    # ══════════════════════════════════════════════════════
    # Step 3: Conservation — total enthalpy
    # ══════════════════════════════════════════════════════
    cp = gamma * R_gas / (gamma - 1)
    H_u = cp * T_u + 0.5 * u_u ** 2
    H_d = cp * T_d + 0.5 * u_d ** 2
    H_rel_err = abs(H_u - H_d) / H_u

    # ══════════════════════════════════════════════════════
    # Step 4: Entropy (isentropic invariant p/rho^gamma)
    # ══════════════════════════════════════════════════════
    s_u = p_u / rho_u ** gamma
    s_d = p_d / rho_d ** gamma

    # ══════════════════════════════════════════════════════
    # Step 5: Vortex center properties
    # ══════════════════════════════════════════════════════
    xc, yc = 0.25, 0.5
    a_v, b_v = 0.075, 0.175
    Mv = 0.9
    v_m = Mv * math.sqrt(gamma)

    coeff = v_m * a_v / (a_v ** 2 - b_v ** 2)
    rt_a = (
        -2 * b_v ** 2 * math.log(b_v)
        - 0.5 * a_v ** 2
        + 2 * b_v ** 2 * math.log(a_v)
        + 0.5 * b_v ** 4 / a_v ** 2
    )
    t_a = T_u - (gamma - 1) * coeff ** 2 * rt_a / (R_gas * gamma)
    t_center = t_a - (gamma - 1) * v_m ** 2 * 0.5 / (R_gas * gamma)
    p_center = p_u * (t_center / T_u) ** (gamma / (gamma - 1))
    rho_center = p_center / (R_gas * t_center)

    # ══════════════════════════════════════════════════════
    # Step 6: Peak vorticity (analytical for solid-body core)
    # ══════════════════════════════════════════════════════
    peak_vort = 2 * v_m / a_v

    # ══════════════════════════════════════════════════════
    # Step 7: Circulation at r=0.12 (numerical line integral)
    # ══════════════════════════════════════════════════════
    r_circ = 0.12
    n_pts = 2000
    circ = 0.0
    for k in range(n_pts):
        theta = 2 * math.pi * k / n_pts
        dtheta = 2 * math.pi / n_pts
        px = xc + r_circ * math.cos(theta)
        py = yc + r_circ * math.sin(theta)
        st = flow_state(px, py)
        ux, vy = st["velocity"][0], st["velocity"][1]
        dl_x = -r_circ * math.sin(theta) * dtheta
        dl_y = r_circ * math.cos(theta) * dtheta
        circ += ux * dl_x + vy * dl_y

    # ══════════════════════════════════════════════════════
    # Step 8: Field statistics on dense grid (vectorized)
    # ══════════════════════════════════════════════════════
    Nx, Ny = 401, 401
    x = np.linspace(0, 1, Nx)
    y = np.linspace(0, 1, Ny)
    X, Y = np.meshgrid(x, y, indexing="ij")

    upstream = X <= 0.5
    U = np.where(upstream, u_u, u_d)
    V = np.full_like(X, 1e-20)
    P = np.where(upstream, p_u, p_d)
    T_field = np.where(upstream, T_u, T_d)

    dx_v = X - xc
    dy_v = Y - yc
    r = np.sqrt(dx_v ** 2 + dy_v ** 2)
    r_safe = np.maximum(r, 1e-30)
    sin_th = dy_v / r_safe
    cos_th = dx_v / r_safe

    inner = upstream & (r <= a_v) & (r > 1e-15)
    outer = upstream & (r > a_v) & (r <= b_v)
    center_mask = upstream & (r < 1e-15)

    coeff_sq = coeff ** 2

    if np.any(inner):
        r_i = r[inner]
        mag = v_m * r_i / a_v
        U[inner] -= mag * sin_th[inner]
        V[inner] += mag * cos_th[inner]
        rt = 0.5 * (1 - r_i ** 2 / a_v ** 2)
        T_field[inner] = t_a - (gamma - 1) * v_m ** 2 * rt / (R_gas * gamma)
        P[inner] = p_u * (T_field[inner] / T_u) ** (gamma / (gamma - 1))

    if np.any(outer):
        r_o = r[outer]
        mag = v_m * a_v * (r_o - b_v ** 2 / r_o) / (a_v ** 2 - b_v ** 2)
        U[outer] -= mag * sin_th[outer]
        V[outer] += mag * cos_th[outer]
        rt = (
            -2 * b_v ** 2 * np.log(b_v)
            - 0.5 * r_o ** 2
            + 2 * b_v ** 2 * np.log(r_o)
            + 0.5 * b_v ** 4 / r_o ** 2
        )
        T_field[outer] = T_u - (gamma - 1) * coeff_sq * rt / (R_gas * gamma)
        P[outer] = p_u * (T_field[outer] / T_u) ** (gamma / (gamma - 1))

    if np.any(center_mask):
        T_field[center_mask] = t_center
        P[center_mask] = p_center

    rho_field = P / (R_gas * T_field)
    speed = np.sqrt(U ** 2 + V ** 2)
    a_sound = np.sqrt(gamma * P / rho_field)
    mach = speed / a_sound

    dx_g = x[1] - x[0]
    dy_g = y[1] - y[0]
    dvdx = np.gradient(V, dx_g, axis=0)
    dudy = np.gradient(U, dy_g, axis=1)
    omega = dvdx - dudy

    # ══════════════════════════════════════════════════════
    # Assemble results
    # ══════════════════════════════════════════════════════
    results = {
        "mesh_quality": {
            "num_nodes": int(num_nodes),
            "num_elements": int(total_elements),
            "min_quality": float(min_quality),
        },
        "shock_conditions": {
            "rho_d": float(rho_d),
            "u_d": float(u_d),
            "p_d": float(p_d),
            "T_d": float(T_d),
            "M_d": float(M_d),
        },
        "conservation": {
            "H_upstream": float(H_u),
            "H_downstream": float(H_d),
            "relative_error": float(H_rel_err),
        },
        "entropy": {
            "s_upstream": float(s_u),
            "s_downstream": float(s_d),
            "entropy_ratio": float(s_d / s_u),
        },
        "vortex_properties": {
            "center_pressure": float(p_center),
            "center_temperature": float(t_center),
            "center_density": float(rho_center),
            "peak_vorticity": float(peak_vort),
            "circulation_r012": float(circ),
        },
        "field_statistics": {
            "max_mach": float(np.max(mach)),
            "min_pressure": float(np.min(P)),
            "max_vorticity": float(np.max(np.abs(omega))),
        },
    }

    with open("/app/results/analysis.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results written to /app/results/analysis.json")


if __name__ == "__main__":
    main()
