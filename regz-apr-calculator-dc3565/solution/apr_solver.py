#!/usr/bin/env python3
"""
Regulation Z Appendix J APR Calculator — Reference Implementation
Computes APR using the actuarial method for closed-end credit transactions.
"""

import json
import sys
import calendar
from datetime import date


# ---------------------------------------------------------------------------
# Date Arithmetic (Reg Z Appendix J conventions)
# ---------------------------------------------------------------------------

def parse_date(s):
    """Parse YYYY-MM-DD string to date."""
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def add_months(d, n):
    """Add n months to date d, clamping to end-of-month."""
    total_m = d.month + n
    year = d.year + (total_m - 1) // 12
    month = ((total_m - 1) % 12) + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(d.day, max_day)
    return date(year, month, day)


def subtract_months(d, n):
    """Subtract n months from date d, clamping to end-of-month."""
    total_m = d.month - n
    year = d.year
    while total_m <= 0:
        total_m += 12
        year -= 1
    month = total_m
    max_day = calendar.monthrange(year, month)[1]
    day = min(d.day, max_day)
    return date(year, month, day)


def days_between(d1, d2):
    """Number of calendar days from d1 to d2."""
    return (d2 - d1).days


def is_whole_months(d1, d2):
    """Check if interval d1->d2 is exactly a whole number of months."""
    if d1 > d2:
        return False
    n = full_months_back(d1, d2)
    target = add_months(d1, n)
    return target == d2


def full_months_back(d1, d2):
    """
    Count full months measured BACK from d2 that don't go before d1.
    Per Reg Z (b)(5)(ii).
    """
    # Upper bound on months
    months = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    # Verify: d2 minus months must be >= d1
    while months > 0:
        candidate = subtract_months(d2, months)
        if candidate >= d1:
            return months
        months -= 1
    return 0


def unit_periods_between_monthly(d1, d2):
    """
    Compute (n, f) for monthly unit-period.
    n = full months back from d2.
    f = days from d1 forward to start of first full month / 30.
    """
    n = full_months_back(d1, d2)
    # d_mid = d2 minus n months
    d_mid = subtract_months(d2, n)
    f_days = days_between(d1, d_mid)
    f = f_days / 30.0
    return (n, f)


# ---------------------------------------------------------------------------
# Payment expansion
# ---------------------------------------------------------------------------

def expand_payment_groups(groups):
    """Expand payment groups into list of (date, amount) tuples."""
    payments = []
    for g in groups:
        d = parse_date(g["first_date"])
        amt = g["amount"]
        count = g["count"]
        period = g["period_months"]
        for k in range(count):
            payments.append((d, amt))
            if k < count - 1:
                d = add_months(d, period)
    return payments


# ---------------------------------------------------------------------------
# Unit-period determination
# ---------------------------------------------------------------------------

def determine_unit_period(advances, payments, consummation):
    """
    Determine unit-period type and w (unit-periods per year).
    Returns (unit_type, w) where unit_type is 'month', 'term_whole',
    'term_nonwhole', etc.
    """
    is_single_payment = len(payments) == 1
    is_single_advance = len(advances) == 1

    if is_single_advance and is_single_payment:
        # Unit-period = term, capped at 1 year
        term_start = consummation
        term_end = payments[0][0]
        d = days_between(term_start, term_end)
        if d <= 0:
            d = 1
        if d > 365:
            # Term > 1 year, unit period = 1 year
            return ("year", 1.0)
        if is_whole_months(term_start, term_end):
            n_months = full_months_back(term_start, term_end)
            if n_months == 0:
                n_months = 1
            w = 12.0 / n_months
            return ("term_whole", w)
        else:
            w = 365.0 / d
            return ("term_nonwhole", w)

    # For multi-payment transactions: find most frequent common period
    # Collect all payment-to-payment intervals
    # For simplicity and correctness for our test cases, which are all
    # monthly, we determine the period from the payment intervals.

    all_intervals = []

    # Payment intervals
    if len(payments) > 1:
        for i in range(1, len(payments)):
            d1, d2 = payments[i - 1][0], payments[i][0]
            all_intervals.append(("payment", d1, d2))

    # Advance intervals
    sorted_advances = sorted(advances, key=lambda x: x[0])
    if len(sorted_advances) > 1:
        for i in range(1, len(sorted_advances)):
            d1, d2 = sorted_advances[i - 1][0], sorted_advances[i][0]
            all_intervals.append(("advance", d1, d2))

    # Consummation to first payment
    if payments:
        first_pay = min(p[0] for p in payments)
        if first_pay > consummation:
            all_intervals.append(("first_period", consummation, first_pay))

    # Consummation to first advance
    if advances:
        first_adv = min(a[0] for a in advances)
        if first_adv > consummation:
            all_intervals.append(("first_adv_period", consummation, first_adv))

    # Categorize each interval into standard intervals
    period_counts = {}  # standard_interval -> count

    for _, d1, d2 in all_intervals:
        std = categorize_interval(d1, d2)
        if std is not None:
            period_counts[std] = period_counts.get(std, 0) + 1

    if not period_counts:
        # Default to monthly
        return ("month", 12.0)

    # Find common periods (count > 1)
    common = {k: v for k, v in period_counts.items() if v > 1}

    if common:
        # Most frequent; ties go to smaller
        max_count = max(common.values())
        candidates = [k for k, v in common.items() if v == max_count]
        # Sort by size (smaller first)
        candidates.sort(key=lambda x: standard_interval_days(x))
        chosen = candidates[0]
    else:
        # No common period — average of all, round to nearest standard
        all_days = []
        for _, d1, d2 in all_intervals:
            all_days.append(days_between(d1, d2))
        avg = sum(all_days) / len(all_days) if all_days else 30
        chosen = nearest_standard_interval(avg)

    return (chosen, standard_interval_w(chosen))


