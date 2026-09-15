
"""
Tests for Section 121 property sale gain exclusion calculator.

Verifies the compute_exclusion function against 16 scenarios covering
single/joint/surviving-spouse returns, period aggregation edge cases,
the §121(b)(3) recency rule, and joint return conditions (A) and (B).
"""

import sys
import pytest

sys.path.insert(0, "/app")
from section121 import compute_exclusion


SCENARIOS = [
    # 1. Single, qualifies, gain under cap
    pytest.param(
        {
            "date_of_sale": "2024-06-15",
            "gain": 200000,
            "return_type": "single",
            "person": {
                "ownership_periods": [
                    {"begin": "2018-01-01", "end": "2024-06-15"}
                ],
                "usage_periods": [
                    {"begin": "2018-01-01", "end": "2024-06-15"}
                ],
                "prior_sale_date": None,
            },
        },
        200000,
        250000,
        id="single_basic_qualifies",
    ),
    # 2. Single, ownership insufficient (380 days < 730)
    pytest.param(
        {
            "date_of_sale": "2024-06-15",
            "gain": 200000,
            "return_type": "single",
            "person": {
                "ownership_periods": [
                    {"begin": "2023-06-01", "end": "2024-06-15"}
                ],
                "usage_periods": [
                    {"begin": "2019-01-01", "end": "2024-06-15"}
                ],
                "prior_sale_date": None,
            },
        },
        0,
        250000,
        id="single_ownership_insufficient",
    ),
    # 3. Single, gain exceeds cap
    pytest.param(
        {
            "date_of_sale": "2024-06-15",
            "gain": 400000,
            "return_type": "single",
            "person": {
                "ownership_periods": [
                    {"begin": "2018-01-01", "end": "2024-06-15"}
                ],
                "usage_periods": [
                    {"begin": "2018-01-01", "end": "2024-06-15"}
                ],
                "prior_sale_date": None,
            },
        },
        250000,
        250000,
        id="single_gain_exceeds_cap",
    ),
    # 4. Single, b3 applies (prior sale 380 days ago <= 730)
    pytest.param(
        {
            "date_of_sale": "2024-06-15",
            "gain": 200000,
            "return_type": "single",
            "person": {
                "ownership_periods": [
                    {"begin": "2015-01-01", "end": "2024-06-15"}
                ],
                "usage_periods": [
                    {"begin": "2015-01-01", "end": "2024-06-15"}
                ],
                "prior_sale_date": "2023-06-01",
            },
        },
        0,
        250000,
        id="single_b3_applies",
    ),
    # 5. Single, prior sale 1110 days ago (> 730, b3 does not apply)
    pytest.param(
        {
            "date_of_sale": "2024-06-15",
            "gain": 200000,
            "return_type": "single",
            "person": {
                "ownership_periods": [
                    {"begin": "2015-01-01", "end": "2024-06-15"}
                ],
                "usage_periods": [
                    {"begin": "2015-01-01", "end": "2024-06-15"}
                ],
                "prior_sale_date": "2021-06-01",
            },
        },
        200000,
        250000,
        id="single_prior_sale_old_enough",
    ),
    # 6. Single, partial period in 5-year window: exactly 730 days (passes)
    #    Period [2016-01-01, 2021-06-15], sale 2024-06-15
    #    end+5y = 2026-06-15, (2026-06-15 - 2024-06-15).days = 730
    pytest.param(
        {
            "date_of_sale": "2024-06-15",
            "gain": 200000,
            "return_type": "single",
            "person": {
                "ownership_periods": [
                    {"begin": "2016-01-01", "end": "2021-06-15"}
                ],
                "usage_periods": [
                    {"begin": "2016-01-01", "end": "2021-06-15"}
                ],
                "prior_sale_date": None,
            },
        },
        200000,
        250000,
        id="single_partial_period_exactly_730",
    ),
    # 7. Single, partial period: 729 days (fails)
    #    Period [2016-01-01, 2021-06-14], sale 2024-06-15
    #    end+5y = 2026-06-14, (2026-06-14 - 2024-06-15).days = 729
    pytest.param(
        {
            "date_of_sale": "2024-06-15",
            "gain": 200000,
            "return_type": "single",
            "person": {
                "ownership_periods": [
                    {"begin": "2016-01-01", "end": "2021-06-14"}
                ],
                "usage_periods": [
                    {"begin": "2016-01-01", "end": "2021-06-14"}
                ],
                "prior_sale_date": None,
            },
        },
        0,
        250000,
        id="single_partial_period_729_days",
    ),
    # 8. Single, two disjoint ownership periods that aggregate above 730
    #    Period1: [2020-01-01, 2021-06-15] → 531 days (full, within window)
    #    Period2: [2022-06-15, 2024-06-15] → 731 days (full, within window)
    #    Total: 1262 days
    pytest.param(
        {
            "date_of_sale": "2024-06-15",
            "gain": 200000,
            "return_type": "single",
            "person": {
                "ownership_periods": [
                    {"begin": "2020-01-01", "end": "2021-06-15"},
                    {"begin": "2022-06-15", "end": "2024-06-15"},
                ],
                "usage_periods": [
                    {"begin": "2019-01-01", "end": "2024-06-15"}
                ],
                "prior_sale_date": None,
            },
        },
        200000,
        250000,
        id="single_multiple_ownership_periods",
    ),
    # 9. Joint (A) applies: person1 owns, both use, neither b3 → $500k cap
    pytest.param(
        {
            "date_of_sale": "2024-06-15",
            "gain": 450000,
            "return_type": "joint",
            "person1": {
                "ownership_periods": [
                    {"begin": "2018-01-01", "end": "2024-06-15"}
                ],
                "usage_periods": [
                    {"begin": "2018-01-01", "end": "2024-06-15"}
                ],
                "prior_sale_date": None,
            },
            "person2": {
                "ownership_periods": [],
                "usage_periods": [
                    {"begin": "2018-01-01", "end": "2024-06-15"}
                ],
                "prior_sale_date": None,
            },
        },
        450000,
        500000,
        id="joint_condition_a_500k",
    ),
    # 10. Joint (B): person2 fails usage (380 days). Person1 qualifies → cap $250k
    pytest.param(
        {
            "date_of_sale": "2024-06-15",
            "gain": 300000,
            "return_type": "joint",
            "person1": {
                "ownership_periods": [
                    {"begin": "2018-01-01", "end": "2024-06-15"}
                ],
                "usage_periods": [
                    {"begin": "2018-01-01", "end": "2024-06-15"}
                ],
                "prior_sale_date": None,
            },
            "person2": {
                "ownership_periods": [],
                "usage_periods": [
                    {"begin": "2023-06-01", "end": "2024-06-15"}
                ],
                "prior_sale_date": None,
            },
        },
        250000,
        250000,
        id="joint_condition_b_one_qualifies",
    ),
    # 11. Surviving spouse within 2 calendar years of death, (A) met → $500k
    pytest.param(
        {
            "date_of_sale": "2024-06-15",
            "gain": 400000,
            "return_type": "surviving_spouse",
            "survivor": {
                "ownership_periods": [
                    {"begin": "2018-01-01", "end": "2024-06-15"}
                ],
                "usage_periods": [
                    {"begin": "2018-01-01", "end": "2024-06-15"}
                ],
                "prior_sale_date": None,
            },
            "deceased_at_death": {
                "ownership_periods": [
                    {"begin": "2018-01-01", "end": "2023-06-01"}
                ],
                "usage_periods": [
                    {"begin": "2018-01-01", "end": "2023-06-01"}
                ],
                "prior_sale_date": None,
            },
            "date_of_death": "2023-06-01",
        },
        400000,
        500000,
        id="surviving_spouse_within_2_years",
    ),
    # 12. Surviving spouse, sale > 2 years after death → single treatment
    pytest.param(
        {
            "date_of_sale": "2026-06-15",
            "gain": 400000,
            "return_type": "surviving_spouse",
            "survivor": {
                "ownership_periods": [
                    {"begin": "2018-01-01", "end": "2026-06-15"}
                ],
                "usage_periods": [
                    {"begin": "2018-01-01", "end": "2026-06-15"}
                ],
                "prior_sale_date": None,
            },
            "deceased_at_death": {
                "ownership_periods": [
                    {"begin": "2018-01-01", "end": "2023-06-01"}
                ],
                "usage_periods": [
                    {"begin": "2018-01-01", "end": "2023-06-01"}
                ],
                "prior_sale_date": None,
            },
            "date_of_death": "2023-06-01",
        },
        250000,
        250000,
        id="surviving_spouse_too_late",
    ),
    # 13. Single, sufficient ownership but zero usage
    pytest.param(
        {
            "date_of_sale": "2024-06-15",
            "gain": 200000,
            "return_type": "single",
            "person": {
                "ownership_periods": [
                    {"begin": "2018-01-01", "end": "2024-06-15"}
                ],
                "usage_periods": [],
                "prior_sale_date": None,
            },
        },
        0,
        250000,
        id="single_no_usage",
    ),
    # 14. Joint: person1 has b3 (197 days) → (A) fails on (iii).
    #     Under (B): person1 blocked by b3, person2 qualifies with merged ownership.
    pytest.param(
        {
            "date_of_sale": "2024-06-15",
            "gain": 300000,
            "return_type": "joint",
            "person1": {
                "ownership_periods": [
                    {"begin": "2018-01-01", "end": "2024-06-15"}
                ],
                "usage_periods": [
                    {"begin": "2018-01-01", "end": "2024-06-15"}
                ],
                "prior_sale_date": "2023-12-01",
            },
            "person2": {
                "ownership_periods": [],
                "usage_periods": [
                    {"begin": "2018-01-01", "end": "2024-06-15"}
                ],
                "prior_sale_date": None,
            },
        },
        250000,
        250000,
        id="joint_b3_blocks_a_condition",
    ),
    # 15. Joint (B): neither meets ownership individually (531 and 379 days),
    #     but merged ownership (745 days) qualifies both → cap $500k
    #     Person1 own [2023-01-01,2024-06-15], Person2 own [2022-06-01,2023-06-15]
    #     Merged: [2022-06-01, 2024-06-15] → 745 days >= 730
    pytest.param(
        {
            "date_of_sale": "2024-06-15",
            "gain": 480000,
            "return_type": "joint",
            "person1": {
                "ownership_periods": [
                    {"begin": "2023-01-01", "end": "2024-06-15"}
                ],
                "usage_periods": [
                    {"begin": "2019-01-01", "end": "2024-06-15"}
                ],
                "prior_sale_date": None,
            },
            "person2": {
                "ownership_periods": [
                    {"begin": "2022-06-01", "end": "2023-06-15"}
                ],
                "usage_periods": [
                    {"begin": "2019-01-01", "end": "2024-06-15"}
                ],
                "prior_sale_date": None,
            },
        },
        480000,
        500000,
        id="joint_b_both_qualify_merged_ownership",
    ),
    # 16. Single, ownership period entirely before the 5-year window → 0 days
    #     Period [2010-01-01, 2012-01-01], sale 2024-06-15
    #     end+5y = 2017-01-01 <= sale_date → 0 contribution
    pytest.param(
        {
            "date_of_sale": "2024-06-15",
            "gain": 200000,
            "return_type": "single",
            "person": {
                "ownership_periods": [
                    {"begin": "2010-01-01", "end": "2012-01-01"}
                ],
                "usage_periods": [
                    {"begin": "2010-01-01", "end": "2012-01-01"}
                ],
                "prior_sale_date": None,
            },
        },
        0,
        250000,
        id="single_period_outside_window",
    ),
]


@pytest.mark.parametrize("scenario,expected_excluded,expected_cap", SCENARIOS)
def test_compute_exclusion(scenario, expected_excluded, expected_cap):
    """Verify excluded_amount and gain_cap for each scenario."""
    result = compute_exclusion(scenario)

    assert isinstance(result, dict), "compute_exclusion must return a dict"
    assert "excluded_amount" in result, "Result must contain 'excluded_amount'"
    assert "gain_cap" in result, "Result must contain 'gain_cap'"

    assert result["excluded_amount"] == expected_excluded, (
        f"excluded_amount: expected {expected_excluded}, got {result['excluded_amount']}"
    )
    assert result["gain_cap"] == expected_cap, (
        f"gain_cap: expected {expected_cap}, got {result['gain_cap']}"
    )
