"""
Complete Vortex Lattice Method solver with stability derivative computation.
Reads /app/config.json, writes /app/results.json.
"""

import json
import math
import sys
import numpy as np


# ----------------------------------------------------------------
# Biot-Savart primitives
# ----------------------------------------------------------------

def _biot_savart_finite(P, A, B):
    """
    Induced velocity at point P from a finite vortex segment A -> B.
    Returns velocity per unit circulation (no 1/(4*pi) factor).
    """
    r1 = P - A
    r2 = P - B
    r0 = B - A

    cross = np.cross(r1, r2)
    cross_sq = np.dot(cross, cross)

    if cross_sq < 1e-20:
        return np.zeros(3)

    r1_mag = np.linalg.norm(r1)
    r2_mag = np.linalg.norm(r2)

    if r1_mag < 1e-12 or r2_mag < 1e-12:
        return np.zeros(3)

    K = np.dot(r0, r1 / r1_mag - r2 / r2_mag)
    return cross / cross_sq * K


def _biot_savart_semi_inf(P, Q, d):
    """
    Induced velocity at point P from a semi-infinite vortex starting at Q
    and extending to infinity in direction d (unit vector).
    Returns velocity per unit circulation (no 1/(4*pi) factor).
    """
    r = P - Q
    cross = np.cross(d, r)
    cross_sq = np.dot(cross, cross)

    if cross_sq < 1e-20:
        return np.zeros(3)

    r_mag = np.linalg.norm(r)
    if r_mag < 1e-12:
        return np.zeros(3)

    K = 1.0 + np.dot(d, r) / r_mag
    return cross / cross_sq * K


def horseshoe_velocity(P, A, B, d_inf):
    """
    Induced velocity at point P from a horseshoe vortex with:
    - Bound vortex from A to B
    - Left trailing: from downstream infinity to A
    - Right trailing: from B to downstream infinity
    Direction d_inf is the unit freestream direction.

    Returns velocity per unit circulation, WITHOUT 1/(4*pi) factor.
    """
    v_bound = _biot_savart_finite(P, A, B)
    # Left trailing: from infinity to A => negative of semi-inf from A to infinity
    v_left = -_biot_savart_semi_inf(P, A, d_inf)
    # Right trailing: from B to infinity
    v_right = _biot_savart_semi_inf(P, B, d_inf)
    return v_bound + v_left + v_right


# ----------------------------------------------------------------
# Panel geometry helpers
# ----------------------------------------------------------------

def compute_panel_geometry(mesh):
    """
    Given mesh of shape (nx, ny, 3), compute panel data.
    Returns list of dicts with keys:
        bound_A, bound_B : bound vortex endpoints (quarter-chord)
        collocation : three-quarter-chord center
        normal : unit outward normal
        dl : bound vortex segment vector (B - A)
    Panels ordered row-major: chordwise index varies fastest.
    """
    nx, ny, _ = mesh.shape
    panels = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            # Panel corners: LE-inner, TE-inner, LE-outer, TE-outer
            p1 = mesh[i, j]        # LE, inner
            p2 = mesh[i + 1, j]    # TE, inner
            p3 = mesh[i, j + 1]    # LE, outer
            p4 = mesh[i + 1, j + 1]  # TE, outer

            # Bound vortex at quarter-chord
            bound_A = 0.75 * p1 + 0.25 * p2  # inner
            bound_B = 0.75 * p3 + 0.25 * p4  # outer

            # Collocation at three-quarter-chord center
            coll = 0.25 * 0.5 * (p1 + p3) + 0.75 * 0.5 * (p2 + p4)

            # Normal via diagonals
            d1 = p4 - p1
            d2 = p3 - p2
            n = np.cross(d1, d2)
            n_mag = np.linalg.norm(n)
            if n_mag < 1e-30:
                n = np.array([0.0, 0.0, 1.0])
            else:
                n = n / n_mag

            panels.append({
                "bound_A": bound_A,
                "bound_B": bound_B,
                "collocation": coll,
                "normal": n,
                "dl": bound_B - bound_A,
                "midpoint": 0.5 * (bound_A + bound_B),
            })
    return panels


# ----------------------------------------------------------------
# AIC matrix assembly
# ----------------------------------------------------------------

