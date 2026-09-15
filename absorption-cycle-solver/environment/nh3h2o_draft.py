
"""
NH3-H2O thermodynamic property functions.
Draft port — may contain errors.
Reference: Patek & Klomfar, Int. J. Refrigeration 18(4), 1995.
"""

import math

M_NH3 = 17.031  # g/mol
M_H2O = 18.015  # g/mol

# ---------------------------------------------------------------------------
# Correlation 1: Bubble-point temperature  T_b(p, x)
# ---------------------------------------------------------------------------
_BUBBLE_T0 = 100.0   # K
_BUBBLE_P0 = 2.0     # MPa
_BUBBLE_COEFFS = [
    (0.322302e1,   0,  0),
    (-0.384206e0,  0,  1),
    (0.460965e-1,  0,  2),
    (-0.378945e-2, 0,  3),
    (0.135610e-3,  0,  4),
    (0.487755e0,   1,  0),
    (-0.120108e0,  1,  1),
    (0.106154e-1,  1,  2),
    (-0.533589e-3, 2,  3),
    (0.785401e1,   4,  0),
    (-0.115941e2,  5,  0),
    (-0.523150e-1, 5,  1),
    (0.489596e1,   6,  0),
    (0.421059e-1,  13, 1),
]

# ---------------------------------------------------------------------------
# Correlation 2: Dew-point temperature  T_d(p, y)
# ---------------------------------------------------------------------------
_DEW_T0 = 100.0
_DEW_P0 = 2.0
_DEW_COEFFS = [
    (0.324004e1,   0, 0),
    (-0.395920e0,  0, 1),
    (0.435624e-1,  0, 2),
    (-0.218943e-2, 0, 3),
    (-0.143526e1,  1, 0),
    (0.105256e1,   1, 1),
    (-0.719281e-1, 1, 2),
    (0.122362e2,   2, 0),
    (-0.224368e1,  2, 1),
    (-0.201780e2,  3, 0),
    (0.110834e1,   3, 1),
    (0.145399e2,   4, 0),
    (0.644312e0,   4, 2),
    (-0.221246e1,  5, 0),
    (-0.756266e0,  5, 2),
    (-0.135529e1,  6, 0),
    (0.183541e0,   7, 2),
]

# ---------------------------------------------------------------------------
# Correlation 3: Vapor composition  y(p, x)
# ---------------------------------------------------------------------------
_VAPOR_P0 = 2.0
_VAPOR_COEFFS = [
    (1.98022017e1,   0, 0),
    (-1.18092669e1,  0, 1),
    (2.77479980e1,   0, 6),
    (-2.88634277e1,  0, 7),
    (-5.91616608e1,  1, 0),
    (5.78091305e2,   2, 1),
    (-6.21736743e0,  2, 2),
    (-3.42198402e3,  3, 2),
    (1.19403127e4,   4, 3),
    (-2.45413777e4,  5, 4),
    (2.91591865e4,   6, 5),
    (-1.84782290e4,  7, 6),
    (2.34819434e1,   7, 7),
    (4.80310617e3,   8, 7),
]

# ---------------------------------------------------------------------------
# Correlation 4: Liquid enthalpy  h_L(T, x)
# ---------------------------------------------------------------------------
_LIQ_H0 = 100.0    # kJ/kg
_LIQ_T0 = 273.16   # K
_LIQ_COEFFS = [
    (-0.761080e1,  0, 1),
    (0.256905e2,   0, 4),
    (-0.247092e3,  0, 8),
    (0.325952e3,   0, 9),
    (-0.158854e3,  0, 12),
    (0.619084e2,   0, 14),
    (0.114314e2,   1, 0),
    (0.118157e1,   1, 1),
    (0.284179e1,   2, 1),
    (0.741609e1,   3, 3),
    (0.891844e3,   5, 3),
    (-0.161309e4,  5, 4),
    (0.622106e3,   5, 5),
    (0.207588e3,   6, 2),
    (-0.687393e1,  6, 4),
    (0.350716e1,   8, 0),
]

# ---------------------------------------------------------------------------
# Correlation 5: Vapor enthalpy  h_V(T, y)
# ---------------------------------------------------------------------------
_VAP_H0 = 1000.0   # kJ/kg
_VAP_T0 = 324.0     # K
_VAP_COEFFS = [
    (0.128827e1,   0, 0),
    (0.125247e0,   1, 0),
    (-0.208748e1,  2, 0),
    (0.217696e1,   3, 0),
    (0.235687e1,   0, 2),
    (-0.886987e1,  1, 2),
    (0.102635e2,   2, 2),
    (-0.237440e1,  3, 2),
    (-0.670155e1,  0, 3),
    (0.164508e2,   1, 3),
    (-0.936849e1,  2, 3),
    (0.842254e1,   0, 4),
    (-0.858907e1,  1, 4),
    (-0.277049e1,  0, 5),
    (-0.961248e0,  4, 6),
    (0.988009e0,   2, 7),
    (0.308482e0,   1, 10),
]


def bubble_temperature(p_MPa, x_molar):
    """Bubble-point temperature T_b(p, x) in K."""
    lnp = math.log(_BUBBLE_P0 / p_MPa)
    omx = 1.0 - x_molar
    result = 0.0
    for a, m, n in _BUBBLE_COEFFS:
        result += a * (omx ** m) * (lnp ** n)
    return _BUBBLE_T0 * result


def dew_temperature(p_MPa, y_molar):
    """Dew-point temperature T_d(p, y) in K."""
    lnp = math.log(_DEW_P0 / p_MPa)
    omy = 1.0 - y_molar
    result = 0.0
    for a, m, n in _DEW_COEFFS:
        result += a * (omy ** m) * (lnp ** n)
    return _DEW_T0 * result


def vapor_composition(p_MPa, x_molar):
    """Vapor composition y(p, x) as molar fraction."""
    pr = p_MPa / _VAPOR_P0
    s = 0.0
    for a, m, n in _VAPOR_COEFFS:
        s += a * (pr ** m) * (x_molar ** (n / 3.0))
    return 1.0 - math.exp(math.log(1.0 - x_molar) + s)


def liquid_enthalpy(T_K, x_molar):
    """Liquid enthalpy h_L(T, x) in kJ/kg."""
    tau = T_K / _LIQ_T0 - 1.0
    result = 0.0
    for a, m, n in _LIQ_COEFFS:
        result += a * (tau ** m) * (x_molar ** n)
    return _LIQ_H0 * result


def vapor_enthalpy(T_K, y_molar):
    """Vapor enthalpy h_V(T, y) in kJ/kg."""
    tau = 1.0 - T_K / _VAP_T0
    omy = 1.0 - y_molar
    result = 0.0
    for a, m, n in _VAP_COEFFS:
        result += a * (tau ** m) * (omy ** (n / 4.0))
    return _VAP_H0 * result


def molar_to_mass_fraction(x_molar):
    """Convert NH3 molar fraction to mass fraction."""
    return x_molar * M_NH3 / (x_molar * M_NH3 + (1.0 - x_molar) * M_H2O)


def mass_to_molar_fraction(w_mass):
    """Convert NH3 mass fraction to molar fraction."""
    return w_mass * M_H2O / (w_mass * M_H2O + (1.0 - w_mass) * M_NH3)
