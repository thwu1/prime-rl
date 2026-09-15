"""Time Value of Money (TVM) financial computation module.

Clean-room implementation of capital budgeting and loan amortization
functions.  Uses numpy for array operations but no dedicated financial
library.
"""


import math
from decimal import Decimal

import numpy as np

# ── when parameter conversion ──────────────────────────────────────────────

_when_to_num = {
    'end': 0, 'e': 0, 'finish': 0, 0: 0,
    'begin': 1, 'b': 1, 'start': 1, 'beginning': 1, 1: 1,
}


def _convert_when(when):
    """Map ``when`` strings / ints / Decimals to numeric 0 or 1."""
    if isinstance(when, np.ndarray):
        return when
    try:
        return _when_to_num[when]
    except (KeyError, TypeError):
        return [_when_to_num[x] for x in when]


def _ufunc_like(arr):
    """Return a scalar for 0-d / single-element arrays, squeezed otherwise."""
    try:
        return arr.item()
    except ValueError:
        return arr.squeeze()


def _value_like(arr, value):
    """Return *value* cast to the same Python type as the first element of *arr*."""
    entry = arr.item(0)
    if isinstance(entry, Decimal):
        return Decimal(value)
    return np.array(value, dtype=arr.dtype).item(0)


# ── core TVM functions ─────────────────────────────────────────────────────

def fv(rate, nper, pmt, pv, when='end'):
    """Compute the future value."""
    when = _convert_when(when)
    rate, nper, pmt, pv, when = np.broadcast_arrays(
        *map(np.asarray, [rate, nper, pmt, pv, when])
    )
    fv_array = np.empty_like(rate)
    zero = rate == 0
    nonzero = ~zero

    if np.any(zero):
        fv_array[zero] = -(pv[zero] + pmt[zero] * nper[zero])
    if np.any(nonzero):
        rate_nz = rate[nonzero]
        temp = (1 + rate_nz) ** nper[nonzero]
        fv_array[nonzero] = (
            -pv[nonzero] * temp
            - pmt[nonzero] * (1 + rate_nz * when[nonzero]) / rate_nz
            * (temp - 1)
        )

    if np.ndim(fv_array) == 0:
        return fv_array.item(0)
    return fv_array


def pv(rate, nper, pmt, fv=0, when='end'):
    """Compute the present value."""
    when = _convert_when(when)
    rate, nper, pmt, fv, when = map(np.asarray, [rate, nper, pmt, fv, when])
    temp = (1 + rate) ** nper
    fact = np.where(rate == 0, nper,
                    (1 + rate * when) * (temp - 1) / rate)
    result = -(fv + pmt * fact) / temp
    return _ufunc_like(np.asarray(result))


def pmt(rate, nper, pv, fv=0, when='end'):
    """Compute the periodic payment against loan principal plus interest."""
    when = _convert_when(when)
    rate, nper, pv, fv, when = map(np.asarray, [rate, nper, pv, fv, when])
    temp = (1 + rate) ** nper
    mask = (rate == 0)
    masked_rate = np.where(mask, 1, rate)
    fact = np.where(mask, nper,
                    (1 + masked_rate * when) * (temp - 1) / masked_rate)
    result = -(fv + pv * temp) / fact
    return _ufunc_like(np.asarray(result))


def nper(rate, pmt, pv, fv=0, when='end'):
    """Compute the number of periodic payments."""
    when = _convert_when(when)
    rate_a = np.atleast_1d(np.asarray(rate, dtype=np.float64))
    pmt_a = np.atleast_1d(np.asarray(pmt, dtype=np.float64))
    pv_a = np.atleast_1d(np.asarray(pv, dtype=np.float64))
    fv_a = np.atleast_1d(np.asarray(fv, dtype=np.float64))
    when_a = np.atleast_1d(np.asarray(when, dtype=np.float64))

    rate_a, pmt_a, pv_a, fv_a, when_a = np.broadcast_arrays(
        rate_a, pmt_a, pv_a, fv_a, when_a)
    # writeable copies
    rate_a, pmt_a, pv_a, fv_a, when_a = (
        np.array(rate_a), np.array(pmt_a), np.array(pv_a),
        np.array(fv_a), np.array(when_a))

    result = np.empty_like(rate_a, dtype=np.float64)

    for idx in np.ndindex(rate_a.shape):
        r = rate_a[idx]
        p = pmt_a[idx]
        pv_v = pv_a[idx]
        fv_v = fv_a[idx]
        w = when_a[idx]

        if r == 0.0 and p == 0.0:
            result[idx] = np.inf
        elif r == 0.0:
            result[idx] = -(fv_v + pv_v) / p
        elif r <= -1.0:
            result[idx] = np.nan
        else:
            z = p * (1.0 + r * w) / r
            result[idx] = (math.log((-fv_v + z) / (pv_v + z))
                           / math.log(1.0 + r))

    return _ufunc_like(result)


# ── ipmt / ppmt ────────────────────────────────────────────────────────────

def _rbl(rate, per, pmt_val, pv, when):
    """Remaining balance on loan after *per-1* payments."""
    return fv(rate, (per - 1), pmt_val, pv, when)


