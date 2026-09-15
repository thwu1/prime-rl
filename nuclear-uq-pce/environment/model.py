import numpy as np


def evaluate(x):
    """
    Nuclear reactor thermal-hydraulic safety model.

    Computes safety metrics for a simplified pressurized water reactor
    channel under uncertain operating conditions using the Dittus-Boelter
    correlation for forced convection heat transfer.

    Inputs (4 uncertain parameters):
        x[0]: Relative power level          ~ Uniform(0.9, 1.1)
        x[1]: Inlet temperature perturbation [K] ~ Normal(0, 5)
        x[2]: Pressure factor               ~ Uniform(0.95, 1.05)
        x[3]: Flow rate factor              ~ Normal(1.0, 0.03)

    Returns:
        [peak_clad_temp, dnbr]
        peak_clad_temp: Peak cladding temperature [K]
        dnbr:           Departure from Nucleate Boiling Ratio
    """
    power_rel = x[0]
    dT_inlet = x[1]
    P_factor = x[2]
    flow_factor = x[3]

    # Nominal conditions
    T_inlet = 565.0 + dT_inlet          # K
    q_flux = 0.6e6 * power_rel          # W/m^2
    P = 15.5 * P_factor                 # MPa
    G = 3800.0 * flow_factor            # kg/(m^2 s)
    D_h = 0.0118                        # m  (hydraulic diameter)
    L = 3.66                            # m  (active fuel length)

    # Simplified coolant properties at ~15.5 MPa
    cp = 5500.0                         # J/(kg K)
    k_c = 0.56                          # W/(m K)
    mu = 8.7e-5                         # Pa s
    Pr = cp * mu / k_c                  # Prandtl number (~0.855)

    # Dittus-Boelter forced convection correlation
    Re = G * D_h / mu
    Nu = 0.023 * Re**0.8 * Pr**0.4
    h_conv = Nu * k_c / D_h

    # Coolant temperature rise along channel
    dT_coolant = 4.0 * q_flux * L / (G * D_h * cp)
    T_outlet = T_inlet + dT_coolant

    # Peak cladding temperature (at outlet where coolant is hottest)
    T_clad_peak = T_outlet + q_flux / h_conv

    # Critical heat flux (simplified Bowring-type correlation)
    T_sat = 620.0                       # K (saturation temperature at ~15.5 MPa)
    subcooling = T_sat - T_outlet
    CHF = (3.5e6
           * np.sqrt(G / 3800.0)
           * (1.0 + 0.002 * subcooling)
           * (1.0 - 0.012 * (P - 15.5)))

    # Departure from Nucleate Boiling Ratio
    dnbr = CHF / q_flux

    return [float(T_clad_peak), float(dnbr)]
