"""Tests for HMDA validation pipeline cross-source reconciliation.

"""
import json
import os

import pytest

ALPHA_PATH = "/app/results/alpha_report.json"
BETA_PATH = "/app/results/beta_report.json"
GAMMA_PATH = "/app/results/gamma_report.json"


# ==================== FIXTURES ====================

@pytest.fixture
def alpha_report():
    if not os.path.exists(ALPHA_PATH):
        pytest.fail(f"{ALPHA_PATH} does not exist")
    with open(ALPHA_PATH) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            pytest.fail(f"Alpha report is not valid JSON: {e}")


@pytest.fixture
def beta_report():
    if not os.path.exists(BETA_PATH):
        pytest.fail(f"{BETA_PATH} does not exist")
    with open(BETA_PATH) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            pytest.fail(f"Beta report is not valid JSON: {e}")


@pytest.fixture
def gamma_report():
    if not os.path.exists(GAMMA_PATH):
        pytest.fail(f"{GAMMA_PATH} does not exist")
    with open(GAMMA_PATH) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            pytest.fail(f"Gamma report is not valid JSON: {e}")


# ==================== HELPERS ====================

def _violations_for(report, rule):
    return [v for v in report["violations"] if v["rule"] == rule]


def _qflags_for(report, rule):
    return [q for q in report["quality_flags"] if q["rule"] == rule]


# ==================== STRUCTURAL TESTS ====================

def test_alpha_report_exists():
    assert os.path.exists(ALPHA_PATH), "Alpha report not found"


def test_beta_report_exists():
    assert os.path.exists(BETA_PATH), "Beta report not found"


def test_gamma_report_exists():
    assert os.path.exists(GAMMA_PATH), "Gamma report not found"


def test_alpha_structure(alpha_report):
    assert isinstance(alpha_report.get("violations"), list)
    assert isinstance(alpha_report.get("quality_flags"), list)
    assert isinstance(alpha_report.get("summary"), dict)
    s = alpha_report["summary"]
    for key in ("total_lars", "violations_count", "quality_flags_count", "rules_triggered"):
        assert key in s, f"summary missing key: {key}"


def test_beta_structure(beta_report):
    assert isinstance(beta_report.get("violations"), list)
    assert isinstance(beta_report.get("quality_flags"), list)
    assert isinstance(beta_report.get("summary"), dict)


def test_gamma_structure(gamma_report):
    assert isinstance(gamma_report.get("violations"), list)
    assert isinstance(gamma_report.get("quality_flags"), list)
    assert isinstance(gamma_report.get("summary"), dict)


def test_violation_items_have_keys(alpha_report):
    for v in alpha_report["violations"]:
        for key in ("rule", "scope", "lar_index", "message"):
            assert key in v, f"Violation missing key '{key}': {v}"


def test_quality_flag_items_have_keys(alpha_report):
    for q in alpha_report["quality_flags"]:
        for key in ("rule", "lar_index", "message"):
            assert key in q, f"Quality flag missing key '{key}': {q}"


# ==================== ALPHA FILING TESTS ====================

def test_alpha_total_lars(alpha_report):
    assert alpha_report["summary"]["total_lars"] == 6


def test_alpha_violations_count(alpha_report):
    assert alpha_report["summary"]["violations_count"] == 3, (
        f"Expected 3 violations, got {alpha_report['summary']['violations_count']}"
    )


def test_alpha_quality_flags_count(alpha_report):
    assert alpha_report["summary"]["quality_flags_count"] == 2, (
        f"Expected 2 quality flags, got {alpha_report['summary']['quality_flags_count']}"
    )


def test_alpha_rules_triggered(alpha_report):
    expected = sorted(["Q601", "Q607", "V607", "V613_4", "V614_1"])
    actual = sorted(alpha_report["summary"]["rules_triggered"])
    assert actual == expected, f"rules_triggered mismatch:\n  expected: {expected}\n  actual:   {actual}"


def test_alpha_v607_ts(alpha_report):
    """V607 must check TS Tax ID format (not agency code)."""
    hits = _violations_for(alpha_report, "V607")
    assert len(hits) == 1, f"Expected 1 V607 violation, got {len(hits)}"
    assert hits[0]["scope"] == "ts"
    assert hits[0]["lar_index"] is None


def test_alpha_v614_1_lar3(alpha_report):
    """V614_1: refinancing + preapproval requested -> violation."""
    hits = _violations_for(alpha_report, "V614_1")
    assert len(hits) == 1, f"Expected 1 V614_1 violation, got {len(hits)}"
    assert hits[0]["lar_index"] == 3


def test_alpha_v613_4_lar6(alpha_report):
    """V613_4: preapproval=1 + action=5 (incomplete) -> violation."""
    hits = _violations_for(alpha_report, "V613_4")
    assert len(hits) == 1, f"Expected 1 V613_4 violation, got {len(hits)}"
    assert hits[0]["lar_index"] == 6


def test_alpha_q607_lar4(alpha_report):
    """Q607: subordinate lien + amount > threshold -> quality flag."""
    hits = _qflags_for(alpha_report, "Q607")
    assert len(hits) == 1, f"Expected 1 Q607 quality flag, got {len(hits)}"
    assert hits[0]["lar_index"] == 4


def test_alpha_q601_lar5(alpha_report):
    """Q601: application date > 2 years before action date -> quality flag."""
    hits = _qflags_for(alpha_report, "Q601")
    assert len(hits) == 1, f"Expected 1 Q601 quality flag, got {len(hits)}"
    assert hits[0]["lar_index"] == 5


