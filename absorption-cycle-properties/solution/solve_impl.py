#!/usr/bin/env python3
"""
Solution: fix 6 bugs in nh3h2o.py, add inverse functions, compute SHX cycle.

Bugs fixed:
1. Correlation 1 (bubble-point), coeff #9: n was 2, should be 3
2. Correlation 2 (dew-point), coeff #13: m was 5, should be 4
3. Correlation 3 (vapor composition), coeff #7: n was 3, should be 2
4. Correlation 4 (liquid enthalpy), coeff #3: a was -0.274092e3, should be -0.247092e3
5. Correlation 5 (vapor enthalpy), coeff #9: a was -0.670155e1, should be -0.670515e1
6. Correlation 5 (vapor enthalpy), coeff #13: a was -0.858907e1, should be -0.858807e1
"""

import json
import os

CORRECTED_MODULE = r'''"""
Ammonia-water (NH3-H2O) thermodynamic property correlations.
Based on Patek & Klomfar (1995).
"""

from math import log, exp
from scipy.optimize import brentq

M_NH3 = 17.031
M_H2O = 18.015

_C1 = {
    1:  {'a':  0.322302e+1, 'm': 0,  'n': 0},
    2:  {'a': -0.384206e+0, 'm': 0,  'n': 1},
    3:  {'a':  0.460965e-1, 'm': 0,  'n': 2},
    4:  {'a': -0.378945e-2, 'm': 0,  'n': 3},
    5:  {'a':  0.135610e-3, 'm': 0,  'n': 4},
    6:  {'a':  0.487755e+0, 'm': 1,  'n': 0},
    7:  {'a': -0.120108e+0, 'm': 1,  'n': 1},
    8:  {'a':  0.106154e-1, 'm': 1,  'n': 2},
    9:  {'a': -0.533589e-3, 'm': 2,  'n': 3},
    10: {'a':  0.785041e+1, 'm': 4,  'n': 0},
    11: {'a': -0.115941e+2, 'm': 5,  'n': 0},
    12: {'a': -0.523150e-1, 'm': 5,  'n': 1},
    13: {'a':  0.489596e+1, 'm': 6,  'n': 0},
    14: {'a':  0.421059e-1, 'm': 13, 'n': 1},
}
_C1_T0 = 100
_C1_p0 = 2

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
    13: {'a':  0.644312e+0, 'm': 4,  'n': 2},
    14: {'a': -0.221246e+1, 'm': 5,  'n': 0},
    15: {'a': -0.756266e+0, 'm': 5,  'n': 2},
    16: {'a': -0.135529e+1, 'm': 6,  'n': 0},
    17: {'a':  0.183541e+0, 'm': 7,  'n': 2},
}
_C2_T0 = 100
_C2_p0 = 2

_C3 = {
    1:  {'a':  1.98022017e+1, 'm': 0, 'n': 0},
    2:  {'a': -1.18092669e+1, 'm': 0, 'n': 1},
    3:  {'a':  2.77479980e+1, 'm': 0, 'n': 6},
    4:  {'a': -2.88634277e+1, 'm': 0, 'n': 7},
    5:  {'a': -5.91616608e+1, 'm': 1, 'n': 0},
    6:  {'a':  5.78091305e+2, 'm': 2, 'n': 1},
    7:  {'a': -6.21736743e+0, 'm': 2, 'n': 2},
    8:  {'a': -3.42198402e+3, 'm': 3, 'n': 2},
    9:  {'a':  1.19403127e+4, 'm': 4, 'n': 3},
    10: {'a': -2.45413777e+4, 'm': 5, 'n': 4},
    11: {'a':  2.91591865e+4, 'm': 6, 'n': 5},
    12: {'a': -1.84782290e+4, 'm': 7, 'n': 6},
    13: {'a':  2.34819434e+1, 'm': 7, 'n': 7},
    14: {'a':  4.80310617e+3, 'm': 8, 'n': 7},
}
_C3_p0 = 2

_C4 = {
    1:  {'a': -0.761080e+1, 'm': 0, 'n': 1},
    2:  {'a':  0.256905e+2, 'm': 0, 'n': 4},
    3:  {'a': -0.247092e+3, 'm': 0, 'n': 8},
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

_C5 = {
    1:  {'a':  0.128827e+1, 'm': 0, 'n': 0},
    2:  {'a':  0.125247e+0, 'm': 1, 'n': 0},
    3:  {'a': -0.208748e+1, 'm': 2, 'n': 0},
    4:  {'a':  0.217696e+1, 'm': 3, 'n': 0},
    5:  {'a':  0.235687e+1, 'm': 0, 'n': 2},
    6:  {'a': -0.886987e+1, 'm': 1, 'n': 2},
    7:  {'a':  0.102635e+2, 'm': 2, 'n': 2},
    8:  {'a': -0.237440e+1, 'm': 3, 'n': 2},
    9:  {'a': -0.670515e+1, 'm': 0, 'n': 3},
    10: {'a':  0.164508e+2, 'm': 1, 'n': 3},
    11: {'a': -0.936849e+1, 'm': 2, 'n': 3},
    12: {'a':  0.842254e+1, 'm': 0, 'n': 4},
    13: {'a': -0.858807e+1, 'm': 1, 'n': 4},
    14: {'a': -0.277049e+1, 'm': 0, 'n': 5},
    15: {'a': -0.961248e+0, 'm': 4, 'n': 6},
    16: {'a':  0.988009e+0, 'm': 2, 'n': 7},
    17: {'a':  0.308482e+0, 'm': 1, 'n': 10},
}
_C5_h0 = 1000
_C5_T0 = 324


def T_from_px(p, x):
    return _C1_T0 * sum(
        c['a'] * (1 - x)**c['m'] * log(_C1_p0 / p)**c['n']
        for c in _C1.values()
    )


def T_from_py(p, y):
    return _C2_T0 * sum(
        c['a'] * (1 - y)**(c['m'] / 4) * log(_C2_p0 / p)**c['n']
        for c in _C2.values()
    )


def y_from_px(p, x):
    s = sum(
        c['a'] * (p / _C3_p0)**c['m'] * x**(c['n'] / 3)
        for c in _C3.values()
    )
    return 1 - exp(log(1 - x) * s)


def Hl_from_Tx(T, x):
    return _C4_h0 * sum(
        c['a'] * (T / _C4_T0 - 1)**c['m'] * x**c['n']
        for c in _C4.values()
    )


def Hg_from_Ty(T, y):
    return _C5_h0 * sum(
        c['a'] * (1 - T / _C5_T0)**c['m'] * (1 - y)**(c['n'] / 4)
        for c in _C5.values()
    )


def molar_to_mass(q):
    return q * M_NH3 / (q * M_NH3 + (1 - q) * M_H2O)


def mass_to_molar(q):
    return q * M_H2O / (q * M_H2O + (1 - q) * M_NH3)


def p_from_Tx(T, x):
    return brentq(lambda p: T_from_px(p, x) - T, 0.001, 5.0, xtol=1e-10)


def x_from_pT(p, T):
    return brentq(lambda x: T_from_px(p, x) - T, 0.001, 0.999, xtol=1e-10)


def T_from_hx(h, x):
    return brentq(lambda T: Hl_from_Tx(T, x) - h, 250, 450, xtol=1e-8)
'''

