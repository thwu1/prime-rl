
"""
Section 121 Property Sale Gain Exclusion Calculator

Implements the IRC Section 121 exclusion computation for gain from the
sale of a principal residence, based on the Catala formalization.

Handles single returns, joint returns (conditions A and B), and
surviving spouse returns (section 121(b)(4)).
"""

from datetime import date


def _parse_date(s):
    """Parse an ISO date string (YYYY-MM-DD) into a date object."""
    parts = s.split("-")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def _add_years(d, n):
    """Add n calendar years to a date, handling Feb 29 gracefully."""
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        # Feb 29 in a non-leap target year → use Feb 28
        return d.replace(year=d.year + n, day=28)


def _aggregate_periods(periods, sale_date):
    """
    Compute aggregate days of ownership/usage within the 5-year lookback window.

    Implements the Catala aggregate_periods_from_last_five_years algorithm:
    For each period:
      - If sale_date <= begin + 5 years: count full period (end - begin)
      - If sale_date >= end + 5 years: count 0 (entirely outside window)
      - Otherwise: count (end + 5 years - sale_date) days (partial overlap)
    """
    total = 0
    for p in periods:
        begin = _parse_date(p["begin"])
        end = _parse_date(p["end"])
        begin_plus_5 = _add_years(begin, 5)
        end_plus_5 = _add_years(end, 5)

        if sale_date <= begin_plus_5:
            # Entire period falls within the 5-year window
            total += (end - begin).days
        elif sale_date >= end_plus_5:
            # Entire period is before the 5-year window
            pass
        else:
            # The 5-year boundary cuts through the period
            total += (end_plus_5 - sale_date).days

    return total


def _check_b3(sale_date, prior_sale_date):
    """
    Check if Section 121(b)(3) applies.

    Returns True if there was a prior §121(a) sale within 730 days,
    which blocks the current exclusion.
    """
    if prior_sale_date is None:
        return False
    prior = _parse_date(prior_sale_date)
    return (sale_date - prior).days <= 730


def _check_person_requirements(person, sale_date):
    """Check ownership and usage requirements for one person at a given date."""
    ownership_days = _aggregate_periods(person["ownership_periods"], sale_date)
    usage_days = _aggregate_periods(person["usage_periods"], sale_date)
    return ownership_days >= 730, usage_days >= 730


def _merge_periods(periods1, periods2):
    """
    Merge two lists of date periods into a non-overlapping union.

    Used for joint return condition (B): each spouse is treated as owning
    the property during any period that either spouse owned it.
    """
    all_intervals = []
    for p in periods1:
        all_intervals.append((_parse_date(p["begin"]), _parse_date(p["end"])))
    for p in periods2:
        all_intervals.append((_parse_date(p["begin"]), _parse_date(p["end"])))

    if not all_intervals:
        return []

    all_intervals.sort()
    merged = [all_intervals[0]]
    for begin, end in all_intervals[1:]:
        if begin <= merged[-1][1]:
            # Overlapping or adjacent → extend
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((begin, end))

    return [{"begin": str(b), "end": str(e)} for b, e in merged]


def _compute_single(person, sale_date, gain):
    """Compute exclusion for a single return under §121."""
    ownership_met, usage_met = _check_person_requirements(person, sale_date)
    requirements_met = ownership_met and usage_met
    b3 = _check_b3(sale_date, person.get("prior_sale_date"))

    gain_cap = 250000

    if requirements_met and not b3:
        excluded = min(gain, gain_cap)
    else:
        excluded = 0

    return {"excluded_amount": excluded, "gain_cap": gain_cap}


def _check_condition_a(person1, person2, sale_date):
    """
    Check joint return condition (A) of §121(b)(2).

    Returns True if:
      (i)   either spouse meets ownership >= 730 days
      (ii)  both spouses meet usage >= 730 days
      (iii) neither spouse is blocked by §121(b)(3)
    """
    p1_own, p1_use = _check_person_requirements(person1, sale_date)
    p2_own, p2_use = _check_person_requirements(person2, sale_date)
    p1_b3 = _check_b3(sale_date, person1.get("prior_sale_date"))
    p2_b3 = _check_b3(sale_date, person2.get("prior_sale_date"))

    return (
        (p1_own or p2_own)
        and (p1_use and p2_use)
        and (not p1_b3 and not p2_b3)
    )


