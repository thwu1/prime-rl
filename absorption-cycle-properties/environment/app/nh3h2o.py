"""
Ammonia-water (NH3-H2O) thermodynamic property correlations.

Based on Patek & Klomfar (1995), "Simple functions for fast calculations of
selected thermodynamic properties of the ammonia-water system",
International Journal of Refrigeration, 18(4), 228-234.

All functions use:
  - Pressure p in MPa
  - Temperature T in K
  - Molar fractions x (liquid) and y (vapor) of NH3
  - Enthalpy in kJ/kg
"""

from math import log, exp

# Molar masses (g/mol)
M_NH3 = 17.031
M_H2O = 18.015

# ---- Correlation 1: Bubble-point temperature T_b(p, x) ----
# T_b = T0 * sum_i[ a_i * (1-x)^m_i * ln(p0/p)^n_i ]
_C1 = {
    1:  {'a':  0.322302e+1, 'm': 0,  'n': 0},
    2:  {'a': -0.384206e+0, 'm': 0,  'n': 1},
    3:  {'a':  0.460965e-1, 'm': 0,  'n': 2},
    4:  {'a': -0.378945e-2, 'm': 0,  'n': 3},
    5:  {'a':  0.135610e-3, 'm': 0,  'n': 4},
    6:  {'a':  0.487755e+0, 'm': 1,  'n': 0},
    7:  {'a': -0.120108e+0, 'm': 1,  'n': 1},
    8:  {'a':  0.106154e-1, 'm': 1,  'n': 2},
    9:  {'a': -0.533589e-3, 'm': 2,  'n': 2},
    10: {'a':  0.785041e+1, 'm': 4,  'n': 0},
    11: {'a': -0.115941e+2, 'm': 5,  'n': 0},
    12: {'a': -0.523150e-1, 'm': 5,  'n': 1},
    13: {'a':  0.489596e+1, 'm': 6,  'n': 0},
    14: {'a':  0.421059e-1, 'm': 13, 'n': 1},
}
_C1_T0 = 100
_C1_p0 = 2

# ---- Correlation 2: Dew-point temperature T_d(p, y) ----
# T_d = T0 * sum_i[ a_i * (1-y)^(m_i/4) * ln(p0/p)^n_i ]
_C2 = {
    1:  {'a':  0.324004e+1, 'm': 0,  'n': 0},
    2:  {'a': -0.395920e+0, 'm': 0,  'n': 1},
    3:  {'a':  0.435624e-1, 'm': 0,  'n': 2},
    4:  {'a': -0.218943e-2, 'm': 0,  'n': 3},
    5:  {'a': -0.143526e+1, 'm': 1,  'n': 0},
    6:  {'a':  0.105256e+1, 'm': 1,  'n': 1},
    7:  {'a': -0.719281e-1, 'm': 1,  'n': 2},
    8:  {'a':  0.122362e+2, 'm': 2,  'n': 0},
    9:  {'a': -0.224368e+1, 'm': 2,  'n': 1},
    10: {'a': -0.201780e+2, 'm': 3,  'n': 0},
    11: {'a':  0.110834e+1, 'm': 3,  'n': 1},
    12: {'a':  0.145399e+2, 'm': 4,  'n': 0},
    13: {'a':  0.644312e+0, 'm': 5,  'n': 2},
    14: {'a': -0.221246e+1, 'm': 5,  'n': 0},
    15: {'a': -0.756266e+0, 'm': 5,  'n': 2},
    16: {'a': -0.135529e+1, 'm': 6,  'n': 0},
    17: {'a':  0.183541e+0, 'm': 7,  'n': 2},
}
_C2_T0 = 100
_C2_p0 = 2

# ---- Correlation 3: Vapor composition y(p, x) ----
# y = 1 - exp( ln(1-x) * sum_i[ a_i * (p/p0)^m_i * x^(n_i/3) ] )
_C3 = {
    1:  {'a':  1.98022017e+1, 'm': 0, 'n': 0},
    2:  {'a': -1.18092669e+1, 'm': 0, 'n': 1},
    3:  {'a':  2.77479980e+1, 'm': 0, 'n': 6},
    4:  {'a': -2.88634277e+1, 'm': 0, 'n': 7},
    5:  {'a': -5.91616608e+1, 'm': 1, 'n': 0},
    6:  {'a':  5.78091305e+2, 'm': 2, 'n': 1},
    7:  {'a': -6.21736743e+0, 'm': 2, 'n': 3},
    8:  {'a': -3.42198402e+3, 'm': 3, 'n': 2},
    9:  {'a':  1.19403127e+4, 'm': 4, 'n': 3},
    10: {'a': -2.45413777e+4, 'm': 5, 'n': 4},
    11: {'a':  2.91591865e+4, 'm': 6, 'n': 5},
    12: {'a': -1.84782290e+4, 'm': 7, 'n': 6},
    13: {'a':  2.34819434e+1, 'm': 7, 'n': 7},
    14: {'a':  4.80310617e+3, 'm': 8, 'n': 7},
}
_C3_p0 = 2