def ipmt(rate, per, nper, pv, fv=0, when='end'):
    """Compute the interest portion of a payment."""
    when = _convert_when(when)
    rate, per, nper, pv, fv, when = np.broadcast_arrays(
        *map(np.asarray, [rate, per, nper, pv, fv, when]))

    total_pmt = pmt(rate, nper, pv, fv, when)
    ipmt_array = np.array(_rbl(rate, per, total_pmt, pv, when) * rate)

    # Payments before period 1 are undefined
    ipmt_array[per < 1] = _value_like(ipmt_array, np.nan)
    # Begin timing, period 1: no interest yet
    per1_begin = (when == 1) & (per == 1)
    ipmt_array[per1_begin] = _value_like(ipmt_array, 0)
    # Begin timing, period > 1: discount by one period
    pergt1_begin = (when == 1) & (per > 1)
    ipmt_array[pergt1_begin] = (
        ipmt_array[pergt1_begin] / (1 + rate[pergt1_begin]))

    if np.ndim(ipmt_array) == 0:
        return ipmt_array.item(0)
    return ipmt_array


def ppmt(rate, per, nper, pv, fv=0, when='end'):
    """Compute the payment against loan principal."""
    total = pmt(rate, nper, pv, fv, when)
    return total - ipmt(rate, per, nper, pv, fv, when)


# ── rate solver (Newton-Raphson) ───────────────────────────────────────────

def _g_div_gp(r, n, p, x, y, w):
    """Return g(r)/g'(r) for the TVM equation Newton-Raphson step."""
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
    is_decimal = isinstance(pmt, Decimal)
    default_type = Decimal if is_decimal else float

    if guess is None:
        guess = default_type('0.1')
    if tol is None:
        tol = default_type('1e-6')

    nper, pmt, pv, fv, when = map(np.asarray, [nper, pmt, pv, fv, when])

    rn = guess
    close = False
    for _ in range(maxiter):
        rnp1 = rn - _g_div_gp(rn, nper, pmt, pv, fv, when)
        diff = abs(rnp1 - rn)
        close = diff < tol
        rn = rnp1
        if np.all(close):
            break

    if not np.all(close):
        rn_arr = np.asarray(rn)
        if rn_arr.ndim == 0:
            return default_type(np.nan)
        rn_arr = rn_arr.copy().astype(float)
        rn_arr[~np.asarray(close)] = np.nan
        return rn_arr

    # Extract scalar from 0-d array if needed
    rn_arr = np.asarray(rn)
    if rn_arr.ndim == 0:
        return rn_arr.item()
    return rn_arr


# ── NPV ────────────────────────────────────────────────────────────────────

def npv(rate, values):
    """Compute the Net Present Value of a cashflow series."""
    values_a = np.atleast_1d(np.asarray(values, dtype=np.float64))
    rate_f = float(rate)

    if rate_f == -1.0:
        return float('nan')

    t = np.arange(len(values_a), dtype=np.float64)
    return float(np.sum(values_a / (1.0 + rate_f) ** t))


# ── IRR ────────────────────────────────────────────────────────────────────

def _irr_default_selection(eirr):
    """Select the most plausible IRR from multiple real polynomial roots."""
    same_sign = np.all(eirr > 0) if eirr[0] > 0 else np.all(eirr < 0)
    if not same_sign:
        pos = np.sum(eirr[eirr > 0])
        neg = np.sum(eirr[eirr < 0])
        if pos >= neg:
            eirr = eirr[eirr >= 0]
        else:
            eirr = eirr[eirr < 0]
    return eirr[np.argmin(np.abs(eirr))]


def irr(values):
    """Compute the Internal Rate of Return."""
    values_a = np.atleast_1d(np.asarray(values, dtype=np.float64))

    # All same sign → no solution
    same_sign = np.all(values_a > 0) if values_a[0] > 0 else np.all(values_a < 0)
    if same_sign:
        return float('nan')

    # Polynomial root-finding: V0*g^N + V1*g^{N-1} + ... + VN = 0
    g = np.roots(values_a)

    # Keep only real roots, convert growth factor g to rate r = g - 1
    eirr = np.real(g[np.isreal(g)]) - 1.0

    # Realistic rates: r >= -1
    eirr = eirr[eirr >= -1.0]

    if len(eirr) == 0:
        return float('nan')
    if len(eirr) == 1:
        return float(eirr[0])
    return float(_irr_default_selection(eirr))


# ── MIRR ───────────────────────────────────────────────────────────────────

def mirr(values, finance_rate, reinvest_rate):
    """Compute the Modified Internal Rate of Return."""
    values_a = np.asarray(values, dtype=np.float64)
    n = len(values_a)

    pos = values_a > 0
    neg = values_a < 0

    if not (pos.any() and neg.any()):
        return float('nan')

    numer = abs(npv(reinvest_rate, values_a * pos))
    denom = abs(npv(finance_rate, values_a * neg))

    return float(
        (numer / denom) ** (1.0 / (n - 1)) * (1.0 + float(reinvest_rate)) - 1.0
    )
