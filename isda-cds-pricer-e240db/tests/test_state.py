"""
Tests for ISDA CDS Pricer — verifies computed values against ISDA standard
model reference values for three CDS trades with different start-date
configurations relative to the valuation date.

"""

import json
import os
import pytest


RESULTS_PATH = "/app/results.json"

# Reference values from ISDA CDS standard model.
# Tolerances: 1e-9 for unit values, 10.0 for PV
UNIT_TOL = 1e-9
PV_TOL = 10.0

# NEXTDAY: BUY, start 2014-01-04, end 2020-10-20, P3M, rate=0.05
NEXTDAY_PROT_LEG = 0.11768372979849945
NEXTDAY_DIRTY_ANNUITY = 6.392982238467668
NEXTDAY_CLEAN_PV = -2019653.8212488396

# BEFORE: SELL, start 2013-12-20, end 2024-09-20, P3M, rate=0.05
BEFORE_PROT_LEG = 0.19620351105145453
BEFORE_DIRTY_ANNUITY = 9.311802668593570
BEFORE_CLEAN_PV = 2673032.8904489065

# AFTER: BUY, start 2014-03-20, end 2029-12-20, P3M, rate=0.05
AFTER_PROT_LEG = 0.27439178003887780
AFTER_DIRTY_ANNUITY = 12.015897365496743
AFTER_CLEAN_PV = -3264030.8823595936


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found: {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestProtectionLeg:
    """Protection leg PV per unit notional."""

    def test_nextday_protection_leg(self, results):
        val = results["nextday_protection_leg"]
        assert abs(val - NEXTDAY_PROT_LEG) < UNIT_TOL, \
            f"nextday_protection_leg: got {val}, expected {NEXTDAY_PROT_LEG}, diff={abs(val - NEXTDAY_PROT_LEG)}"

    def test_before_protection_leg(self, results):
        val = results["before_protection_leg"]
        assert abs(val - BEFORE_PROT_LEG) < UNIT_TOL, \
            f"before_protection_leg: got {val}, expected {BEFORE_PROT_LEG}, diff={abs(val - BEFORE_PROT_LEG)}"

    def test_after_protection_leg(self, results):
        val = results["after_protection_leg"]
        assert abs(val - AFTER_PROT_LEG) < UNIT_TOL, \
            f"after_protection_leg: got {val}, expected {AFTER_PROT_LEG}, diff={abs(val - AFTER_PROT_LEG)}"


class TestDirtyAnnuity:
    """Dirty risky annuity (premium leg) per unit notional."""

    def test_nextday_dirty_annuity(self, results):
        val = results["nextday_dirty_annuity"]
        assert abs(val - NEXTDAY_DIRTY_ANNUITY) < UNIT_TOL, \
            f"nextday_dirty_annuity: got {val}, expected {NEXTDAY_DIRTY_ANNUITY}, diff={abs(val - NEXTDAY_DIRTY_ANNUITY)}"

    def test_before_dirty_annuity(self, results):
        val = results["before_dirty_annuity"]
        assert abs(val - BEFORE_DIRTY_ANNUITY) < UNIT_TOL, \
            f"before_dirty_annuity: got {val}, expected {BEFORE_DIRTY_ANNUITY}, diff={abs(val - BEFORE_DIRTY_ANNUITY)}"

    def test_after_dirty_annuity(self, results):
        val = results["after_dirty_annuity"]
        assert abs(val - AFTER_DIRTY_ANNUITY) < UNIT_TOL, \
            f"after_dirty_annuity: got {val}, expected {AFTER_DIRTY_ANNUITY}, diff={abs(val - AFTER_DIRTY_ANNUITY)}"


class TestCleanPV:
    """Clean present value in currency amount."""

    def test_nextday_clean_pv(self, results):
        val = results["nextday_clean_pv"]
        assert abs(val - NEXTDAY_CLEAN_PV) < PV_TOL, \
            f"nextday_clean_pv: got {val}, expected {NEXTDAY_CLEAN_PV}, diff={abs(val - NEXTDAY_CLEAN_PV)}"

    def test_before_clean_pv(self, results):
        val = results["before_clean_pv"]
        assert abs(val - BEFORE_CLEAN_PV) < PV_TOL, \
            f"before_clean_pv: got {val}, expected {BEFORE_CLEAN_PV}, diff={abs(val - BEFORE_CLEAN_PV)}"

    def test_after_clean_pv(self, results):
        val = results["after_clean_pv"]
        assert abs(val - AFTER_CLEAN_PV) < PV_TOL, \
            f"after_clean_pv: got {val}, expected {AFTER_CLEAN_PV}, diff={abs(val - AFTER_CLEAN_PV)}"


class TestOutputCompleteness:
    """Verify all required keys exist and have numeric values."""

    REQUIRED_KEYS = [
        "nextday_protection_leg", "nextday_dirty_annuity", "nextday_clean_pv",
        "before_protection_leg", "before_dirty_annuity", "before_clean_pv",
        "after_protection_leg", "after_dirty_annuity", "after_clean_pv",
    ]

    def test_all_keys_present(self, results):
        for key in self.REQUIRED_KEYS:
            assert key in results, f"Missing key: {key}"

    def test_all_values_numeric(self, results):
        for key in self.REQUIRED_KEYS:
            val = results.get(key)
            assert isinstance(val, (int, float)), f"{key} is not numeric: {type(val)}"

    def test_no_nan_or_inf(self, results):
        import math
        for key in self.REQUIRED_KEYS:
            val = results[key]
            assert not math.isnan(val), f"{key} is NaN"
            assert not math.isinf(val), f"{key} is Inf"
