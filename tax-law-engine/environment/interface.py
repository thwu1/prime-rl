"""
IRC Section 121 - Exclusion of Gain from Sale of Principal Residence

Data types and function signature for the Section 121 computation engine.
Implement the compute_exclusion function in tax_engine.py.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import List, Optional


class ReducedExclusionReason(Enum):
    """Qualifying reasons for reduced maximum exclusion under §121(c)."""
    NONE = "none"
    EMPLOYMENT_CHANGE = "employment_change"
    HEALTH = "health"
    UNFORESEEN = "unforeseen"


@dataclass
class Period:
    """A date range [begin, end) — begin inclusive, end exclusive."""
    begin: date
    end: date


@dataclass
class ExclusionResult:
    """Result of the §121 exclusion computation.

    excluded_gain: Dollar amount of gain excluded from gross income.
    non_excludable_depreciation: Depreciation recapture that cannot be
        excluded (always taxable per §121(d)(6)).
    taxable_gain: Total taxable gain = realized_gain - excluded_gain.
    """
    excluded_gain: float
    non_excludable_depreciation: float
    taxable_gain: float


@dataclass
class PersonalData:
    """Tax-relevant data for a single person regarding the property.

    For surviving_spouse return_type, person2 represents the deceased
    spouse's data as of the date of death (not the sale date).

    Non-qualified use periods and depreciation are property-level data
    carried on person1 for all return types.
    """
    property_ownage: List[Period] = field(default_factory=list)
    property_usage_as_principal_residence: List[Period] = field(default_factory=list)
    most_recent_prior_121a_sale_date: Optional[date] = None
    reduced_exclusion_reason: ReducedExclusionReason = ReducedExclusionReason.NONE
    non_qualified_use_periods: List[Period] = field(default_factory=list)
    depreciation_allowed: float = 0.0
    acquired_via_1031_exchange: bool = False
    date_of_1031_acquisition: Optional[date] = None


def compute_exclusion(
    date_of_sale: date,
    gain: float,
    return_type: str,
    person1: PersonalData,
    person2: Optional[PersonalData] = None,
    date_of_spouse_death: Optional[date] = None,
) -> ExclusionResult:
    """Compute the gain excluded from gross income under IRC Section 121.

    Args:
        date_of_sale: Date of the property sale or exchange.
        gain: Realized gain from the sale (dollars, non-negative).
        return_type: One of "single", "joint", or "surviving_spouse".
        person1: Data for the taxpayer (or surviving spouse).
                 Also carries property-level NQ use and depreciation data.
        person2: Data for second spouse (joint) or deceased spouse
                 (surviving_spouse).
        date_of_spouse_death: Date of death (surviving_spouse only).

    Returns:
        ExclusionResult with excluded_gain, non_excludable_depreciation,
        and taxable_gain.
    """
    raise NotImplementedError("Implement this function in tax_engine.py")