def categorize_interval(d1, d2):
    """Categorize a date interval into a standard interval name."""
    d = days_between(d1, d2)
    if d <= 0:
        return None

    # Check if it's a whole number of months
    if is_whole_months(d1, d2):
        n = full_months_back(d1, d2)
        if n == 1:
            return "month"
        elif n <= 11:
            return f"{n}month"
        elif n == 12:
            return "year"
        else:
            return None  # > 1 year
    # Check weeks
    if d % 7 == 0:
        weeks = d // 7
        if weeks == 1:
            return "week"
        elif weeks == 2:
            return "2week"
        elif weeks <= 52:
            return f"{weeks}week"
    # Check semimonth (~15 days)
    if 14 <= d <= 16:
        return "semimonth"
    # Check day
    if d == 1:
        return "day"
    # Non-standard
    return f"days_{d}"


def standard_interval_days(name):
    """Approximate days for sorting standard intervals."""
    if name == "day":
        return 1
    if name == "week":
        return 7
    if name == "semimonth":
        return 15
    if name == "month":
        return 30
    if name == "year":
        return 365
    if name.endswith("week"):
        n = int(name.replace("week", ""))
        return n * 7
    if name.endswith("month"):
        n = int(name.replace("month", ""))
        return n * 30
    if name.startswith("days_"):
        return int(name.split("_")[1])
    return 30


def standard_interval_w(name):
    """Unit-periods per year for a standard interval."""
    if name == "day":
        return 365.0
    if name == "week":
        return 52.0
    if name == "semimonth":
        return 24.0
    if name == "month":
        return 12.0
    if name == "year":
        return 1.0
    if name.endswith("week"):
        n = int(name.replace("week", ""))
        return 52.0 / n
    if name.endswith("month"):
        n = int(name.replace("month", ""))
        return 12.0 / n
    return 12.0  # fallback


def nearest_standard_interval(avg_days):
    """Round average days to nearest standard interval."""
    standards = [
        ("day", 1),
        ("week", 7),
        ("semimonth", 15),
        ("month", 30),
        ("2month", 60),
        ("3month", 90),
        ("4month", 120),
        ("6month", 180),
        ("year", 365),
    ]
    best = None
    best_diff = float("inf")
    for name, days in standards:
        diff = abs(avg_days - days)
        if diff < best_diff or (diff == best_diff and days < standard_interval_days(best)):
            best = name
            best_diff = diff
    return best


# ---------------------------------------------------------------------------
# Time position computation
# ---------------------------------------------------------------------------