def _compute_joint(person1, person2, sale_date, gain):
    """Compute exclusion for a joint return under §121(b)(2)."""

    # Check condition (A): $500,000 cap
    if _check_condition_a(person1, person2, sale_date):
        gain_cap = 500000
        excluded = min(gain, gain_cap)
        return {"excluded_amount": excluded, "gain_cap": gain_cap}

    # Condition (B): merge ownership, compute individual entitlements
    merged_ownership = _merge_periods(
        person1["ownership_periods"], person2["ownership_periods"]
    )

    # Person 1 with merged ownership
    p1_merged = dict(person1)
    p1_merged["ownership_periods"] = merged_ownership
    p1_own, p1_use = _check_person_requirements(p1_merged, sale_date)
    p1_b3 = _check_b3(sale_date, person1.get("prior_sale_date"))
    p1_entitled = p1_own and p1_use and not p1_b3

    # Person 2 with merged ownership
    p2_merged = dict(person2)
    p2_merged["ownership_periods"] = merged_ownership
    p2_own, p2_use = _check_person_requirements(p2_merged, sale_date)
    p2_b3 = _check_b3(sale_date, person2.get("prior_sale_date"))
    p2_entitled = p2_own and p2_use and not p2_b3

    # Cap = sum of $250k for each entitled spouse
    gain_cap = (250000 if p1_entitled else 0) + (250000 if p2_entitled else 0)

    if p1_entitled or p2_entitled:
        excluded = min(gain, gain_cap)
    else:
        excluded = 0

    return {"excluded_amount": excluded, "gain_cap": gain_cap}


def _compute_surviving_spouse(
    survivor, deceased_at_death, date_of_death_str, sale_date, gain
):
    """
    Compute exclusion for a surviving spouse under §121(b)(4).

    If the sale is within 2 calendar years of the spouse's death and
    condition (A) was met immediately before death, cap = $500,000.
    Otherwise fall back to single-person treatment.
    """
    death_date = _parse_date(date_of_death_str)

    # Sale must be after death and within 2 calendar years
    within_2_years = death_date < sale_date and sale_date <= _add_years(
        death_date, 2
    )

    if within_2_years:
        # Check if (A) would have been met at time of death
        condition_a_at_death = _check_condition_a(
            survivor, deceased_at_death, death_date
        )

        if condition_a_at_death:
            # Survivor gets $500k cap but must still meet requirements at sale
            own_met, use_met = _check_person_requirements(survivor, sale_date)
            b3 = _check_b3(sale_date, survivor.get("prior_sale_date"))

            gain_cap = 500000
            if own_met and use_met and not b3:
                excluded = min(gain, gain_cap)
            else:
                excluded = 0

            return {"excluded_amount": excluded, "gain_cap": gain_cap}

    # Default: treat as single return with survivor's data
    return _compute_single(survivor, sale_date, gain)


def compute_exclusion(scenario):
    """
    Compute the Section 121 gain exclusion for a property sale.

    Args:
        scenario: dict with date_of_sale, gain, return_type, and
                  person data appropriate to the return type.

    Returns:
        dict with excluded_amount (int) and gain_cap (int) in dollars.
    """
    sale_date = _parse_date(scenario["date_of_sale"])
    gain = scenario["gain"]
    return_type = scenario["return_type"]

    if return_type == "single":
        return _compute_single(scenario["person"], sale_date, gain)
    elif return_type == "joint":
        return _compute_joint(
            scenario["person1"], scenario["person2"], sale_date, gain
        )
    elif return_type == "surviving_spouse":
        return _compute_surviving_spouse(
            scenario["survivor"],
            scenario["deceased_at_death"],
            scenario["date_of_death"],
            sale_date,
            gain,
        )
    else:
        raise ValueError(f"Unknown return_type: {return_type}")