# ---- Correlation 4: Liquid enthalpy h_L(T, x) ----
# h_L = h0 * sum_i[ a_i * (T/T0 - 1)^m_i * x^n_i ]
_C4 = {
    1:  {'a': -0.761080e+1, 'm': 0, 'n': 1},
    2:  {'a':  0.256905e+2, 'm': 0, 'n': 4},
    3:  {'a': -0.274092e+3, 'm': 0, 'n': 8},
    4:  {'a':  0.325952e+3, 'm': 0, 'n': 9},
    5:  {'a': -0.158854e+3, 'm': 0, 'n': 12},
    6:  {'a':  0.619084e+2, 'm': 0, 'n': 14},
    7:  {'a':  0.114314e+2, 'm': 1, 'n': 0},
    8:  {'a':  0.118157e+1, 'm': 1, 'n': 1},
    9:  {'a':  0.284179e+1, 'm': 2, 'n': 1},
    10: {'a':  0.741609e+1, 'm': 3, 'n': 3},
    11: {'a':  0.891844e+3, 'm': 5, 'n': 3},
    12: {'a': -0.161309e+4, 'm': 5, 'n': 4},
    13: {'a':  0.622106e+3, 'm': 5, 'n': 5},
    14: {'a': -0.207588e+3, 'm': 6, 'n': 2},
    15: {'a': -0.687393e+1, 'm': 6, 'n': 4},
    16: {'a':  0.350716e+1, 'm': 8, 'n': 0},
}
_C4_h0 = 100
_C4_T0 = 273.16

# ---- Correlation 5: Vapor enthalpy h_V(T, y) ----
# h_V = h0 * sum_i[ a_i * (1 - T/T0)^m_i * (1-y)^(n_i/4) ]
_C5 = {
    1:  {'a':  0.128827e+1, 'm': 0, 'n': 0},
    2:  {'a':  0.125247e+0, 'm': 1, 'n': 0},
    3:  {'a': -0.208748e+1, 'm': 2, 'n': 0},
    4:  {'a':  0.217696e+1, 'm': 3, 'n': 0},
    5:  {'a':  0.235687e+1, 'm': 0, 'n': 2},
    6:  {'a': -0.886987e+1, 'm': 1, 'n': 2},
    7:  {'a':  0.102635e+2, 'm': 2, 'n': 2},
    8:  {'a': -0.237440e+1, 'm': 3, 'n': 2},
    9:  {'a': -0.670155e+1, 'm': 0, 'n': 3},
    10: {'a':  0.164508e+2, 'm': 1, 'n': 3},
    11: {'a': -0.936849e+1, 'm': 2, 'n': 3},
    12: {'a':  0.842254e+1, 'm': 0, 'n': 4},
    13: {'a': -0.858907e+1, 'm': 1, 'n': 4},
    14: {'a': -0.277049e+1, 'm': 0, 'n': 5},
    15: {'a': -0.961248e+0, 'm': 4, 'n': 6},
    16: {'a':  0.988009e+0, 'm': 2, 'n': 7},
    17: {'a':  0.308482e+0, 'm': 1, 'n': 10},
}
_C5_h0 = 1000
_C5_T0 = 324


def T_from_px(p, x):
    """Bubble-point temperature [K] from pressure [MPa] and liquid molar fraction x."""
    return _C1_T0 * sum(
        c['a'] * (1 - x)**c['m'] * log(_C1_p0 / p)**c['n']
        for c in _C1.values()
    )


def T_from_py(p, y):
    """Dew-point temperature [K] from pressure [MPa] and vapor molar fraction y."""
    return _C2_T0 * sum(
        c['a'] * (1 - y)**(c['m'] / 4) * log(_C2_p0 / p)**c['n']
        for c in _C2.values()
    )


def y_from_px(p, x):
    """Vapor molar fraction from pressure [MPa] and liquid molar fraction x."""
    s = sum(
        c['a'] * (p / _C3_p0)**c['m'] * x**(c['n'] / 3)
        for c in _C3.values()
    )
    return 1 - exp(log(1 - x) * s)


def Hl_from_Tx(T, x):
    """Liquid enthalpy [kJ/kg] from temperature [K] and liquid molar fraction x."""
    return _C4_h0 * sum(
        c['a'] * (T / _C4_T0 - 1)**c['m'] * x**c['n']
        for c in _C4.values()
    )


def Hg_from_Ty(T, y):
    """Vapor enthalpy [kJ/kg] from temperature [K] and vapor molar fraction y."""
    return _C5_h0 * sum(
        c['a'] * (1 - T / _C5_T0)**c['m'] * (1 - y)**(c['n'] / 4)
        for c in _C5.values()
    )


def molar_to_mass(q):
    """Convert NH3 molar fraction to mass fraction."""
    return q * M_NH3 / (q * M_NH3 + (1 - q) * M_H2O)


def mass_to_molar(q):
    """Convert NH3 mass fraction to molar fraction."""
    return q * M_H2O / (q * M_H2O + (1 - q) * M_NH3)