def test_alpha_no_s301_violations(alpha_report):
    """S301 must use case-insensitive comparison; LAR 2 lowercase LEI is not a violation."""
    hits = _violations_for(alpha_report, "S301")
    assert len(hits) == 0, f"S301 should not fire (case-insensitive match), got {len(hits)} violations"


def test_alpha_no_violations_lar1(alpha_report):
    """LAR 1 is fully valid — no violations or quality flags."""
    v = [x for x in alpha_report["violations"] if x.get("lar_index") == 1]
    q = [x for x in alpha_report["quality_flags"] if x.get("lar_index") == 1]
    assert len(v) == 0, f"LAR 1 should have no violations: {v}"
    assert len(q) == 0, f"LAR 1 should have no quality flags: {q}"


def test_alpha_no_q634(alpha_report):
    """Q634 should not fire on alpha: home purchase originations (4) <= threshold (4)."""
    hits = _qflags_for(alpha_report, "Q634")
    assert len(hits) == 0, f"Q634 should not fire on alpha, got {len(hits)}"


# ==================== BETA FILING TESTS ====================

def test_beta_total_lars(beta_report):
    assert beta_report["summary"]["total_lars"] == 4


def test_beta_zero_violations(beta_report):
    assert beta_report["summary"]["violations_count"] == 0, (
        f"Beta should have 0 violations, got {beta_report['summary']['violations_count']}. "
        f"Violations: {beta_report['violations']}"
    )


def test_beta_zero_quality_flags(beta_report):
    assert beta_report["summary"]["quality_flags_count"] == 0, (
        f"Beta should have 0 quality flags, got {beta_report['summary']['quality_flags_count']}. "
        f"Flags: {beta_report['quality_flags']}"
    )


def test_beta_empty_rules_triggered(beta_report):
    assert beta_report["summary"]["rules_triggered"] == [], (
        f"Beta should trigger no rules, got {beta_report['summary']['rules_triggered']}"
    )


def test_beta_no_s301_false_positives(beta_report):
    """LAR 3 has lowercase LEI; case-insensitive S301 must not flag it."""
    hits = _violations_for(beta_report, "S301")
    assert len(hits) == 0, f"S301 false positive on beta LAR 3: {hits}"


def test_beta_no_q601_false_positives(beta_report):
    """LAR 4 has 12M amount; Q601 checks date recency, not amount."""
    hits = _qflags_for(beta_report, "Q601")
    assert len(hits) == 0, f"Q601 false positive on beta LAR 4: {hits}"


def test_beta_no_q634(beta_report):
    """Q634 should not fire on beta: home purchase originations (4) <= threshold (4)."""
    hits = _qflags_for(beta_report, "Q634")
    assert len(hits) == 0, f"Q634 should not fire on beta, got {len(hits)}"


# ==================== GAMMA FILING TESTS ====================

def test_gamma_total_lars(gamma_report):
    assert gamma_report["summary"]["total_lars"] == 6


def test_gamma_violations_count(gamma_report):
    assert gamma_report["summary"]["violations_count"] == 6, (
        f"Expected 6 violations, got {gamma_report['summary']['violations_count']}"
    )


def test_gamma_quality_flags_count(gamma_report):
    assert gamma_report["summary"]["quality_flags_count"] == 1, (
        f"Expected 1 quality flag, got {gamma_report['summary']['quality_flags_count']}"
    )


def test_gamma_rules_triggered(gamma_report):
    expected = sorted(["Q634", "S304", "S305", "V608_1", "V611", "V614_1", "V618"])
    actual = sorted(gamma_report["summary"]["rules_triggered"])
    assert actual == expected, f"rules_triggered mismatch:\n  expected: {expected}\n  actual:   {actual}"


def test_gamma_s304_filing(gamma_report):
    """S304: TS says 5 LARs but there are 6."""
    hits = _violations_for(gamma_report, "S304")
    assert len(hits) == 1
    assert hits[0]["scope"] == "filing"


def test_gamma_s305_filing(gamma_report):
    """S305: LAR 5 duplicates LAR 1 ULI."""
    hits = _violations_for(gamma_report, "S305")
    assert len(hits) >= 1
    for h in hits:
        assert h["scope"] == "filing"


def test_gamma_v611_lar2(gamma_report):
    """V611: loan type 5 invalid."""
    hits = _violations_for(gamma_report, "V611")
    assert len(hits) == 1
    assert hits[0]["lar_index"] == 2


def test_gamma_v608_1_lar3(gamma_report):
    """V608_1: ULI contains '@' (non-alphanumeric)."""
    hits = _violations_for(gamma_report, "V608_1")
    assert len(hits) == 1, f"Expected 1 V608_1, got {len(hits)}"
    assert hits[0]["lar_index"] == 3


def test_gamma_v614_1_lar4(gamma_report):
    """V614_1: purpose=Other + preapproval=requested -> violation."""
    hits = _violations_for(gamma_report, "V614_1")
    assert len(hits) == 1
    assert hits[0]["lar_index"] == 4


def test_gamma_v618_lar6(gamma_report):
    """V618: action date '20241345' is not a valid calendar date."""
    hits = _violations_for(gamma_report, "V618")
    assert len(hits) == 1
    assert hits[0]["lar_index"] == 6


def test_gamma_q634_filing(gamma_report):
    """Q634: Home purchase origination concentration exceeds threshold.
    5 originated home purchases > threshold(4), and 5/5 > ratio(0.80)."""
    hits = _qflags_for(gamma_report, "Q634")
    assert len(hits) == 1, f"Expected 1 Q634 quality flag on gamma, got {len(hits)}"
    assert hits[0]["lar_index"] is None, "Q634 is filing-level, lar_index should be null"
