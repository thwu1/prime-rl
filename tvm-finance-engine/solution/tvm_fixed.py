"""
Time Value of Money (TVM) financial computation library — corrected version.

Pure-Python implementation for capital budgeting, loan amortization,
and investment analysis. Supports numpy broadcasting and decimal.Decimal.

Includes native C accelerator for NPV computation when available.
"""


import ctypes
import os
import numpy as np
from decimal import Decimal

__all__ = ['fv', 'pv', 'pmt', 'nper', 'ipmt', 'ppmt', 'rate',
           'irr', 'npv', 'mirr', 'xnpv', 'xirr']

# --- Native C accelerator loading ---
_native_lib = None
_npv_native = None


def _load_native_backend():
    """Attempt to load the native NPV shared library via ctypes."""
    global _native_lib, _npv_native
    native_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'native')
    lib_path = os.path.join(native_dir, 'libdiscount.so')
    try:
        _native_lib = ctypes.CDLL(lib_path)
        _npv_native = _native_lib.npv_native
        _npv_native.argtypes = [
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
        ]
        _npv_native.restype = ctypes.c_double
    except OSError:
        _native_lib = None
        _npv_native = None


_load_native_backend()


# --- Internal helpers ---

_when_to_num = {
    'end': 0, 'begin': 1, 'e': 0, 'b': 1,
    0: 0, 1: 1, 'beginning': 1, 'start': 1, 'finish': 0,
}


def _convert_when(when):
    if isinstance(when, np.ndarray):
        return when
    try:
        return _when_to_num[when]
    except (KeyError, TypeError):
        return [_when_to_num[x] for x in when]


def _ufunc_like(array):
    try:
        return array.item()
    except ValueError:
        return array.squeeze()


def _value_like(arr, value):
    entry = arr.item(0)
    if isinstance(entry, Decimal):
        if value != value:
            return Decimal('nan')
        return Decimal(value)
    return np.array(value, dtype=arr.dtype).item(0)


# =====================================================================
# Future Value
# =====================================================================
def fv(rate, nper, pmt, pv, when='end'):
    """Compute the future value."""
    when = _convert_when(when)
    rate, nper, pmt, pv, when = np.broadcast_arrays(rate, nper, pmt, pv, when)

    fv_array = np.empty_like(rate)
    zero = rate == 0
    nonzero = ~zero

    fv_array[zero] = -(pv[zero] + pmt[zero] * nper[zero])

    rate_nz = rate[nonzero]
    temp = (1 + rate_nz) ** nper[nonzero]
    fv_array[nonzero] = (
        - pv[nonzero] * temp
        - pmt[nonzero] * (1 + rate_nz * when[nonzero]) / rate_nz
        * (temp - 1)
    )

    if np.ndim(fv_array) == 0:
        return fv_array.item(0)
    return fv_array


# =====================================================================
# Present Value
# =====================================================================
def pv(rate, nper, pmt, fv=0, when='end'):
    """Compute the present value."""
    when = _convert_when(when)
    rate, nper, pmt, fv, when = map(np.asarray, [rate, nper, pmt, fv, when])
    temp = (1 + rate) ** nper
    fact = np.where(rate == 0, nper, (1 + rate * when) * (temp - 1) / rate)
    return -(fv + pmt * fact) / temp


# =====================================================================
# Payment
# =====================================================================
def pmt(rate, nper, pv, fv=0, when='end'):
    """Compute the payment against loan principal plus interest."""
    when = _convert_when(when)
    (rate, nper, pv, fv, when) = map(np.array, [rate, nper, pv, fv, when])
    temp = (1 + rate) ** nper
    mask = (rate == 0)
    masked_rate = np.where(mask, 1, rate)
    fact = np.where(mask != 0, nper,
                    (1 + masked_rate * when) * (temp - 1) / masked_rate)
    return -(fv + pv * temp) / fact


