"""Force and moment computation from VLM solution."""
import numpy as np
from .biot_savart import biot_savart_semi_inf, horseshoe_velocity


def compute_forces_moments(panels, gamma, v_inf, alpha_rad, rho, d_inf_unit,
                           symmetry, moment_ref_pt):
    """
    Compute total aerodynamic force and moment vectors using Kutta-Joukowski
    theorem applied at each bound vortex segment.

    The local velocity at each bound vortex midpoint is the freestream plus
    the induced velocity from all other vortex elements (including the panel's
    own trailing legs, but excluding its own bound vortex segment to avoid
    singularity).
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
        # panel k's own bound vortex
        V_induced = np.zeros(3)

        for j in range(n_panels):
            A_j = panels[j]["bound_A"]
            B_j = panels[j]["bound_B"]

            if j == k:
                # Only trailing legs, no bound vortex
                v_left = -biot_savart_semi_inf(midpt, A_j, d_inf_unit)
                v_right = biot_savart_semi_inf(midpt, B_j, d_inf_unit)
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

    # For symmetric wing, double the force (mirror side contributes equally)
    if symmetry:
        total_force *= 2.0

    return total_force, total_moment


def compute_coefficients(total_force, total_moment, v_inf, rho, S_ref, c_ref,
                         alpha_rad, AR):
    """
    Decompose total force and moment into aerodynamic coefficients.
    Lift and drag are in the wind-axis frame.
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
