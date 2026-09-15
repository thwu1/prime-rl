"""
Time Value of Money (TVM) financial computation library.

Pure-Python implementation for capital budgeting, loan amortization,
and investment analysis. Supports numpy broadcasting and decimal.Decimal
for arbitrary-precision calculations.

Includes optional native C accelerator for NPV computation.
Build with: make -C /app/native
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
    lib_path = os.path.join(native_dir, 'discount.dylib')
    try:
        _native_lib = ctypes.CDLL(lib_path)
        _npv_native = _native_lib.npv_native
        _npv_native.argtypes = [
            ctypes.c_float,
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
        ]
        _npv_native.restype = ctypes.c_float
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
        if value != value:  # NaN check
            return Decimal('nan')
        return Decimal(value)
    return np.array(value, dtype=arr.dtype).item(0)


# =====================================================================
# Future Value
# =====================================================================
def fv(rate, nper, pmt, pv, when='end'):
    """Compute the future value.

    Parameters
    ----------
    rate : scalar or array_like
        Rate of interest per period
    nper : scalar or array_like
        Number of compounding periods
    pmt : scalar or array_like
        Payment
    pv : scalar or array_like
        Present value
    when : {'begin', 1, 'end', 0}, optional
        When payments are due (default: 'end')
    """
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
    """Compute the number of periodic payments.

    Decimal type is not supported.
    """
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
# Interest Portion of Payment
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

    # Payments before period 1 are invalid
    ipmt_array[per < 1] = _value_like(ipmt_array, np.nan)

    # Begin timing, period 1: no interest accrued yet
    per1_and_begin = (when == 1) & (per == 1)
    ipmt_array[per1_and_begin] = _value_like(ipmt_array, 0)

    # Begin timing, per > 1: discount by one period
    per_gt_1_and_begin = (when == 1) & (per > 1)
    ipmt_array[per_gt_1_and_begin] = (
        ipmt_array[per_gt_1_and_begin] / (1 + rate[per_gt_1_and_begin]) ** 2
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
# Rate (Newton-Raphson solver)
# =====================================================================
def _g_div_gp(r, n, p, x, y, w):
    """Compute g(r)/g'(r) for Newton-Raphson iteration."""
    t1 = (r + 1) ** n
    t2 = (r + 1) ** (n - 1)
    g = y + t1 * x + p * (t1 - 1) * (r * w + 1) / r
    gp = (n * t2 * x
          - p * (t1 - 1) * (r * w + 1) / (r ** 2)
          + n * p * t2 * (r * w + 1) / r
          + p * (t1 - 1) * w / r)
    return g / gp


def rate(nper, pmt, pv, fv, when='end', guess=0.1, tol=1e-6, maxiter=100):
    """Compute the rate of interest per period via Newton-Raphson."""
    when = _convert_when(when)
    default_type = Decimal if isinstance(pmt, Decimal) else float

    if isinstance(guess, str):
        guess = default_type(guess)
    if isinstance(tol, str):
        tol = default_type(tol)

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
# Internal Rate of Return
# =====================================================================
def _irr_default_selection(eirr):
    """Select IRR from multiple real solutions.

    When a cashflow polynomial has multiple real roots >= -1,
    this heuristic selects the most financially meaningful one.
    """
    same_sign = np.all(eirr > 0) if eirr[0] > 0 else np.all(eirr < 0)

    if not same_sign:
        pos = sum(eirr[eirr > 0])
        neg = sum(eirr[eirr < 0])
        if pos >= neg:
            eirr = eirr[eirr >= 0]
        else:
            eirr = eirr[eirr < 0]

    abs_eirr = np.abs(eirr)
    return eirr[np.argmax(abs_eirr)]


def irr(values):
    """Return the Internal Rate of Return (IRR).

    Finds the rate of return such that the net present value of
    the cashflow series equals zero. Uses polynomial root-finding.

    Decimal type is not supported.
    """
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
# Net Present Value
# =====================================================================
def npv(rate, values):
    """Return the NPV (Net Present Value) of a cash flow series.

    NPV = sum(values[t] / (1 + rate)^t, t=0..N-1)

    Uses the native C backend when available for scalar rates.
    """
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
        factors = (1 + r) ** timesteps
        return float(np.sum(values / factors))
    else:
        result = np.empty(rate_arr.shape)
        for j, r in enumerate(rate_arr.flat):
            factors = (1 + r) ** timesteps
            result.flat[j] = np.sum(values / factors)
        return _ufunc_like(result)


# =====================================================================
# Modified Internal Rate of Return
# =====================================================================
def mirr(values, finance_rate, reinvest_rate):
    """Return the Modified Internal Rate of Return (MIRR).

    MIRR considers both the cost of investment and the return
    on reinvested cash flows.
    """
    values = np.atleast_1d(np.asarray(values, dtype=np.float64))
    n = len(values)

    pos = values > 0
    neg = values < 0

    if not (pos.any() and neg.any()):
        return np.nan

    numer = np.abs(npv(reinvest_rate, values * pos))
    denom = np.abs(npv(finance_rate, values * neg))

    return (numer / denom) ** (1.0 / n) * (1 + reinvest_rate) - 1


# =====================================================================
# Extended NPV (irregular dates)
# =====================================================================
def xnpv(rate, cashflows, dates):
    """Compute NPV for cashflows occurring on arbitrary dates.

    Uses actual/365 day-count convention:
        xnpv = sum(cf_i / (1 + rate) ^ ((date_i - date_0).days / 365))

    Parameters
    ----------
    rate : float
        Annual discount rate
    cashflows : array_like
        Cash flow amounts
    dates : list of datetime.date
        Dates corresponding to each cash flow

    Returns
    -------
    float : Net present value
    """
    raise NotImplementedError("xnpv is not yet implemented")


# =====================================================================
# Extended IRR (irregular dates)
# =====================================================================
def xirr(cashflows, dates, guess=0.1, tol=1e-6, maxiter=100):
    """Compute IRR for cashflows occurring on arbitrary dates.

    Finds the annual rate r such that xnpv(r, cashflows, dates) = 0.

    Parameters
    ----------
    cashflows : array_like
        Cash flow amounts (must contain both positive and negative values)
    dates : list of datetime.date
        Dates corresponding to each cash flow
    guess : float, optional
        Initial rate estimate (default: 0.1)
    tol : float, optional
        Convergence tolerance (default: 1e-6)
    maxiter : int, optional
        Maximum iterations (default: 100)

    Returns
    -------
    float : Internal rate of return, or NaN if no solution found
    """
    raise NotImplementedError("xirr is not yet implemented")