# =====================================================================
# Number of Periods
# =====================================================================
def nper(rate, pmt, pv, fv=0, when='end'):
    """Compute the number of periodic payments."""
    when = _convert_when(when)
    rate = np.atleast_1d(np.asarray(rate, dtype=np.float64))
    pmt_arr = np.atleast_1d(np.asarray(pmt, dtype=np.float64))
    pv_arr = np.atleast_1d(np.asarray(pv, dtype=np.float64))
    fv_arr = np.atleast_1d(np.asarray(fv, dtype=np.float64))
    when_arr = np.atleast_1d(np.asarray(when, dtype=np.float64))

    rate, pmt_arr, pv_arr, fv_arr, when_arr = np.broadcast_arrays(
        rate, pmt_arr, pv_arr, fv_arr, when_arr)

    result = np.empty_like(rate, dtype=np.float64)

    zero_rate = rate == 0
    nonzero_rate = ~zero_rate

    if np.any(zero_rate):
        with np.errstate(divide='ignore', invalid='ignore'):
            result[zero_rate] = -(pv_arr[zero_rate] + fv_arr[zero_rate]) / pmt_arr[zero_rate]

    if np.any(nonzero_rate):
        r = rate[nonzero_rate]
        p = pmt_arr[nonzero_rate]
        x = pv_arr[nonzero_rate]
        y = fv_arr[nonzero_rate]
        w = when_arr[nonzero_rate]

        A = p * (1 + r * w) / r
        with np.errstate(divide='ignore', invalid='ignore'):
            vals = np.log((-y + A) / (x + A)) / np.log(1 + r)
        bad = r <= -1
        vals[bad] = np.nan
        result[nonzero_rate] = vals

    return _ufunc_like(result)


# =====================================================================
# Interest Portion of Payment — FIX: exponent 1 not 2
# =====================================================================
def _rbl(rate, per, pmt, pv, when):
    """Remaining balance on loan."""
    return fv(rate, (per - 1), pmt, pv, when)


def ipmt(rate, per, nper, pv, fv=0, when='end'):
    """Compute the interest portion of a payment."""
    when = _convert_when(when)
    rate, per, nper, pv, fv, when = np.broadcast_arrays(
        rate, per, nper, pv, fv, when)

    total_pmt = pmt(rate, nper, pv, fv, when)
    ipmt_array = np.array(_rbl(rate, per, total_pmt, pv, when) * rate)

    ipmt_array[per < 1] = _value_like(ipmt_array, np.nan)

    per1_and_begin = (when == 1) & (per == 1)
    ipmt_array[per1_and_begin] = _value_like(ipmt_array, 0)

    per_gt_1_and_begin = (when == 1) & (per > 1)
    ipmt_array[per_gt_1_and_begin] = (
        ipmt_array[per_gt_1_and_begin] / (1 + rate[per_gt_1_and_begin])
    )

    if np.ndim(ipmt_array) == 0:
        return ipmt_array.item(0)
    return ipmt_array


# =====================================================================
# Principal Portion of Payment
# =====================================================================
def ppmt(rate, per, nper, pv, fv=0, when='end'):
    """Compute the payment against loan principal."""
    total = pmt(rate, nper, pv, fv, when)
    return total - ipmt(rate, per, nper, pv, fv, when)


# =====================================================================
# Rate (Newton-Raphson solver) — FIX: Decimal type propagation
# =====================================================================
def _g_div_gp(r, n, p, x, y, w):
    t1 = (r + 1) ** n
    t2 = (r + 1) ** (n - 1)
    g = y + t1 * x + p * (t1 - 1) * (r * w + 1) / r
    gp = (n * t2 * x
          - p * (t1 - 1) * (r * w + 1) / (r ** 2)
          + n * p * t2 * (r * w + 1) / r
          + p * (t1 - 1) * w / r)
    return g / gp


def rate(nper, pmt, pv, fv, when='end', guess=None, tol=None, maxiter=100):
    """Compute the rate of interest per period via Newton-Raphson."""
    when = _convert_when(when)
    default_type = Decimal if isinstance(pmt, Decimal) else float

    if guess is None:
        guess = default_type('0.1')
    if tol is None:
        tol = default_type('1e-6')

    nper, pmt, pv, fv, when = map(np.asarray, [nper, pmt, pv, fv, when])

    rn = guess
    iterator = 0
    close = False
    while (iterator < maxiter) and not np.all(close):
        rnp1 = rn - _g_div_gp(rn, nper, pmt, pv, fv, when)
        diff = abs(rnp1 - rn)
        close = diff < tol
        iterator += 1
        rn = rnp1

    if not np.all(close):
        if np.isscalar(rn):
            return default_type(np.nan)
        else:
            rn[~close] = np.nan
    return rn


# =====================================================================
# Internal Rate of Return — FIX: argmin not argmax
# =====================================================================
def _irr_default_selection(eirr):
    """Select IRR from multiple real solutions."""
    same_sign = np.all(eirr > 0) if eirr[0] > 0 else np.all(eirr < 0)

    if not same_sign:
        pos = sum(eirr[eirr > 0])
        neg = sum(eirr[eirr < 0])
        if pos >= neg:
            eirr = eirr[eirr >= 0]
        else:
            eirr = eirr[eirr < 0]

    abs_eirr = np.abs(eirr)
    return eirr[np.argmin(abs_eirr)]


