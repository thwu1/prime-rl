"""Main VLM solver loop and stability derivative computation."""
import math
import numpy as np
from .panel import compute_panel_geometry
from .aic import build_aic
from .forces import compute_forces_moments, compute_coefficients


def _solve_at_alpha(panels, alpha_rad, v_inf, symmetry):
    """Solve for panel circulations at a given angle of attack."""
    cosa = np.cos(alpha_rad)
    sina = np.sin(alpha_rad)
    d_inf = np.array([cosa, 0.0, sina])
    d_inf_unit = d_inf / np.linalg.norm(d_inf)

    V_vec = v_inf * d_inf

    AIC = build_aic(panels, d_inf_unit, symmetry)

    n_panels = len(panels)
    rhs = np.zeros(n_panels)
    for i in range(n_panels):
        rhs[i] = -np.dot(V_vec, panels[i]["normal"])

    gamma = np.linalg.solve(AIC, rhs)
    return gamma, d_inf_unit


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

    # Compute panel geometry (depends only on mesh, not alpha)
    panels = compute_panel_geometry(mesh)

    # Solve at nominal alpha
    gamma, d_inf_unit = _solve_at_alpha(panels, alpha_rad, v_inf, symmetry)
    F, M = compute_forces_moments(
        panels, gamma, v_inf, alpha_rad, rho, d_inf_unit, symmetry, moment_ref_pt
    )
    CL, CDi, CM, e = compute_coefficients(
        F, M, v_inf, rho, S_ref, c_ref, alpha_rad, AR
    )

    # Stability derivatives via central finite difference
    delta_deg = 0.001
    delta_rad = math.radians(delta_deg)

    # Alpha + delta
    g_p, d_p = _solve_at_alpha(panels, alpha_rad + delta_rad, v_inf, symmetry)
    F_p, M_p = compute_forces_moments(
        panels, g_p, v_inf, alpha_rad + delta_rad, rho, d_p, symmetry, moment_ref_pt
    )
    CL_p, _, CM_p, _ = compute_coefficients(
        F_p, M_p, v_inf, rho, S_ref, c_ref, alpha_rad + delta_rad, AR
    )

    # Alpha - delta
    g_m, d_m = _solve_at_alpha(panels, alpha_rad - delta_rad, v_inf, symmetry)
    F_m, M_m = compute_forces_moments(
        panels, g_m, v_inf, alpha_rad - delta_rad, rho, d_m, symmetry, moment_ref_pt
    )
    CL_m, _, CM_m, _ = compute_coefficients(
        F_m, M_m, v_inf, rho, S_ref, c_ref, alpha_rad - delta_rad, AR
    )

    CL_alpha = (CL_p - CL_m) / (2.0 * delta_deg)
    CM_alpha = (CM_p - CM_m) / (2.0 * delta_deg)

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
