
"""Tests for IRC Section 121 Capital Gains Exclusion Engine
with formal verification."""

import json
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, "/app")
from interface import (
    ExclusionResult,
    Period,
    PersonalData,
    ReducedExclusionReason,
)
from tax_engine import compute_exclusion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_period(start_year: int, end_year: int) -> Period:
    """Return Period(Jan 1 start_year, Jan 1 end_year)."""
    return Period(date(start_year, 1, 1), date(end_year, 1, 1))


def _standard_person(start_year: int = 2020, end_year: int = 2025,
                      prior_sale: date = None) -> PersonalData:
    """Person who owns and uses from Jan 1 start_year to Jan 1 end_year."""
    p = _full_period(start_year, end_year)
    return PersonalData(
        property_ownage=[p],
        property_usage_as_principal_residence=[p],
        most_recent_prior_121a_sale_date=prior_sale,
    )


def _assert_result(result: ExclusionResult, excluded: float,
                   depreciation: float, taxable: float):
    """Assert all three fields of an ExclusionResult."""
    assert result.excluded_gain == pytest.approx(excluded, abs=0.01), \
        f"excluded_gain: expected {excluded}, got {result.excluded_gain}"
    assert result.non_excludable_depreciation == pytest.approx(depreciation, abs=0.01), \
        f"non_excludable_depreciation: expected {depreciation}, got {result.non_excludable_depreciation}"
    assert result.taxable_gain == pytest.approx(taxable, abs=0.01), \
        f"taxable_gain: expected {taxable}, got {result.taxable_gain}"


SALE_DATE = date(2025, 1, 1)


# ---------------------------------------------------------------------------
# §121(a) + §121(b)(1): Single-person basics
# ---------------------------------------------------------------------------