def irr(values):
    """Return the Internal Rate of Return (IRR)."""
    values = np.atleast_2d(values)
    if values.ndim != 2:
        raise ValueError("Cashflows must be a 2D array")

    irr_results = np.empty(values.shape[0])
    for i, row in enumerate(values):
        same_sign = np.all(row > 0) if row[0] > 0 else np.all(row < 0)
        if same_sign:
            irr_results[i] = np.nan
        else:
            g = np.roots(row)
            eirr = np.real(g[np.isreal(g)]) - 1
            eirr = eirr[eirr >= -1]

            if len(eirr) == 0:
                irr_results[i] = np.nan
            elif len(eirr) == 1:
                irr_results[i] = eirr[0]
            else:
                irr_results[i] = _irr_default_selection(eirr)

    return _ufunc_like(irr_results)


# =====================================================================
# Net Present Value — FIX: rate==-1 guard + native backend
# =====================================================================
def npv(rate, values):
    """Return the NPV (Net Present Value) of a cash flow series."""
    values = np.atleast_1d(np.asarray(values, dtype=np.float64))
    rate_arr = np.atleast_1d(np.asarray(rate, dtype=np.float64))

    n = values.shape[-1]

    # Use native backend for scalar rate if available
    if _npv_native is not None and (rate_arr.ndim == 0 or rate_arr.size == 1):
        r = rate_arr.item()
        c_values = (ctypes.c_double * n)(*values)
        return float(_npv_native(r, c_values, n))

    # Pure Python fallback
    timesteps = np.arange(n)

    if rate_arr.ndim == 0 or rate_arr.size == 1:
        r = rate_arr.item()
        if r == -1:
            return np.nan
        factors = (1 + r) ** timesteps
        return float(np.sum(values / factors))
    else:
        result = np.empty(rate_arr.shape)
        for j, r in enumerate(rate_arr.flat):
            if r == -1:
                result.flat[j] = np.nan
            else:
                factors = (1 + r) ** timesteps
                result.flat[j] = np.sum(values / factors)
        return _ufunc_like(result)


# =====================================================================
# Modified Internal Rate of Return — FIX: exponent 1/(n-1) not 1/n
# =====================================================================
def mirr(values, finance_rate, reinvest_rate):
    """Return the Modified Internal Rate of Return (MIRR)."""
    values = np.atleast_1d(np.asarray(values, dtype=np.float64))
    n = len(values)

    pos = values > 0
    neg = values < 0

    if not (pos.any() and neg.any()):
        return np.nan

    numer = np.abs(npv(reinvest_rate, values * pos))
    denom = np.abs(npv(finance_rate, values * neg))

    return (numer / denom) ** (1.0 / (n - 1)) * (1 + reinvest_rate) - 1


# =====================================================================
# Extended NPV (irregular dates) — NEW IMPLEMENTATION
# =====================================================================
def xnpv(rate, cashflows, dates):
    """Compute NPV for cashflows on arbitrary dates (actual/365)."""
    cashflows = np.asarray(cashflows, dtype=np.float64)
    d0 = dates[0]
    day_fracs = np.array([(d - d0).days / 365.0 for d in dates])

    r = float(rate)
    if r == -1:
        return np.nan

    return float(np.sum(cashflows / (1 + r) ** day_fracs))


# =====================================================================
# Extended IRR (irregular dates) — NEW IMPLEMENTATION
# =====================================================================
def xirr(cashflows, dates, guess=0.1, tol=1e-6, maxiter=100):
    """Compute IRR for irregular cashflows via Newton-Raphson."""
    cashflows = np.asarray(cashflows, dtype=np.float64)

    # No solution if all same sign
    if np.all(cashflows >= 0) or np.all(cashflows <= 0):
        return np.nan

    d0 = dates[0]
    day_fracs = np.array([(d - d0).days / 365.0 for d in dates])

    rate = float(guess)
    for _ in range(maxiter):
        base = (1 + rate)
        if base <= 0:
            rate = rate / 2 + 0.5
            continue

        powers = base ** day_fracs
        npv_val = np.sum(cashflows / powers)

        powers_deriv = base ** (day_fracs + 1)
        dnpv = np.sum(-day_fracs * cashflows / powers_deriv)

        if abs(dnpv) < 1e-30:
            return np.nan

        new_rate = rate - npv_val / dnpv
        if abs(new_rate - rate) < tol:
            return new_rate
        rate = new_rate

    return np.nan
