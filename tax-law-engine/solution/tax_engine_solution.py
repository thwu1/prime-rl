"""IRC Section 121 computation engine — reference solution.

"""

from datetime import date
from typing import List, Optional

from interface import (
    ExclusionResult,
    Period,
    PersonalData,
    ReducedExclusionReason,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _window_start(sale_date: date) -> date:
    """Start of the 5-year lookback window (calendar-year subtraction)."""
    return date(sale_date.year - 5, sale_date.month, sale_date.day)


def _aggregate_days(periods: List[Period], sale_date: date) -> int:
    """Sum the days of each period that fall within the 5-year window
    ending on *sale_date*.  Only the overlapping portion counts."""
    ws = _window_start(sale_date)
    total = 0
    for p in periods:
        start = max(ws, p.begin)
        end = min(sale_date, p.end)
        if start < end:
            total += (end - start).days
    return total


def _total_period_days(periods: List[Period]) -> int:
    """Sum the total days across all periods (no clipping)."""
    return sum((p.end - p.begin).days for p in periods)


def _ownership_met(person: PersonalData, sale_date: date) -> bool:
    return _aggregate_days(person.property_ownage, sale_date) >= 730


def _usage_met(person: PersonalData, sale_date: date) -> bool:
    return _aggregate_days(
        person.property_usage_as_principal_residence, sale_date
    ) >= 730


def _b3_applies(person: PersonalData, sale_date: date) -> bool:
    """True if a prior §121(a) sale occurred within 730 days."""
    if person.most_recent_prior_121a_sale_date is None:
        return False
    return (sale_date - person.most_recent_prior_121a_sale_date).days <= 730


def _1031_blocked(sale_date: date, person: PersonalData) -> bool:
    """True if property was acquired via §1031 exchange and sale is within
    5 years of acquisition date per §121(d)(10)."""
    if not person.acquired_via_1031_exchange or person.date_of_1031_acquisition is None:
        return False
    acq = person.date_of_1031_acquisition
    try:
        boundary = date(acq.year + 5, acq.month, acq.day)
    except ValueError:
        # Feb 29 edge case
        boundary = date(acq.year + 5, 3, 1)
    return sale_date < boundary


def _merge_periods(
    periods1: List[Period], periods2: List[Period]
) -> List[Period]:
    """Merge two lists of periods into a non-overlapping sorted list
    covering the union of both inputs."""
    all_p = sorted(periods1 + periods2, key=lambda x: x.begin)
    if not all_p:
        return []
    merged = [Period(all_p[0].begin, all_p[0].end)]
    for p in all_p[1:]:
        if p.begin <= merged[-1].end:
            if p.end > merged[-1].end:
                merged[-1] = Period(merged[-1].begin, p.end)
        else:
            merged.append(Period(p.begin, p.end))
    return merged


def _first_use_date(person: PersonalData) -> Optional[date]:
    """Earliest begin date among usage periods."""
    if not person.property_usage_as_principal_residence:
        return None
    return min(p.begin for p in person.property_usage_as_principal_residence)


def _last_use_date(person: PersonalData) -> Optional[date]:
    """Latest end date among usage periods (exclusive boundary)."""
    if not person.property_usage_as_principal_residence:
        return None
    return max(p.end for p in person.property_usage_as_principal_residence)


def _effective_nq_days(person: PersonalData, sale_date: date) -> int:
    """Compute effective non-qualified use days, excluding:
    1. Periods before the property's first use as principal residence
    2. Periods after the property's last use as principal residence
    """
    first_use = _first_use_date(person)
    last_use = _last_use_date(person)
    if first_use is None:
        return 0

    ws = _window_start(sale_date)

    # Post-last-use exclusion zone: [max(last_use, ws), sale_date)
    if last_use is not None:
        excl_zone_start = max(last_use, ws)
        excl_zone_end = sale_date
        has_excl_zone = excl_zone_start < excl_zone_end
    else:
        has_excl_zone = False
        excl_zone_start = excl_zone_end = None

    total = 0
    for p in person.non_qualified_use_periods:
        # Rule 1: clip to [first_use, ...) — exclude pre-first-use
        start = max(p.begin, first_use)
        end = p.end
        if start >= end:
            continue

        # Rule 2: subtract overlap with post-last-use exclusion zone
        if has_excl_zone:
            ovlp_start = max(start, excl_zone_start)
            ovlp_end = min(end, excl_zone_end)
            if ovlp_start < ovlp_end:
                period_days = (end - start).days
                overlap_days = (ovlp_end - ovlp_start).days
                total += period_days - overlap_days
            else:
                total += (end - start).days
        else:
            total += (end - start).days

    return total


def _nq_ratio(person: PersonalData, sale_date: date) -> float:
    """Non-qualified use ratio = effective_nq_days / total_ownership_days."""
    total_own = _total_period_days(person.property_ownage)
    if total_own <= 0:
        return 0.0
    eff_nq = _effective_nq_days(person, sale_date)
    return eff_nq / total_own


def _reduced_cap(
    base_cap: float, person: PersonalData, sale_date: date
) -> float:
    """§121(c): prorated cap when §121(a) not met but qualifying reason
    exists.  Returns 0 if no qualifying reason."""
    if person.reduced_exclusion_reason == ReducedExclusionReason.NONE:
        return 0.0
    own_days = _aggregate_days(person.property_ownage, sale_date)
    use_days = _aggregate_days(
        person.property_usage_as_principal_residence, sale_date
    )
    shorter = min(own_days, use_days)
    return base_cap * shorter / 730


def _person_cap(
    person: PersonalData, sale_date: date, base_cap: float = 250_000.0
) -> float:
    """Determine the exclusion cap for a single person.

    1. If blocked by §121(d)(10) → 0
    2. If blocked by §121(b)(3) → 0
    3. If meets §121(a) → base_cap
    4. If §121(c) applies → prorated base_cap
    5. Otherwise → 0
    """
    if _1031_blocked(sale_date, person):
        return 0.0
    if _b3_applies(person, sale_date):
        return 0.0
    if _ownership_met(person, sale_date) and _usage_met(person, sale_date):
        return base_cap
    return _reduced_cap(base_cap, person, sale_date)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_exclusion(
    date_of_sale: date,
    gain: float,
    return_type: str,
    person1: PersonalData,
    person2: Optional[PersonalData] = None,
    date_of_spouse_death: Optional[date] = None,
) -> ExclusionResult:
    if gain <= 0:
        return ExclusionResult(0.0, 0.0, 0.0)

    # --- NQ ratio and depreciation (property-level, from person1) ---
    nq_r = _nq_ratio(person1, date_of_sale)
    depr = person1.depreciation_allowed

    # §121(b)(5)(D): depreciation first, then NQ allocation
    eligible = (gain - depr) * (1.0 - nq_r)
    eligible = max(0.0, eligible)

    # --- Determine cap based on return type ---
    if return_type == "single":
        cap = _person_cap(person1, date_of_sale)

    elif return_type == "joint":
        # Check §121(b)(2)(A)
        p1_own = _ownership_met(person1, date_of_sale)
        p2_own = _ownership_met(person2, date_of_sale)
        p1_use = _usage_met(person1, date_of_sale)
        p2_use = _usage_met(person2, date_of_sale)
        p1_b3 = _b3_applies(person1, date_of_sale)
        p2_b3 = _b3_applies(person2, date_of_sale)
        p1_1031 = _1031_blocked(date_of_sale, person1)
        p2_1031 = _1031_blocked(date_of_sale, person2)

        b2a = (
            (p1_own or p2_own)
            and (p1_use and p2_use)
            and (not p1_b3 and not p2_b3)
            and (not p1_1031 and not p2_1031)
        )
        if b2a:
            cap = 500_000.0
        else:
            # §121(b)(2)(B): sum of individual caps with merged ownership
            merged_own = _merge_periods(
                person1.property_ownage, person2.property_ownage
            )
            p1m = PersonalData(
                property_ownage=merged_own,
                property_usage_as_principal_residence=(
                    person1.property_usage_as_principal_residence
                ),
                most_recent_prior_121a_sale_date=(
                    person1.most_recent_prior_121a_sale_date
                ),
                reduced_exclusion_reason=(
                    person1.reduced_exclusion_reason
                ),
                acquired_via_1031_exchange=(
                    person1.acquired_via_1031_exchange
                ),
                date_of_1031_acquisition=(
                    person1.date_of_1031_acquisition
                ),
            )
            p2m = PersonalData(
                property_ownage=merged_own,
                property_usage_as_principal_residence=(
                    person2.property_usage_as_principal_residence
                ),
                most_recent_prior_121a_sale_date=(
                    person2.most_recent_prior_121a_sale_date
                ),
                reduced_exclusion_reason=(
                    person2.reduced_exclusion_reason
                ),
                acquired_via_1031_exchange=(
                    person2.acquired_via_1031_exchange
                ),
                date_of_1031_acquisition=(
                    person2.date_of_1031_acquisition
                ),
            )
            cap = _person_cap(p1m, date_of_sale) + _person_cap(p2m, date_of_sale)

    elif return_type == "surviving_spouse":
        base_cap = 250_000.0

        # Check §121(b)(4): sale within 2 years (730 days) of death
        if date_of_spouse_death is not None and person2 is not None:
            if (date_of_sale - date_of_spouse_death).days <= 730:
                # Check §121(b)(2)(A) conditions at time of death
                p1_own_d = _ownership_met(person1, date_of_spouse_death)
                p2_own_d = _ownership_met(person2, date_of_spouse_death)
                p1_use_d = _usage_met(person1, date_of_spouse_death)
                p2_use_d = _usage_met(person2, date_of_spouse_death)
                p1_b3_d = _b3_applies(person1, date_of_spouse_death)
                p2_b3_d = _b3_applies(person2, date_of_spouse_death)
                p1_1031_d = _1031_blocked(date_of_spouse_death, person1)
                p2_1031_d = _1031_blocked(date_of_spouse_death, person2)

                b2a_at_death = (
                    (p1_own_d or p2_own_d)
                    and (p1_use_d and p2_use_d)
                    and (not p1_b3_d and not p2_b3_d)
                    and (not p1_1031_d and not p2_1031_d)
                )
                if b2a_at_death:
                    base_cap = 500_000.0

        cap = _person_cap(person1, date_of_sale, base_cap)

    else:
        raise ValueError(f"Unknown return_type: {return_type}")

    # --- Apply cap ---
    excluded = min(eligible, cap)
    excluded = min(excluded, gain)  # can't exclude more than total gain

    taxable = gain - excluded

    return ExclusionResult(
        excluded_gain=excluded,
        non_excludable_depreciation=depr,
        taxable_gain=taxable,
    )