# Write the corrected module
with open('/app/nh3h2o.py', 'w') as f:
    f.write(CORRECTED_MODULE)

print("Corrected nh3h2o.py written with 6 bug fixes and 3 inverse functions.")

# Ensure cycle_spec.json exists at /app/
CYCLE_SPEC = {
    "description": "Single-effect NH3-H2O absorption chiller with solution heat exchanger (SHX)",
    "x_strong_molar": 0.5,
    "x_weak_molar": 0.3,
    "P_high_MPa": 1.5,
    "P_low_MPa": 0.2,
    "m_ref_kgps": 1.0,
    "SHX_effectiveness": 0.7,
    "SHX_definition": "Temperature effectiveness on the hot (weak solution) side: eps = (T_hot_in - T_hot_out) / (T_hot_in - T_cold_in)",
    "assumptions": [
        "No rectifier",
        "Negligible pump work",
        "Isenthalpic expansion valves",
        "Generator operates at bubble point of weak solution at P_high; vapor in equilibrium at same conditions",
        "Absorber operates at bubble point of strong solution at P_low",
        "Complete condensation of refrigerant vapor to saturated liquid at P_high",
        "Complete evaporation at evaporator outlet; vapor at dew point at P_low",
        "SHX hot stream: weak solution leaving generator; cold stream: strong solution leaving absorber",
        "All energy balances use enthalpy correlations; do not assume constant specific heat"
    ]
}

