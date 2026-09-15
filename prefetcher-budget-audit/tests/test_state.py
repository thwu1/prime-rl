
"""
Tests for DPC-3 prefetcher storage budget audit.

Expected correct values (derived from source files):

L1D structures:
  - Active Page Table: (2^7 - 1) = 127 entries x (52+10+64+6+(12*7)+(12*5)+6+7) = 289 bits = 36703
  - History Buffer: 2^10 = 1024 entries x (7+6+16) = 29 bits = 29696
  - Pending Prefetch: 2^9 = 512 entries x (7+6+16+1) = 30 bits = 15360
  - Archive Table: ((2^10)+(2^8)+(2^6))-1 = 1343 entries x (32+64+6+7+11) = 120 bits = 161160
  - IP Table: 2^10 = 1024 entries x 11 bits = 11264
  - Aux (hb_head + pp_head): 10 + 9 = 19
  Total L1D: 254202

L2C structures:
  - Signature Table: 2^9 = 512 entries x (16+6+12+9) = 43 bits = 22016
  - Pattern Table: 2^12 = 4096 entries x (64+4) = 68 bits = 278528
  - Accumulation Table: (2^7)+(2^5) = 160 entries x (48+64+6+12+8) = 138 bits = 22080
  - Prefetch Filter: 2^10 = 1024 entries x (12+2) = 14 bits = 14336
  - Perceptron Weights: 6 features x 2^8 = 256 entries x 6 bits = 9216
  - Aux (threshold_counter): 10
  Total L2C: 346186

LLC structures:
  - Stream Table: 2^6 = 64 entries x (42+6+1+3+1+6) = 59 bits = 3776
  - Region Table: (2^9)-(2^3) = 504 entries x (32+64+9) = 105 bits = 52920
  Total LLC: 56696

Grand Total: 254202 + 346186 + 56696 = 657084 bits
Budget: 524288 bits (64 KB)
Over budget: 132796 bits
Compliant: False
"""

import json
import os
import pytest


EXPECTED = {
    "l1d_total_bits": 254202,
    "l2c_total_bits": 346186,
    "llc_total_bits": 56696,
    "grand_total_bits": 657084,
    "budget_limit_bits": 524288,
    "compliant": False,
    "over_budget_bits": 132796,
}

AUDIT_FILE = "/app/storage_audit.json"


@pytest.fixture
def audit_data():
    assert os.path.exists(AUDIT_FILE), (
        f"Audit file {AUDIT_FILE} does not exist. "
        "The agent must write the storage audit results to this file."
    )
    with open(AUDIT_FILE, "r") as f:
        data = json.load(f)
    return data


def test_audit_file_has_required_keys(audit_data):
    """Verify the audit JSON contains all required keys."""
    for key in EXPECTED:
        assert key in audit_data, f"Missing required key: '{key}'"


def test_l1d_total_bits(audit_data):
    """
    L1D budget must be exactly 254202 bits.

    Breakdown:
    - APT: 127 * 289 = 36703
    - HB:  1024 * 29 = 29696
    - PP:  512 * 30  = 15360
    - AT:  1343 * 120 = 161160
    - IP:  1024 * 11 = 11264
    - Aux: 10 + 9 = 19
    """
    assert audit_data["l1d_total_bits"] == EXPECTED["l1d_total_bits"], (
        f"L1D total bits: expected {EXPECTED['l1d_total_bits']}, "
        f"got {audit_data['l1d_total_bits']}"
    )


def test_l2c_total_bits(audit_data):
    """
    L2C budget must be exactly 346186 bits.

    Breakdown:
    - ST:    512 * 43  = 22016
    - PT:    4096 * 68 = 278528
    - ACCUM: 160 * 138 = 22080
    - PF:    1024 * 14 = 14336
    - PERC:  6 * 256 * 6 = 9216
    - Aux:   10
    """
    assert audit_data["l2c_total_bits"] == EXPECTED["l2c_total_bits"], (
        f"L2C total bits: expected {EXPECTED['l2c_total_bits']}, "
        f"got {audit_data['l2c_total_bits']}"
    )


def test_llc_total_bits(audit_data):
    """
    LLC budget must be exactly 56696 bits.

    Breakdown:
    - Stream: 64 * 59   = 3776
    - Region: 504 * 105 = 52920
    """
    assert audit_data["llc_total_bits"] == EXPECTED["llc_total_bits"], (
        f"LLC total bits: expected {EXPECTED['llc_total_bits']}, "
        f"got {audit_data['llc_total_bits']}"
    )


def test_grand_total_bits(audit_data):
    """Grand total must equal the sum of all three levels: 657084 bits."""
    assert audit_data["grand_total_bits"] == EXPECTED["grand_total_bits"], (
        f"Grand total bits: expected {EXPECTED['grand_total_bits']}, "
        f"got {audit_data['grand_total_bits']}"
    )


def test_grand_total_is_sum_of_levels(audit_data):
    """Grand total must be the arithmetic sum of L1D + L2C + LLC totals."""
    computed_sum = (
        audit_data["l1d_total_bits"]
        + audit_data["l2c_total_bits"]
        + audit_data["llc_total_bits"]
    )
    assert audit_data["grand_total_bits"] == computed_sum, (
        f"Grand total ({audit_data['grand_total_bits']}) != "
        f"L1D ({audit_data['l1d_total_bits']}) + "
        f"L2C ({audit_data['l2c_total_bits']}) + "
        f"LLC ({audit_data['llc_total_bits']}) = {computed_sum}"
    )


def test_budget_limit(audit_data):
    """Budget limit must be 524288 bits (64 KB)."""
    assert audit_data["budget_limit_bits"] == 524288


def test_compliant_flag(audit_data):
    """Submission must be identified as non-compliant (over budget)."""
    assert audit_data["compliant"] is False, (
        f"Expected compliant=False (total {EXPECTED['grand_total_bits']} > "
        f"budget {EXPECTED['budget_limit_bits']}), got {audit_data['compliant']}"
    )


def test_over_budget_bits(audit_data):
    """Over-budget amount must be exactly 132796 bits."""
    assert audit_data["over_budget_bits"] == EXPECTED["over_budget_bits"], (
        f"Over budget bits: expected {EXPECTED['over_budget_bits']}, "
        f"got {audit_data['over_budget_bits']}"
    )


def test_over_budget_consistency(audit_data):
    """over_budget_bits must equal grand_total_bits - budget_limit_bits."""
    expected_over = audit_data["grand_total_bits"] - audit_data["budget_limit_bits"]
    if expected_over < 0:
        expected_over = 0
    assert audit_data["over_budget_bits"] == expected_over, (
        f"over_budget_bits ({audit_data['over_budget_bits']}) != "
        f"grand_total ({audit_data['grand_total_bits']}) - "
        f"budget ({audit_data['budget_limit_bits']}) = {expected_over}"
    )