class TestSingleBasic:
    def test_gain_below_cap(self):
        result = compute_exclusion(SALE_DATE, 200_000.0, "single",
                                   _standard_person())
        _assert_result(result, 200_000.0, 0.0, 0.0)

    def test_gain_above_cap(self):
        result = compute_exclusion(SALE_DATE, 400_000.0, "single",
                                   _standard_person())
        _assert_result(result, 250_000.0, 0.0, 150_000.0)

    def test_zero_gain(self):
        result = compute_exclusion(SALE_DATE, 0.0, "single",
                                   _standard_person())
        _assert_result(result, 0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# §121(a): Ownership and usage requirements
# ---------------------------------------------------------------------------

class TestRequirements:
    def test_ownership_insufficient(self):
        """Owned < 730 days in 5-year window (366 days)."""
        person = PersonalData(
            property_ownage=[Period(date(2024, 1, 1), date(2025, 1, 1))],
            property_usage_as_principal_residence=[
                _full_period(2020, 2025)
            ],
        )
        result = compute_exclusion(SALE_DATE, 200_000.0, "single", person)
        _assert_result(result, 0.0, 0.0, 200_000.0)

    def test_usage_insufficient(self):
        """Used < 730 days in 5-year window (275 days)."""
        person = PersonalData(
            property_ownage=[_full_period(2020, 2025)],
            property_usage_as_principal_residence=[
                Period(date(2024, 4, 1), date(2025, 1, 1))
            ],
        )
        result = compute_exclusion(SALE_DATE, 200_000.0, "single", person)
        _assert_result(result, 0.0, 0.0, 200_000.0)


# ---------------------------------------------------------------------------
# Period aggregation within the 5-year window
# ---------------------------------------------------------------------------

class TestPeriodAggregation:
    def test_clipping_to_five_year_window(self):
        """Usage period starts before window. Unclipped = 1247 days (pass),
        but clipped = 517 days (fail). Tests that only the in-window portion
        counts."""
        person = PersonalData(
            property_ownage=[Period(date(2018, 1, 1), date(2025, 1, 1))],
            property_usage_as_principal_residence=[
                Period(date(2018, 1, 1), date(2021, 6, 1))
            ],
        )
        result = compute_exclusion(SALE_DATE, 200_000.0, "single", person)
        _assert_result(result, 0.0, 0.0, 200_000.0)

    def test_multiple_periods_aggregate_pass(self):
        """Two usage periods totalling 853 days (>= 730)."""
        person = PersonalData(
            property_ownage=[_full_period(2020, 2025)],
            property_usage_as_principal_residence=[
                Period(date(2020, 3, 1), date(2021, 5, 1)),   # 426 days
                Period(date(2023, 6, 1), date(2024, 8, 1)),   # 427 days
            ],
        )
        result = compute_exclusion(SALE_DATE, 180_000.0, "single", person)
        _assert_result(result, 180_000.0, 0.0, 0.0)

    def test_multiple_periods_aggregate_fail(self):
        """Two usage periods totalling 698 days (< 730)."""
        person = PersonalData(
            property_ownage=[_full_period(2020, 2025)],
            property_usage_as_principal_residence=[
                Period(date(2020, 6, 1), date(2021, 3, 1)),   # 273 days
                Period(date(2023, 1, 1), date(2024, 3, 1)),   # 425 days
            ],
        )
        result = compute_exclusion(SALE_DATE, 200_000.0, "single", person)
        _assert_result(result, 0.0, 0.0, 200_000.0)


# ---------------------------------------------------------------------------
# §121(b)(2)(A): Joint returns — $500,000 cap
# ---------------------------------------------------------------------------

class TestJointQualifying:
    def test_both_qualify_below_cap(self):
        result = compute_exclusion(SALE_DATE, 400_000.0, "joint",
                                   _standard_person(), _standard_person())
        _assert_result(result, 400_000.0, 0.0, 0.0)

    def test_both_qualify_above_cap(self):
        result = compute_exclusion(SALE_DATE, 700_000.0, "joint",
                                   _standard_person(), _standard_person())
        _assert_result(result, 500_000.0, 0.0, 200_000.0)


# ---------------------------------------------------------------------------
# §121(b)(2)(B): Joint returns — non-qualifying, individual limits
# ---------------------------------------------------------------------------

class TestJointNonQualifying:
    def test_one_spouse_usage_fails(self):
        """Person2 fails usage (275 days). (A) fails because not both meet
        usage. Under (B), person2 ineligible -> total cap = $250k."""
        p1 = _standard_person()
        p2 = PersonalData(
            property_ownage=[_full_period(2020, 2025)],
            property_usage_as_principal_residence=[
                Period(date(2024, 4, 1), date(2025, 1, 1))
            ],
        )
        result = compute_exclusion(SALE_DATE, 400_000.0, "joint", p1, p2)
        _assert_result(result, 250_000.0, 0.0, 150_000.0)


# ---------------------------------------------------------------------------
# §121(b)(3): Prior sale within 730 days
# ---------------------------------------------------------------------------

class TestPriorSale:
    def test_prior_sale_blocks(self):
        """Prior sale 245 days ago -> blocked."""
        person = _standard_person(prior_sale=date(2024, 5, 1))
        result = compute_exclusion(SALE_DATE, 200_000.0, "single", person)
        _assert_result(result, 0.0, 0.0, 200_000.0)

    def test_prior_sale_exactly_730_days(self):
        """Prior sale exactly 730 days ago -> still blocked (<=)."""
        prior = SALE_DATE - timedelta(days=730)
        person = _standard_person(prior_sale=prior)
        result = compute_exclusion(SALE_DATE, 200_000.0, "single", person)
        _assert_result(result, 0.0, 0.0, 200_000.0)

    def test_prior_sale_731_days_not_blocked(self):
        """Prior sale 731 days ago -> not blocked."""
        prior = SALE_DATE - timedelta(days=731)
        person = _standard_person(prior_sale=prior)
        result = compute_exclusion(SALE_DATE, 200_000.0, "single", person)
        _assert_result(result, 200_000.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# §121(b)(4): Surviving spouse
# ---------------------------------------------------------------------------

class TestSurvivingSpouse:
    def test_within_2_years_of_death(self):
        """Sale within 2 years (730 days) of death, (2)(A) met at death ->
        $500k cap."""
        survivor = PersonalData(
            property_ownage=[Period(date(2017, 1, 1), date(2025, 1, 1))],
            property_usage_as_principal_residence=[
                Period(date(2017, 1, 1), date(2025, 1, 1))
            ],
        )
        deceased = PersonalData(
            property_ownage=[Period(date(2017, 1, 1), date(2023, 6, 15))],
            property_usage_as_principal_residence=[
                Period(date(2017, 1, 1), date(2023, 6, 15))
            ],
        )
        result = compute_exclusion(
            date(2025, 1, 1), 450_000.0, "surviving_spouse",
            survivor, deceased, date_of_spouse_death=date(2023, 6, 15),
        )
        _assert_result(result, 450_000.0, 0.0, 0.0)

    def test_after_2_years_of_death(self):
        """Sale more than 730 days after death -> regular $250k cap."""
        survivor = PersonalData(
            property_ownage=[Period(date(2017, 1, 1), date(2026, 1, 1))],
            property_usage_as_principal_residence=[
                Period(date(2017, 1, 1), date(2026, 1, 1))
            ],
        )
        deceased = PersonalData(
            property_ownage=[Period(date(2017, 1, 1), date(2023, 6, 15))],
            property_usage_as_principal_residence=[
                Period(date(2017, 1, 1), date(2023, 6, 15))
            ],
        )
        result = compute_exclusion(
            date(2026, 1, 1), 450_000.0, "surviving_spouse",
            survivor, deceased, date_of_spouse_death=date(2023, 6, 15),
        )
        _assert_result(result, 250_000.0, 0.0, 200_000.0)


# ---------------------------------------------------------------------------
# §121(c): Reduced maximum exclusion
# ---------------------------------------------------------------------------

class TestReducedExclusion:
    def test_employment_change_prorated(self):
        """365 days owned and used, employment change -> cap = 250k * 365/730
        = 125,000."""
        person = PersonalData(
            property_ownage=[Period(date(2024, 1, 2), date(2025, 1, 1))],
            property_usage_as_principal_residence=[
                Period(date(2024, 1, 2), date(2025, 1, 1))
            ],
            reduced_exclusion_reason=ReducedExclusionReason.EMPLOYMENT_CHANGE,
        )
        result = compute_exclusion(SALE_DATE, 200_000.0, "single", person)
        _assert_result(result, 125_000.0, 0.0, 75_000.0)

    def test_121a_met_reason_irrelevant(self):
        """Person meets full §121(a) requirements. Even though a qualifying
        reason is specified, the full cap applies (§121(c) only applies when
        §121(a) is NOT met)."""
        person = PersonalData(
            property_ownage=[_full_period(2020, 2025)],
            property_usage_as_principal_residence=[_full_period(2020, 2025)],
            reduced_exclusion_reason=ReducedExclusionReason.EMPLOYMENT_CHANGE,
        )
        result = compute_exclusion(SALE_DATE, 200_000.0, "single", person)
        _assert_result(result, 200_000.0, 0.0, 0.0)

    def test_no_reason_no_exclusion(self):
        """§121(a) not met, no qualifying reason -> $0 exclusion."""
        person = PersonalData(
            property_ownage=[Period(date(2024, 1, 2), date(2025, 1, 1))],
            property_usage_as_principal_residence=[
                Period(date(2024, 1, 2), date(2025, 1, 1))
            ],
        )
        result = compute_exclusion(SALE_DATE, 200_000.0, "single", person)
        _assert_result(result, 0.0, 0.0, 200_000.0)


# ---------------------------------------------------------------------------
# §121(b)(5): Non-qualified use
# ---------------------------------------------------------------------------

class TestNonQualifiedUse:
    def test_nq_reduces_exclusion(self):
        """NQ use period reduces eligible gain. Total ownership = 1825 days,
        NQ use = 365 days -> nq_ratio = 0.2. gain = 100,000 ->
        eligible = 80,000."""
        person = PersonalData(
            property_ownage=[Period(date(2020, 1, 3), date(2025, 1, 1))],
            property_usage_as_principal_residence=[
                Period(date(2020, 1, 3), date(2022, 6, 1)),
                Period(date(2023, 6, 1), date(2025, 1, 1)),
            ],
            non_qualified_use_periods=[
                Period(date(2022, 6, 1), date(2023, 6, 1)),  # 365 days
            ],
        )
        result = compute_exclusion(SALE_DATE, 100_000.0, "single", person)
        # nq_ratio = 365/1825 = 0.2, eligible = 100000 * 0.8 = 80000
        _assert_result(result, 80_000.0, 0.0, 20_000.0)

    def test_nq_with_depreciation(self):
        """Same as above but with depreciation. eligible =
        (100000 - 5000) * 0.8 = 76000."""
        person = PersonalData(
            property_ownage=[Period(date(2020, 1, 3), date(2025, 1, 1))],
            property_usage_as_principal_residence=[
                Period(date(2020, 1, 3), date(2022, 6, 1)),
                Period(date(2023, 6, 1), date(2025, 1, 1)),
            ],
            non_qualified_use_periods=[
                Period(date(2022, 6, 1), date(2023, 6, 1)),
            ],
            depreciation_allowed=5_000.0,
        )
        result = compute_exclusion(SALE_DATE, 100_000.0, "single", person)
        _assert_result(result, 76_000.0, 5_000.0, 24_000.0)

    def test_pre_first_use_excluded(self):
        """NQ period before first use as principal residence is excluded from
        the NQ ratio. All NQ is pre-first-use -> nq_ratio = 0."""
        person = PersonalData(
            property_ownage=[Period(date(2018, 1, 1), date(2025, 1, 1))],
            property_usage_as_principal_residence=[
                Period(date(2020, 1, 1), date(2025, 1, 1)),
            ],
            non_qualified_use_periods=[
                Period(date(2018, 1, 1), date(2020, 1, 1)),
            ],
        )
        result = compute_exclusion(SALE_DATE, 200_000.0, "single", person)
        _assert_result(result, 200_000.0, 0.0, 0.0)

    def test_post_last_use_in_window_excluded(self):
        """NQ period after last use that falls within the 5-year window is
        excluded from the NQ ratio per §121(b)(5)(C)(ii)."""
        person = PersonalData(
            property_ownage=[Period(date(2019, 1, 1), date(2025, 1, 1))],
            property_usage_as_principal_residence=[
                Period(date(2019, 1, 1), date(2023, 1, 1)),
            ],
            non_qualified_use_periods=[
                Period(date(2023, 1, 1), date(2025, 1, 1)),
            ],
        )
        result = compute_exclusion(SALE_DATE, 200_000.0, "single", person)
        _assert_result(result, 200_000.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Combined: Joint + prior sale interaction
# ---------------------------------------------------------------------------

class TestJointPriorSale:
    def test_one_spouse_prior_sale_blocks_b2a(self):
        """Person2 has a prior sale within 730 days. (A) fails because
        person2 is ineligible under (b)(3). Under (B), person2 gets $0
        cap, person1 gets $250k -> total cap $250k."""
        p1 = _standard_person()
        p2 = _standard_person(prior_sale=date(2024, 5, 1))
        result = compute_exclusion(SALE_DATE, 400_000.0, "joint", p1, p2)
        _assert_result(result, 250_000.0, 0.0, 150_000.0)


# ---------------------------------------------------------------------------
# Combined: Joint + §121(c) reduced exclusion for one spouse
# ---------------------------------------------------------------------------

class TestJointReduced:
    def test_one_spouse_reduced(self):
        """P1 meets §121(a), P2 has 365 days + employment change.
        Under (B) with merged ownership: P1 cap = 250k, P2 reduced cap =
        250k * 365/730 = 125k -> total = 375k."""
        p1 = _standard_person()
        p2 = PersonalData(
            property_ownage=[Period(date(2024, 1, 2), date(2025, 1, 1))],
            property_usage_as_principal_residence=[
                Period(date(2024, 1, 2), date(2025, 1, 1)),
            ],
            reduced_exclusion_reason=ReducedExclusionReason.EMPLOYMENT_CHANGE,
        )
        result = compute_exclusion(SALE_DATE, 500_000.0, "joint", p1, p2)
        _assert_result(result, 375_000.0, 0.0, 125_000.0)


# ---------------------------------------------------------------------------
# §121(d)(10): Property acquired in like-kind exchange
# ---------------------------------------------------------------------------

class Test1031Exchange:
    def test_within_5_years_blocked(self):
        """Property acquired via §1031 exchange, sold within 5 years of
        acquisition -> exclusion blocked entirely."""
        person = PersonalData(
            property_ownage=[Period(date(2021, 1, 1), date(2025, 1, 1))],
            property_usage_as_principal_residence=[
                Period(date(2021, 1, 1), date(2025, 1, 1))
            ],
            acquired_via_1031_exchange=True,
            date_of_1031_acquisition=date(2021, 1, 1),
        )
        result = compute_exclusion(SALE_DATE, 200_000.0, "single", person)
        _assert_result(result, 0.0, 0.0, 200_000.0)

    def test_after_5_years_allowed(self):
        """Property acquired via §1031 exchange, sold after 5 years of
        acquisition -> normal exclusion rules apply."""
        person = PersonalData(
            property_ownage=[Period(date(2019, 1, 1), date(2025, 1, 1))],
            property_usage_as_principal_residence=[
                Period(date(2019, 1, 1), date(2025, 1, 1))
            ],
            acquired_via_1031_exchange=True,
            date_of_1031_acquisition=date(2019, 1, 1),
        )
        result = compute_exclusion(SALE_DATE, 200_000.0, "single", person)
        _assert_result(result, 200_000.0, 0.0, 0.0)

    def test_joint_one_spouse_1031_blocked(self):
        """One spouse acquired via §1031 within 5 years. (A) fails per
        (A)(iii)/(d)(10), under (B) blocked spouse gets $0, other gets $250k."""
        p1 = _standard_person()
        p2 = PersonalData(
            property_ownage=[Period(date(2021, 1, 1), date(2025, 1, 1))],
            property_usage_as_principal_residence=[
                Period(date(2021, 1, 1), date(2025, 1, 1))
            ],
            acquired_via_1031_exchange=True,
            date_of_1031_acquisition=date(2021, 1, 1),
        )
        result = compute_exclusion(SALE_DATE, 400_000.0, "joint", p1, p2)
        _assert_result(result, 250_000.0, 0.0, 150_000.0)


# ---------------------------------------------------------------------------
# Formal Verification
# ---------------------------------------------------------------------------

class TestFormalVerification:
    @pytest.fixture(autouse=True)
    def load_results(self):
        with open("/app/verification_results.json") as f:
            data = json.load(f)
        self.by_name = {r["property"]: r for r in data}

    def test_all_properties_present(self):
        expected = {
            "single_cap_bound", "joint_cap_bound",
            "reduced_leq_full", "nq_use_can_reduce",
        }
        assert set(self.by_name.keys()) == expected

    def test_single_cap_bound_proved(self):
        r = self.by_name["single_cap_bound"]
        assert r["result"] == "proved"
        assert r["solver_result"] == "unsat"

    def test_joint_cap_bound_proved(self):
        r = self.by_name["joint_cap_bound"]
        assert r["result"] == "proved"
        assert r["solver_result"] == "unsat"

    def test_reduced_leq_full_proved(self):
        r = self.by_name["reduced_leq_full"]
        assert r["result"] == "proved"
        assert r["solver_result"] == "unsat"

    def test_nq_use_can_reduce_witnessed(self):
        r = self.by_name["nq_use_can_reduce"]
        assert r["result"] == "witness_found"
        assert r["solver_result"] == "sat"