if not os.path.exists('/app/cycle_spec.json'):
    with open('/app/cycle_spec.json', 'w') as f:
        json.dump(CYCLE_SPEC, f, indent=2)
    print("Created /app/cycle_spec.json (was missing from environment).")

# Compute cycle results
import sys
sys.path.insert(0, '/app')
if 'nh3h2o' in sys.modules:
    del sys.modules['nh3h2o']
import nh3h2o

with open('/app/cycle_spec.json') as f:
    cfg = json.load(f)

P_hi = cfg['P_high_MPa']
P_lo = cfg['P_low_MPa']
x_s = cfg['x_strong_molar']
x_w = cfg['x_weak_molar']
m_r = cfg['m_ref_kgps']
eps = cfg['SHX_effectiveness']

# Basic state points
T_gen = nh3h2o.T_from_px(P_hi, x_w)
T_abs = nh3h2o.T_from_px(P_lo, x_s)
y_ref = nh3h2o.y_from_px(P_hi, x_w)

h_wk = nh3h2o.Hl_from_Tx(T_gen, x_w)
h_st = nh3h2o.Hl_from_Tx(T_abs, x_s)
h_vap = nh3h2o.Hg_from_Ty(T_gen, y_ref)

# Condenser and evaporator
T_cond = nh3h2o.T_from_px(P_hi, y_ref)
h_cond = nh3h2o.Hl_from_Tx(T_cond, y_ref)
T_evap = nh3h2o.T_from_py(P_lo, y_ref)
h_evap = nh3h2o.Hg_from_Ty(T_evap, y_ref)

# Mass fractions and circulation ratio
w_s = nh3h2o.molar_to_mass(x_s)
w_w = nh3h2o.molar_to_mass(x_w)
w_r = nh3h2o.molar_to_mass(y_ref)
f = (w_r - w_w) / (w_s - w_w)

m_wk = (f - 1) * m_r
m_st = f * m_r

# SHX calculations
T_wk_out = T_gen - eps * (T_gen - T_abs)
h_wk_out = nh3h2o.Hl_from_Tx(T_wk_out, x_w)
Q_SHX = m_wk * (h_wk - h_wk_out)
h_st_out = h_st + Q_SHX / m_st
T_st_out = nh3h2o.T_from_hx(h_st_out, x_s)

# Generator energy balance with SHX
Q_gen = (h_vap + (f - 1) * h_wk - f * h_st_out) * m_r
Q_evap = (h_evap - h_cond) * m_r
COP = Q_evap / Q_gen

# Without SHX (for comparison)
Q_gen_no = (h_vap + (f - 1) * h_wk - f * h_st) * m_r
COP_no = Q_evap / Q_gen_no

results = {
    "T_generator_K": round(T_gen, 6),
    "T_absorber_K": round(T_abs, 6),
    "y_refrigerant_molar": round(y_ref, 8),
    "h_weak_gen_kJperkg": round(h_wk, 4),
    "h_strong_abs_kJperkg": round(h_st, 4),
    "h_refrigerant_vapor_kJperkg": round(h_vap, 4),
    "T_condenser_K": round(T_cond, 6),
    "h_condensed_liquid_kJperkg": round(h_cond, 4),
    "T_evaporator_K": round(T_evap, 6),
    "h_evaporator_vapor_kJperkg": round(h_evap, 4),
    "circulation_ratio": round(f, 6),
    "T_weak_SHX_out_K": round(T_wk_out, 6),
    "h_strong_SHX_out_kJperkg": round(h_st_out, 4),
    "T_strong_SHX_out_K": round(T_st_out, 6),
    "Q_SHX_kW": round(Q_SHX, 4),
    "Q_generator_kW": round(Q_gen, 4),
    "Q_evaporator_kW": round(Q_evap, 4),
    "COP_cooling": round(COP, 6),
    "COP_no_SHX": round(COP_no, 6),
}

with open('/app/cycle_results.json', 'w') as f:
    json.dump(results, f, indent=2)

print("Cycle results written to /app/cycle_results.json:")
for k, v in results.items():
    print(f"  {k}: {v}")