def build_aic(panels, d_inf, symmetry):
    """
    Build the Aerodynamic Influence Coefficient matrix.
    AIC[i,j] = induced normal velocity at collocation i from horseshoe j.
    Includes mirror-image contributions for symmetric half-wing.
    """
    n_panels = len(panels)
    AIC = np.zeros((n_panels, n_panels))

    for i in range(n_panels):
        coll = panels[i]["collocation"]
        normal = panels[i]["normal"]

        for j in range(n_panels):
            A = panels[j]["bound_A"]
            B = panels[j]["bound_B"]

            # Real horseshoe influence
            v = horseshoe_velocity(coll, A, B, d_inf) / (4.0 * np.pi)
            AIC[i, j] = np.dot(v, normal)

            # Mirror-image horseshoe for symmetric half-wing
            if symmetry:
                A_m = A.copy()
                A_m[1] = -A_m[1]
                B_m = B.copy()
                B_m[1] = -B_m[1]
                # Mirror bound vortex goes from B_m to A_m (reversed)
                v_m = horseshoe_velocity(coll, B_m, A_m, d_inf) / (4.0 * np.pi)
                AIC[i, j] += np.dot(v_m, normal)

    return AIC


# ----------------------------------------------------------------
# Solve VLM at a given alpha
# ----------------------------------------------------------------

def solve_vlm_alpha(panels, alpha_rad, v_inf, d_inf_base, symmetry):
    """
    Solve for circulations at a given angle of attack.
    Returns gamma array and the AIC matrix.
    """
    # Freestream direction (rotated by alpha in x-z plane)
    cosa = np.cos(alpha_rad)
    sina = np.sin(alpha_rad)
    d_inf = np.array([cosa, 0.0, sina])
    d_inf_mag = np.linalg.norm(d_inf)
    d_inf_unit = d_inf / d_inf_mag

    # Freestream velocity vector
    V_vec = v_inf * d_inf

    # Build AIC
    AIC = build_aic(panels, d_inf_unit, symmetry)

    # RHS: -V_inf . n at each collocation
    n_panels = len(panels)
    rhs = np.zeros(n_panels)
    for i in range(n_panels):
        rhs[i] = -np.dot(V_vec, panels[i]["normal"])

    # Solve
    gamma = np.linalg.solve(AIC, rhs)
    return gamma, AIC, d_inf_unit


# ----------------------------------------------------------------
# Force and moment computation
# ----------------------------------------------------------------

def compute_forces_moments(panels, gamma, v_inf, alpha_rad, rho, d_inf_unit,
                           symmetry, moment_ref_pt):
    """
    Compute section forces at each bound vortex segment using K-J theorem.
    Returns total force vector and moment vector (about moment_ref_pt).
    """
    n_panels = len(panels)
    cosa = np.cos(alpha_rad)
    sina = np.sin(alpha_rad)
    V_inf_vec = v_inf * np.array([cosa, 0.0, sina])

    total_force = np.zeros(3)
    total_moment = np.zeros(3)

    for k in range(n_panels):
        midpt = panels[k]["midpoint"]

        # Compute induced velocity at midpoint from everything EXCEPT
        # panel k's own bound vortex.
        V_induced = np.zeros(3)

        for j in range(n_panels):
            A_j = panels[j]["bound_A"]
            B_j = panels[j]["bound_B"]

            if j == k:
                # Only trailing legs, no bound vortex
                v_left = -_biot_savart_semi_inf(midpt, A_j, d_inf_unit)
                v_right = _biot_savart_semi_inf(midpt, B_j, d_inf_unit)
                V_induced += gamma[j] / (4.0 * np.pi) * (v_left + v_right)
            else:
                v = horseshoe_velocity(midpt, A_j, B_j, d_inf_unit)
                V_induced += gamma[j] / (4.0 * np.pi) * v

            # Mirror contributions (full horseshoe, including bound)
            if symmetry:
                A_m = A_j.copy()
                A_m[1] = -A_m[1]
                B_m = B_j.copy()
                B_m[1] = -B_m[1]
                v_m = horseshoe_velocity(midpt, B_m, A_m, d_inf_unit)
                V_induced += gamma[j] / (4.0 * np.pi) * v_m

        V_total = V_inf_vec + V_induced
        dl = panels[k]["dl"]

        # Kutta-Joukowski: dF = rho * Gamma * (V_total x dl)
        dF = rho * gamma[k] * np.cross(V_total, dl)

        total_force += dF
        r = midpt - moment_ref_pt
        total_moment += np.cross(r, dF)

    # For symmetric wing, double the force and moment (mirror side contributes equally)
    if symmetry:
        total_force *= 2.0
        total_moment *= 2.0

    return total_force, total_moment


