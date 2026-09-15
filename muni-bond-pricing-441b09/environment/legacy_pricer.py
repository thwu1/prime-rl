"""
Legacy municipal bond pricing library.

WARNING: This module is known to have defects and is provided for
reference only. Do NOT use it for production calculations.

Internal review notes:
  - Several calculation discrepancies reported by compliance team
  - Issues traced to day-count, precision, and call-schedule handling
  - Scheduled for replacement
"""

import math
from datetime import date, timedelta


def _last_day(year, month):
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def _add_months(d, months):
    m = d.month + months
    y = d.year
    while m > 12:
        m -= 12
        y += 1
    while m <= 0:
        m += 12
        y -= 1
    day = min(d.day, _last_day(y, m))
    return date(y, m, day)


def days_30_360(d1, d2):
    """30/360 day count -- NOTE: see compliance review notes."""
    y1, m1, dd1 = d1.year, d1.month, d1.day
    y2, m2, dd2 = d2.year, d2.month, d2.day

    if dd1 == 31:
        dd1 = 30
    # BUG: D2 adjustment does not check whether adjusted D1 >= 30
    if dd2 == 31:
        dd2 = 30
    return (y2 - y1) * 360 + (m2 - m1) * 30 + (dd2 - dd1)


def format_price(raw):
    """Format dollar price -- NOTE: review pending."""
    # BUG: rounds to 3 dp instead of truncating
    return round(raw, 3)


def format_yield(raw):
    """Format yield value."""
    # BUG: truncates directly to 3 dp, skipping the 4-dp intermediate step
    factor = 10 ** 3
    return math.floor(raw * factor) / factor


def format_ai(raw):
    """Format accrued interest."""
    # truncate to 3 then round to 2
    t3 = math.floor(raw * 1000) / 1000
    return round(t3 + 0.00001, 2)  # crude rounding


def price_at_redemption(RV, R, Y, DIR, DSM, B=360):
    P = (RV + R * 100 * DIR / B) / (1 + Y * DSM / B)
    return format_price(P)


def price_periodic(RV, R, M, Y, N, A, E):
    """Compute periodic bond price. Does NOT handle call schedules."""
    C = (R / M) * 100
    if N <= 1:
        DSC = E - A
        P = (RV + C) / (1 + DSC / E * Y / M) - (A / E) * C
    else:
        y = Y / M
        w = (E - A) / E
        base = 1 + y
        pv_rv = RV / (base ** (N - 1 + w))
        pv_c = sum(C / (base ** (k - 1 + w)) for k in range(1, N + 1))
        P = pv_rv + pv_c - (A / E) * C
    return format_price(P)


def price_discounted(RV, DR, DSM, B=360):
    P = RV * (1 - DR * DSM / B)
    return format_price(P)


def roi_discounted(RV, P, DSM, B=360):
    if DSM == 0 or P == 0:
        return 0.0
    return format_yield(((RV - P) / P) * (B / DSM))
