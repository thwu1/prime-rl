"""
Supplementary thermal-hydraulic correlations.

Pressure drop correlations for duct/pipe flow sections of
the natural circulation loop (chimney, riser, downcomer).
"""


def darcy_weisbach_dp(f, L, D_h, rho, v):
    """
    Darcy-Weisbach pressure drop for pipe/duct flow [Pa].

    Parameters
    ----------
    f : float
        Darcy friction factor [-]
    L : float
        Flow path length [m]
    D_h : float
        Hydraulic diameter [m]
    rho : float
        Fluid density [kg/m^3]
    v : float
        Flow velocity [m/s]
    """
    return f * (L / D_h) * 0.5 * rho * v**2
