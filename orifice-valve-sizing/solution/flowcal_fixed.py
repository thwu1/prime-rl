"""Flow analysis module — FIXED version.

Corrects 3 defects in the original flowcal.py:
1. _TAP_MAP: flange/D values swapped → corrected to match C header
2. size_liquid_valve: choked+piping uses FL → FLP
3. size_gas_valve: Y clamp 1/3 → 2/3

(C-side fixes are in flowcore_fixed.c)
"""

import ctypes
import os
from math import pi, sqrt

# ──────────────────────────────────────────────────────────────
# Physical and IEC constants
# ──────────────────────────────────────────────────────────────
R_GAS = 8.31446261815324

_N1 = 0.1
_N2 = 1.6e-3
_N5 = 1.8e-3
_N9 = 2.46e1
_RHO0 = 999.10329075702327

# ──────────────────────────────────────────────────────────────
# Load C shared library
# ──────────────────────────────────────────────────────────────
_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libflowcore.so")


def _load_lib():
    if not os.path.exists(_LIB_PATH):
        raise FileNotFoundError(
            f"Shared library not found at {_LIB_PATH}. "
            "Run 'make' in /app to build it."
        )
    lib = ctypes.CDLL(_LIB_PATH)

    lib.orifice_C.argtypes = [
        ctypes.c_double, ctypes.c_double, ctypes.c_double,
        ctypes.c_double, ctypes.c_double, ctypes.c_int,
    ]
    lib.orifice_C.restype = ctypes.c_double

    lib.orifice_eps.argtypes = [
        ctypes.c_double, ctypes.c_double, ctypes.c_double,
        ctypes.c_double, ctypes.c_double,
    ]
    lib.orifice_eps.restype = ctypes.c_double

    lib.orifice_flow.argtypes = [
        ctypes.c_double, ctypes.c_double, ctypes.c_double,
        ctypes.c_double, ctypes.c_double, ctypes.c_double,
        ctypes.c_double, ctypes.c_int,
    ]
    lib.orifice_flow.restype = ctypes.c_double

    return lib


_lib = None


def _get_lib():
    global _lib
    if _lib is None:
        _lib = _load_lib()
    return _lib


# FIX: tap mapping must match C header (TAP_CORNER=0, TAP_FLANGE=1, TAP_D=2)
_TAP_MAP = {"corner": 0, "flange": 1, "D": 2}


# ──────────────────────────────────────────────────────────────
# Orifice plate — wrappers around C library functions
# ──────────────────────────────────────────────────────────────

def orifice_discharge_coefficient(D, Do, rho, mu, m, taps="corner"):
    """Compute orifice plate discharge coefficient via C library."""
    lib = _get_lib()
    tap_code = _TAP_MAP.get(taps)
    if tap_code is None:
        raise ValueError(f"Unsupported tap type: {taps}")
    return lib.orifice_C(D, Do, rho, mu, m, tap_code)


def orifice_expansibility(D, Do, P1, P2, k):
    """Compute orifice expansibility factor via C library."""
    lib = _get_lib()
    return lib.orifice_eps(D, Do, P1, P2, k)


def solve_orifice_flow_rate(D, Do, P1, P2, rho, mu, k, taps="corner"):
    """Iteratively solve for mass flow rate via C library."""
    lib = _get_lib()
    tap_code = _TAP_MAP.get(taps)
    if tap_code is None:
        raise ValueError(f"Unsupported tap type: {taps}")
    return lib.orifice_flow(D, Do, P1, P2, rho, mu, k, tap_code)


# ──────────────────────────────────────────────────────────────
# Control valve sizing — pure Python (IEC 60534)
# ──────────────────────────────────────────────────────────────

def _loss_coefficient_piping(d, D1=None, D2=None):
    """Sum of inlet/outlet piping loss coefficients."""
    loss = 0.0
    if D1 is not None:
        dr = d / D1
        dr2 = dr * dr
        loss += 1.0 - dr2 * dr2
        loss += 0.5 * (1.0 - dr2) ** 2
    if D2 is not None:
        dr = d / D2
        dr2 = dr * dr
        loss += 1.0 * (1.0 - dr2) ** 2
        loss -= 1.0 - dr2 * dr2
    return loss


def _FF_l(Psat, Pc):
    """Liquid critical pressure ratio factor."""
    return 0.96 - 0.28 * sqrt(Psat / Pc)


