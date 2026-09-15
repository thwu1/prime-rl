
import json
import os
import pytest


REPORT_PATH = "/app/audit_report.json"


def load_report():
    """Load and return the audit report JSON."""
    with open(REPORT_PATH, "r") as f:
        return json.load(f)


def find_entry(report, fragment):
    """Find a function entry whose key contains the given fragment (case-insensitive)."""
    funcs = report.get("functions", {})
    fragment_lower = fragment.lower().replace("_", "")
    for key, val in funcs.items():
        key_normalized = key.lower().replace("_", "").replace("-", "")
        if fragment_lower in key_normalized:
            return val
    return None


def has_issue_type(entry, *keywords):
    """Check if any issue's type or description contains one of the keywords."""
    if not entry or "issues" not in entry:
        return False
    for issue in entry["issues"]:
        issue_type = issue.get("type", "").lower()
        issue_desc = issue.get("description", "").lower()
        combined = issue_type + " " + issue_desc
        for kw in keywords:
            if kw.lower() in combined:
                return True
    return False


class TestReportExists:
    def test_file_exists(self):
        assert os.path.exists(REPORT_PATH), f"Audit report not found at {REPORT_PATH}"

    def test_valid_json(self):
        report = load_report()
        assert isinstance(report, dict), "Report must be a JSON object"
        assert "functions" in report, "Report must have a 'functions' key"


class TestReportStructure:
    def test_has_four_functions(self):
        report = load_report()
        funcs = report["functions"]
        assert len(funcs) >= 4, f"Expected at least 4 function entries, got {len(funcs)}"

    def test_bignum_add_present(self):
        report = load_report()
        entry = find_entry(report, "bignum_add")
        assert entry is not None, "No entry found for bignum_add"

    def test_mul_p25519_present(self):
        report = load_report()
        entry = find_entry(report, "mul_p25519")
        assert entry is not None, "No entry found for bignum_mul_p25519"

    def test_montmul_p256_present(self):
        report = load_report()
        entry = find_entry(report, "montmul_p256")
        assert entry is not None, "No entry found for bignum_montmul_p256"

    def test_montjmixadd_present(self):
        report = load_report()
        entry = find_entry(report, "montjmixadd")
        assert entry is not None, "No entry found for p256_montjmixadd"

    def test_entries_have_status(self):
        report = load_report()
        for name, entry in report["functions"].items():
            assert "status" in entry, f"Entry '{name}' missing 'status' field"
            assert entry["status"] in ("pass", "fail"), \
                f"Entry '{name}' has invalid status '{entry['status']}'"

    def test_entries_have_issues_list(self):
        report = load_report()
        for name, entry in report["functions"].items():
            assert "issues" in entry, f"Entry '{name}' missing 'issues' field"
            assert isinstance(entry["issues"], list), \
                f"Entry '{name}' issues must be a list"


class TestBignumAddBytecodeIssue:
    """bignum_add proof has a tampered machine code byte sequence."""

    def test_status_is_fail(self):
        report = load_report()
        entry = find_entry(report, "bignum_add")
        assert entry is not None, "No entry for bignum_add"
        assert entry["status"] == "fail", \
            "bignum_add should have status 'fail' due to bytecode tampering"

    def test_has_bytecode_issue(self):
        report = load_report()
        entry = find_entry(report, "bignum_add")
        assert entry is not None
        assert has_issue_type(entry, "bytecode", "mismatch", "byte", "machine_code",
                              "opcode", "xor", "r10", "r11", "encoding"), \
            f"bignum_add should report a bytecode mismatch issue. Issues found: {entry.get('issues', [])}"

    def test_has_at_least_one_issue(self):
        report = load_report()
        entry = find_entry(report, "bignum_add")
        assert entry is not None
        assert len(entry["issues"]) >= 1, "bignum_add should have at least one issue"


class TestMulP25519PostconditionIssue:
    """bignum_mul_p25519 proof has a weakened postcondition (MOD 2^256 instead of MOD p_25519)."""

    def test_status_is_fail(self):
        report = load_report()
        entry = find_entry(report, "mul_p25519")
        assert entry is not None, "No entry for bignum_mul_p25519"
        assert entry["status"] == "fail", \
            "bignum_mul_p25519 should have status 'fail' due to weakened postcondition"

    def test_has_postcondition_issue(self):
        report = load_report()
        entry = find_entry(report, "mul_p25519")
        assert entry is not None
        assert has_issue_type(entry, "postcondition", "spec", "modular", "modulus",
                              "p_25519", "p25519", "256", "reduction", "weak",
                              "field", "prime"), \
            f"bignum_mul_p25519 should report a postcondition weakness. Issues found: {entry.get('issues', [])}"


class TestMontmulP256Clean:
    """bignum_montmul_p256 proof is clean - no issues."""

    def test_status_is_pass(self):
        report = load_report()
        entry = find_entry(report, "montmul_p256")
        assert entry is not None, "No entry for bignum_montmul_p256"
        assert entry["status"] == "pass", \
            f"bignum_montmul_p256 should have status 'pass' (clean proof). Got: {entry}"

    def test_no_issues(self):
        report = load_report()
        entry = find_entry(report, "montmul_p256")
        assert entry is not None
        assert len(entry["issues"]) == 0, \
            f"bignum_montmul_p256 should have no issues. Got: {entry['issues']}"


class TestP256MontjmixaddPreconditionIssue:
    """p256_montjmixadd proof is missing a nonoverlapping precondition."""

    def test_status_is_fail(self):
        report = load_report()
        entry = find_entry(report, "montjmixadd")
        assert entry is not None, "No entry for p256_montjmixadd"
        assert entry["status"] == "fail", \
            "p256_montjmixadd should have status 'fail' due to missing precondition"

    def test_has_precondition_issue(self):
        report = load_report()
        entry = find_entry(report, "montjmixadd")
        assert entry is not None
        assert has_issue_type(entry, "precondition", "nonoverlapping", "overlap",
                              "aliasing", "constraint", "missing", "code",
                              "self-modif", "output"), \
            f"p256_montjmixadd should report a missing precondition. Issues found: {entry.get('issues', [])}"
