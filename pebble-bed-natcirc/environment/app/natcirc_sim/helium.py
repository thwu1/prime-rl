"""
Helium thermophysical properties for reactor thermal-hydraulic analysis.

Transport properties computed using standard correlations for monatomic gases.
Thermodynamic properties from ideal gas law.
"""


def density(T, P, R_specific):
    """
    Helium density from ideal gas law [kg/m^3].

    Parameters
    ----------
    T : float or array
        Temperature [K]
    P : float
        Pressure [Pa]
    R_specific : float
        Specific gas constant [J/(kg·K)]
    """
    return P / (R_specific * T)


def viscosity(T):
    """
    Dynamic viscosity of helium [Pa·s].

    Uses Sutherland's law for monatomic gases (Crane TP-410).

    Parameters
    ----------
    T : float
        Temperature [K]
    """
    mu_ref = 1.96e-5    # Pa·s at T_ref
    T_ref = 273.15       # K
    S = 79.4             # Sutherland constant for He [K]
    return mu_ref * (T / T_ref) ** 1.5 * (T_ref + S) / (T + S)


def thermal_conductivity(T, k_coeff, k_exp):
    """
    Thermal conductivity of helium [W/(m·K)].

    Power-law correlation: k = k_coeff * T^k_exp

    Parameters
    ----------
    T : float or array
        Temperature [K]
    k_coeff : float
        Power-law coefficient
    k_exp : float
        Power-law exponent
    """
    return k_coeff * T ** k_exp