def compute_coefficients(total_force, total_moment, v_inf, rho, S_ref, c_ref,
                         alpha_rad, AR):
    """
    Decompose total force into CL, CDi, CM.
    """
    q = 0.5 * rho * v_inf ** 2
    cosa = np.cos(alpha_rad)
    sina = np.sin(alpha_rad)

    # Lift: perpendicular to freestream in x-z plane
    L = -total_force[0] * sina + total_force[2] * cosa
    # Drag: along freestream
    D = total_force[0] * cosa + total_force[2] * sina

    CL = L / (q * S_ref)
    CDi = D / (q * S_ref)

    # Pitching moment: y-component of moment vector
    CM = total_moment[1] / (q * S_ref * c_ref)

    # Oswald efficiency
    if abs(CDi) > 1e-30:
        e = CL ** 2 / (np.pi * AR * CDi)
    else:
        e = 0.0

    return CL, CDi, CM, e


# ----------------------------------------------------------------
# Full analysis for a single case
# ----------------------------------------------------------------

def analyze_case(case_cfg):
    """Run full VLM analysis for one case configuration."""
    mesh = np.array(case_cfg["mesh"], dtype=float)
    symmetry = case_cfg["symmetry"]
    alpha_deg = case_cfg["alpha_deg"]
    v_inf = case_cfg["v_inf"]
    rho = case_cfg["rho"]
    S_ref = case_cfg["S_ref"]
    c_ref = case_cfg["c_ref"]
    AR = case_cfg["AR"]
    moment_ref_pt = np.array(case_cfg["moment_ref_pt"], dtype=float)

    alpha_rad = math.radians(alpha_deg)

    # Compute panel geometry (only depends on mesh, not alpha)
    panels = compute_panel_geometry(mesh)

    # Base freestream direction (alpha=0)
    d_inf_base = np.array([1.0, 0.0, 0.0])

    # Solve at nominal alpha
    gamma, AIC, d_inf_unit = solve_vlm_alpha(
        panels, alpha_rad, v_inf, d_inf_base, symmetry
    )
    F, M = compute_forces_moments(
        panels, gamma, v_inf, alpha_rad, rho, d_inf_unit,
        symmetry, moment_ref_pt
    )
    CL, CDi, CM, e = compute_coefficients(
        F, M, v_inf, rho, S_ref, c_ref, alpha_rad, AR
    )

    # --- Stability derivatives via central finite difference ---
    delta_deg = 0.001
    delta_rad = math.radians(delta_deg)

    # Alpha + delta
    alpha_p = alpha_rad + delta_rad
    g_p, _, d_p = solve_vlm_alpha(panels, alpha_p, v_inf, d_inf_base, symmetry)
    F_p, M_p = compute_forces_moments(
        panels, g_p, v_inf, alpha_p, rho, d_p, symmetry, moment_ref_pt
    )
    CL_p, CDi_p, CM_p, _ = compute_coefficients(
        F_p, M_p, v_inf, rho, S_ref, c_ref, alpha_p, AR
    )

    # Alpha - delta
    alpha_m = alpha_rad - delta_rad
    g_m, _, d_m = solve_vlm_alpha(panels, alpha_m, v_inf, d_inf_base, symmetry)
    F_m, M_m = compute_forces_moments(
        panels, g_m, v_inf, alpha_m, rho, d_m, symmetry, moment_ref_pt
    )
    CL_m, CDi_m, CM_m, _ = compute_coefficients(
        F_m, M_m, v_inf, rho, S_ref, c_ref, alpha_m, AR
    )

    CL_alpha = (CL_p - CL_m) / (2.0 * delta_rad)
    CM_alpha = (CM_p - CM_m) / (2.0 * delta_rad)

    if abs(CL_alpha) > 1e-30:
        static_margin = -CM_alpha / CL_alpha
    else:
        static_margin = 0.0

    return {
        "name": case_cfg.get("name", "unnamed"),
        "CL": float(CL),
        "CDi": float(CDi),
        "CM": float(CM),
        "CL_alpha": float(CL_alpha),
        "CM_alpha": float(CM_alpha),
        "static_margin": float(static_margin),
        "oswald_efficiency": float(e),
        "circulations": [float(g) for g in gamma],
    }


# ----------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------

def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "/app/config.json"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "/app/results.json"

    with open(config_path) as f:
        config = json.load(f)

    if "cases" not in config:
        raise ValueError(
            f"Config at {config_path} missing 'cases' key. "
            f"Keys found: {list(config.keys())}"
        )

    results = {"cases": []}
    for case_cfg in config["cases"]:
        result = analyze_case(case_cfg)
        results["cases"].append(result)

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
