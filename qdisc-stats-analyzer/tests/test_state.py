"""
Tests for HTB Traffic Shaping Forensics task.

Validates that the agent correctly identified all three HTB
misconfigurations and produced a valid remediation script.

"""
import json
import os
import re
import pytest


@pytest.fixture(scope="session")
def diagnosis():
    path = "/app/diagnosis.json"
    assert os.path.exists(path), "diagnosis.json not found at /app/diagnosis.json"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def fix_sh():
    path = "/app/fix.sh"
    assert os.path.exists(path), "fix.sh not found at /app/fix.sh"
    with open(path) as f:
        return f.read()


# ---------- Diagnosis structure ----------

def test_diagnosis_has_issues_array(diagnosis):
    assert "issues" in diagnosis, "diagnosis.json must have 'issues' key"
    assert isinstance(diagnosis["issues"], list), "'issues' must be a list"


def test_diagnosis_at_least_three_issues(diagnosis):
    assert len(diagnosis["issues"]) >= 3, (
        f"Expected at least 3 issues, found {len(diagnosis['issues'])}")


def test_each_issue_has_required_fields(diagnosis):
    for i, issue in enumerate(diagnosis["issues"]):
        assert "affected_class" in issue, f"Issue {i} missing 'affected_class'"
        assert "root_cause" in issue, f"Issue {i} missing 'root_cause'"
        assert isinstance(issue["root_cause"], str), (
            f"Issue {i} 'root_cause' must be a string")


# ---------- VoIP filter misclassification ----------

def _find_issues_for_class(diagnosis, class_id):
    return [i for i in diagnosis["issues"]
            if i.get("affected_class") == class_id]


def test_voip_issue_identified(diagnosis):
    issues = _find_issues_for_class(diagnosis, "1:100")
    assert len(issues) >= 1, (
        "No issue found for VoIP class 1:100 — expected filter "
        "misclassification diagnosis")


def test_voip_root_cause_mentions_filter_or_dscp(diagnosis):
    issues = _find_issues_for_class(diagnosis, "1:100")
    rc = issues[0]["root_cause"].lower()
    keywords = ["filter", "dscp", "misclass", "classif", "0xb0",
                "0xb8", "tos", "match", "u32"]
    assert any(kw in rc for kw in keywords), (
        f"VoIP root_cause should reference filter/DSCP issue, "
        f"got: {issues[0]['root_cause'][:200]}")


def test_voip_misclassified_flows_listed(diagnosis):
    """The three DSCP-46 flows (F001, F002, F003) must appear in the issue."""
    issues = _find_issues_for_class(diagnosis, "1:100")
    issue_str = json.dumps(issues[0]).lower()
    for fid in ["f001", "f002", "f003"]:
        assert fid in issue_str, (
            f"Expected misclassified flow {fid.upper()} in VoIP issue")


# ---------- Web ceil misconfiguration ----------

def test_web_issue_identified(diagnosis):
    issues = _find_issues_for_class(diagnosis, "1:201")
    assert len(issues) >= 1, (
        "No issue found for Web class 1:201 — expected ceil "
        "misconfiguration diagnosis")


def test_web_root_cause_mentions_ceil(diagnosis):
    issues = _find_issues_for_class(diagnosis, "1:201")
    rc = issues[0]["root_cause"].lower()
    assert "ceil" in rc, (
        f"Web root_cause should mention ceil, "
        f"got: {issues[0]['root_cause'][:200]}")


# ---------- Quantum scheduling unfairness ----------

def test_quantum_issue_identified(diagnosis):
    issues_301 = _find_issues_for_class(diagnosis, "1:301")
    issues_300 = _find_issues_for_class(diagnosis, "1:300")
    assert len(issues_301) >= 1 or len(issues_300) >= 1, (
        "No issue found for quantum misconfiguration — expected "
        "1:301 or 1:300 affected")


def test_quantum_root_cause_mentions_quantum(diagnosis):
    issues = (_find_issues_for_class(diagnosis, "1:301")
              or _find_issues_for_class(diagnosis, "1:300"))
    rc = issues[0]["root_cause"].lower()
    assert "quantum" in rc, (
        f"Quantum root_cause should mention quantum, "
        f"got: {issues[0]['root_cause'][:200]}")


# ---------- fix.sh validation ----------

def test_fix_sh_not_empty(fix_sh):
    assert len(fix_sh.strip()) > 0, "fix.sh is empty"


def test_fix_voip_filter_correction(fix_sh):
    """fix.sh must contain a tc filter command with the correct DSCP EF
    value (0xb8 or equivalent)."""
    lower = fix_sh.lower()
    assert "tc filter" in lower, (
        "fix.sh should contain a tc filter command for VoIP fix")
    assert "b8" in lower, (
        "fix.sh should contain 0xb8 (ToS value for DSCP EF/46)")


def test_fix_web_ceil_correction(fix_sh):
    """fix.sh must update class 1:201 ceil to allow borrowing."""
    lower = fix_sh.lower()
    assert "1:201" in lower, "fix.sh should reference class 1:201"
    # Ceil should be increased (40Mbit in the design spec)
    assert "ceil" in lower, "fix.sh should set a ceil value"
    # Check that 40 appears (for 40Mbit or 40000000 etc.)
    assert "40" in lower, (
        "fix.sh should set Web ceil to 40Mbit (matching hierarchy spec)")


def test_fix_quantum_correction(fix_sh):
    """fix.sh must fix the quantum disparity for class 1:301."""
    lower = fix_sh.lower()
    assert "1:301" in lower, "fix.sh should reference class 1:301"
    assert "quantum" in lower, "fix.sh should set quantum value"
    quantum_match = re.search(r'quantum\s+(\d+)', lower)
    assert quantum_match, "fix.sh should have 'quantum <value>'"
    q_val = int(quantum_match.group(1))
    assert q_val <= 2000, (
        f"fix.sh quantum should be <= 2000 (standard ~1500), got {q_val}")


def test_fix_uses_inplace_commands(fix_sh):
    """fix.sh should use tc class change/replace, not full teardown."""
    lower = fix_sh.lower()
    has_change = "tc class change" in lower or "tc class replace" in lower
    assert has_change, (
        "fix.sh should use 'tc class change' or 'tc class replace' "
        "for in-place modification")
