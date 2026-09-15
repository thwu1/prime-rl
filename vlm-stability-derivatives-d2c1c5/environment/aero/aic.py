"""Aerodynamic Influence Coefficient matrix assembly."""
import numpy as np
from .biot_savart import horseshoe_velocity


def build_aic(panels, d_inf, symmetry):
    """
    Build the Aerodynamic Influence Coefficient matrix.
    AIC[i,j] = induced normal velocity at collocation i from horseshoe j.
    Includes mirror-image contributions for symmetric half-wing configurations.
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
                v_m = horseshoe_velocity(coll, A_m, B_m, d_inf) / (4.0 * np.pi)
                AIC[i, j] += np.dot(v_m, normal)

    return AIC