def _is_choked_l(dP, P1, Psat, FF, FL=None, FLP=None, FP=None):
    """Check choked flow condition for liquid service."""
    if FLP is not None and FP is not None:
        return dP >= (FLP * FLP) / (FP * FP) * (P1 - FF * Psat)
    elif FL is not None:
        return dP >= FL * FL * (P1 - FF * Psat)
    raise ValueError("Need FL or (FLP, FP)")


def size_liquid_valve(rho, Psat, Pc, mu, P1, P2, Q,
                      D1=None, D2=None, d=None, FL=0.9, Fd=1.0):
    """Size a control valve for liquid service. Returns Kv [m^3/hr]."""
    P1k = P1 * 1e-3
    P2k = P2 * 1e-3
    Psk = Psat * 1e-3
    Pck = Pc * 1e-3
    Qh = Q * 3600.0

    dP = P1k - P2k
    FF = _FF_l(Psk, Pck)
    choked = _is_choked_l(dP, P1k, Psk, FF, FL=FL)

    if choked:
        C = Qh / _N1 / FL * sqrt(rho / _RHO0 / (P1k - FF * Psk))
    else:
        C = Qh / _N1 * sqrt(rho / _RHO0 / dP)

    if D1 is None and D2 is None and d is None:
        return C

    D1m = D1 * 1000.0
    D2m = D2 * 1000.0
    dm = d * 1000.0

    if D1m != dm or D2m != dm:
        _MAX = 40
        for _ in range(_MAX):
            Ci = C
            loss = _loss_coefficient_piping(dm, D1m, D2m)
            FP = 1.0 / sqrt(1.0 + loss / _N2 * (Ci / dm ** 2) ** 2)

            if dm > D1m:
                loss_up = 0.0
            else:
                loss_up = _loss_coefficient_piping(dm, D1m)

            FLP = FL / sqrt(
                1.0 + FL ** 2 / _N2 * loss_up * (Ci / dm ** 2) ** 2
            )
            choked = _is_choked_l(dP, P1k, Psk, FF, FLP=FLP, FP=FP)

            if choked:
                # FIX: must use FLP (not FL) when choked with piping
                C = Qh / _N1 / FLP * sqrt(rho / _RHO0 / (P1k - FF * Psk))
            else:
                C = Qh / _N1 / FP * sqrt(rho / _RHO0 / dP)

            if Ci / C >= 0.99:
                break

    return C


def size_gas_valve(T, MW, mu, gamma, Z, P1, P2, Q,
                   D1=None, D2=None, d=None, FL=0.9, Fd=1.0, xT=0.7):
    """Size a control valve for gas service. Returns Kv [m^3/hr]."""
    P1k = P1 * 1e-3
    P2k = P2 * 1e-3
    Qh = Q * 3600.0

    Vm = Z * R_GAS * T / (P1k * 1000.0)
    rho_gas = MW * 1e-3 / Vm

    dP = P1k - P2k
    Fgamma = gamma / 1.40
    x = dP / P1k
    # FIX: Y must clamp at 2/3, not 1/3
    Y = max(1.0 - x / (3.0 * Fgamma * xT), 2.0 / 3.0)

    choked = x >= Fgamma * xT

    if choked:
        C = Qh / (_N9 * P1k * Y) * sqrt(MW * T * Z / xT / Fgamma)
    else:
        C = Qh / (_N9 * P1k * Y) * sqrt(MW * T * Z / x)

    if D1 is None and D2 is None and d is None:
        return C

    D1m = D1 * 1000.0
    D2m = D2 * 1000.0
    dm = d * 1000.0

    if D1m != dm or D2m != dm:
        _MAX = 40
        for _ in range(_MAX):
            Ci = C
            loss = _loss_coefficient_piping(dm, D1m, D2m)
            FP = 1.0 / sqrt(1.0 + loss / _N2 * (Ci / dm ** 2) ** 2)

            loss_up = _loss_coefficient_piping(dm, D1m)
            xTP = xT / FP ** 2 / (
                1.0 + xT * loss_up / _N5 * (Ci / dm ** 2) ** 2
            )
            choked = x >= Fgamma * xTP

            if choked:
                C = Qh / (_N9 * FP * P1k * Y) * sqrt(
                    MW * T * Z / xTP / Fgamma
                )
            else:
                C = Qh / (_N9 * FP * P1k * Y) * sqrt(MW * T * Z / x)

            if Ci / C >= 0.99:
                break

    return C