def compute_time_position(zero_point, target, unit_type):
    """
    Compute (n, f) — the time position of `target` relative to `zero_point`
    in the given unit-period type. n = full unit-periods, f = fraction.
    """
    if target == zero_point:
        return (0, 0.0)

    if target < zero_point:
        # Negative time — shouldn't happen with correct zero point
        return (0, 0.0)

    if unit_type in ("month",):
        return unit_periods_between_monthly(zero_point, target)

    if unit_type.startswith("term_"):
        # Single advance, single payment: position is either 0 or 1
        # The advance is at 0, the payment is at 1
        return (1, 0.0)

    if unit_type.endswith("month") and unit_type != "month":
        # Multi-month unit period
        n_months_per_unit = int(unit_type.replace("month", ""))
        # Convert to 30-day-month system
        n_full_months = full_months_back(zero_point, target)
        d_mid = subtract_months(target, n_full_months)
        remaining_days = days_between(zero_point, d_mid)
        total_30day = 30 * n_full_months + remaining_days
        days_per_unit = 30 * n_months_per_unit
        n = total_30day // days_per_unit
        f = (total_30day % days_per_unit) / days_per_unit
        return (n, f)

    if unit_type in ("week",) or (unit_type.endswith("week") and unit_type != "week"):
        d = days_between(zero_point, target)
        if unit_type == "week":
            dpup = 7
        else:
            dpup = int(unit_type.replace("week", "")) * 7
        n = d // dpup
        f = (d % dpup) / dpup
        return (n, f)

    if unit_type == "day":
        d = days_between(zero_point, target)
        return (d, 0.0)

    if unit_type == "semimonth":
        n_full_months = full_months_back(zero_point, target)
        d_mid = subtract_months(target, n_full_months)
        remaining_days = days_between(zero_point, d_mid)
        total_30day = 30 * n_full_months + remaining_days
        n = total_30day // 15
        f = (total_30day % 15) / 15.0
        return (n, f)

    if unit_type == "year":
        # Full years (12 months each) back from target
        years = 0
        while True:
            test = subtract_months(target, (years + 1) * 12)
            if test < zero_point:
                break
            years += 1
        d_mid = subtract_months(target, years * 12)
        remaining_months = full_months_back(zero_point, d_mid)
        if add_months(zero_point, remaining_months) == d_mid:
            f = remaining_months / 12.0
        else:
            f = days_between(zero_point, d_mid) / 365.0
        return (years, f)

    # Fallback: treat as monthly
    return unit_periods_between_monthly(zero_point, target)


# ---------------------------------------------------------------------------
# Discount factor and derivatives
# ---------------------------------------------------------------------------

def discount_factor(n, f, i):
    """DF(n, f, i) = 1 / ((1 + f*i) * (1+i)^n)"""
    if n == 0 and f == 0.0:
        return 1.0
    denom = (1.0 + f * i) * ((1.0 + i) ** n)
    if denom == 0:
        return 0.0
    return 1.0 / denom


def d_discount_factor(n, f, i):
    """Derivative of DF with respect to i."""
    df = discount_factor(n, f, i)
    if df == 0:
        return 0.0
    t1 = f / (1.0 + f * i) if (1.0 + f * i) != 0 else 0.0
    t2 = n / (1.0 + i) if (1.0 + i) != 0 else 0.0
    return -df * (t1 + t2)


# ---------------------------------------------------------------------------
# Equation F(i) and F'(i)
# ---------------------------------------------------------------------------

def equation_value(i, adv_pos, pay_pos):
    """F(i) = PV(advances) - PV(payments). Should be 0 at correct i."""
    pv_adv = sum(amt * discount_factor(n, f, i) for amt, n, f in adv_pos)
    pv_pay = sum(amt * discount_factor(n, f, i) for amt, n, f in pay_pos)
    return pv_adv - pv_pay


def equation_deriv(i, adv_pos, pay_pos):
    """F'(i) = d/di [PV(advances) - PV(payments)]."""
    d_adv = sum(amt * d_discount_factor(n, f, i) for amt, n, f in adv_pos)
    d_pay = sum(amt * d_discount_factor(n, f, i) for amt, n, f in pay_pos)
    return d_adv - d_pay


# ---------------------------------------------------------------------------
# Root-finding solver
# ---------------------------------------------------------------------------

def solve_for_rate(adv_pos, pay_pos):
    """
    Find unit-period rate i such that F(i) = 0.
    Uses bisection to bracket, then Newton-Raphson to refine.
    """
    def f(i):
        return equation_value(i, adv_pos, pay_pos)

    def fp(i):
        return equation_deriv(i, adv_pos, pay_pos)

    # Check for trivial cases
    total_adv = sum(a for a, _, _ in adv_pos)
    total_pay = sum(p for p, _, _ in pay_pos)
    if abs(total_adv - total_pay) < 1e-10:
        return 0.0

    # Check for direct solution (single advance at 0, single payment)
    if len(adv_pos) == 1 and len(pay_pos) == 1:
        a_amt, a_n, a_f = adv_pos[0]
        p_amt, p_n, p_f = pay_pos[0]
        if a_n == 0 and a_f == 0 and p_n == 1 and p_f == 0 and a_amt > 0:
            return p_amt / a_amt - 1.0

    # Bisection phase: find bracket [lo, hi] where f changes sign
    lo = 1e-10
    f_lo = f(lo)

    hi = None
    for trial in [0.0005, 0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2,
                  0.5, 1.0, 2.0, 5.0, 10.0]:
        try:
            f_trial = f(trial)
        except (OverflowError, ZeroDivisionError):
            continue
        if f_lo * f_trial < 0:
            hi = trial
            break

    if hi is None:
        # Can't bracket — try Newton-Raphson from a guess
        i = 0.01
    else:
        # Bisect to narrow bracket
        for _ in range(80):
            mid = (lo + hi) / 2.0
            try:
                f_mid = f(mid)
            except (OverflowError, ZeroDivisionError):
                hi = mid
                continue
            if f_lo * f_mid <= 0:
                hi = mid
            else:
                lo = mid
                f_lo = f_mid
        i = (lo + hi) / 2.0

    # Newton-Raphson refinement
    for _ in range(200):
        try:
            fval = f(i)
            fpval = fp(i)
        except (OverflowError, ZeroDivisionError):
            break
        if abs(fpval) < 1e-30:
            break
        step = fval / fpval
        i_new = i - step
        if i_new <= 0:
            i_new = i / 2.0
        if abs(i_new - i) < 1e-14:
            break
        i = i_new

    return i


# ---------------------------------------------------------------------------
# Transaction classification
# ---------------------------------------------------------------------------

def classify_transaction(advances, payments):
    """
    Classify as 'regular' or 'irregular' per Section 1026.22(a)(3).
    Irregular if: multiple advances, irregular payment periods (excluding
    odd first period), or irregular payment amounts (excluding odd first/
    final payment).
    """
    # Multiple advances → irregular
    if len(advances) > 1:
        return "irregular"

    if len(payments) <= 1:
        return "regular"

    # Check payment-to-payment periods using standard interval categories
    # (not raw days, since months have different numbers of days)
    dates = [p[0] for p in payments]
    if len(dates) >= 3:
        interval_cats = []
        for j in range(1, len(dates)):
            cat = categorize_interval(dates[j - 1], dates[j])
            interval_cats.append(cat)
        # All payment-to-payment intervals should be the same standard interval
        if len(set(interval_cats)) > 1:
            return "irregular"

    # Check payment amounts (excluding first and last)
    amounts = [p[1] for p in payments]
    if len(amounts) > 2:
        middle = amounts[1:-1]
        if len(set(round(a, 2) for a in middle)) > 1:
            return "irregular"

    return "regular"


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process_loan(filepath):
    """Process a loan JSON file and return the result dict."""
    with open(filepath) as fh:
        loan = json.load(fh)

    loan_id = loan["id"]
    consummation = parse_date(loan["consummation_date"])
    is_mortgage = loan.get("is_mortgage", False)
    disclosed_apr = loan.get("disclosed_apr")

    # Parse advances
    advances = [(parse_date(a["date"]), a["amount"]) for a in loan["advances"]]

    # Expand payments
    payments = expand_payment_groups(loan["payment_groups"])

    # Determine zero point (earliest of consummation, first payment, first advance)
    all_dates = [consummation] + [a[0] for a in advances] + [p[0] for p in payments]
    zero_point = min(all_dates)

    # Determine unit-period type and w
    unit_type, w = determine_unit_period(advances, payments, consummation)

    # Compute time positions for each cash flow
    adv_pos = []  # (amount, n, f)
    for d, amt in advances:
        n, f = compute_time_position(zero_point, d, unit_type)
        adv_pos.append((amt, n, f))

    pay_pos = []  # (amount, n, f)
    for d, amt in payments:
        n, f = compute_time_position(zero_point, d, unit_type)
        pay_pos.append((amt, n, f))

    # Solve for unit-period rate
    i = solve_for_rate(adv_pos, pay_pos)

    # Compute APR
    computed_apr = round(i * w * 100.0, 2)

    # Classify transaction
    txn_type = classify_transaction(advances, payments)

    # Determine tolerance
    if txn_type == "irregular":
        tolerance = 0.25
    else:
        tolerance = 0.125

    # Check tolerance
    if disclosed_apr is not None:
        within = abs(computed_apr - disclosed_apr) <= tolerance
    else:
        within = None

    return {
        "id": loan_id,
        "computed_apr": computed_apr,
        "transaction_type": txn_type,
        "tolerance_pct": tolerance,
        "disclosed_apr": disclosed_apr,
        "within_tolerance": within,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: regz_apr <loan_file.json>", file=sys.stderr)
        sys.exit(1)
    result = process_loan(sys.argv[1])
    print(json.dumps(result))
