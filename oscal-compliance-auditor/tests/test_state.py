
import json
import os
import pytest


# ─── Expected values ───────────────────────────────────────────────────────

EXPECTED_CATALOG_IDS = sorted([
    "ac-1", "ac-2", "ac-2.1", "ac-2.2", "ac-2.3", "ac-2.4", "ac-2.5",
    "ac-3", "ac-3.1", "ac-4", "ac-5", "ac-6", "ac-6.1", "ac-6.2",
    "ac-7", "ac-8",
    "au-1", "au-2", "au-3", "au-3.1", "au-4", "au-5", "au-6", "au-6.1", "au-6.3",
    "si-1", "si-2", "si-2.1", "si-2.2", "si-3", "si-3.1",
    "si-4", "si-4.1", "si-4.2", "si-4.4", "si-4.5", "si-5",
])

EXPECTED_EFFECTIVE = sorted([
    "ac-1", "ac-2", "ac-2.1", "ac-2.3", "ac-2.4",
    "ac-3", "ac-4", "ac-5", "ac-6", "ac-6.1", "ac-7", "ac-8",
    "au-1", "au-2", "au-3", "au-3.1", "au-4", "au-5", "au-6", "au-6.1",
    "si-1", "si-2", "si-2.1", "si-3", "si-3.1",
    "si-4", "si-4.2", "si-4.4", "si-5",
])

EXPECTED_GAPS = sorted(["ac-5", "au-3.1", "au-6.1", "si-4.4"])

EXPECTED_STALE = sorted(["ac-2.2", "au-6.3", "si-4.1"])

EXPECTED_BROKEN_REFS = [
    {
        "control_id": "ac-2",
        "statement_id": "ac-2_smt.c",
        "component_uuid": "99999999-0000-4000-8000-000000000001"
    },
    {
        "control_id": "si-3",
        "statement_id": "si-3_smt.a",
        "component_uuid": "99999999-0000-4000-8000-000000000002"
    },
]

EXPECTED_PARAM_GAPS = [
    {"control_id": "au-5", "param_id": "au-5_prm_1"},
    {"control_id": "au-6", "param_id": "au-6_prm_2"},
]

EXPECTED_STMT_GAPS = [
    {"control_id": "au-1", "missing_statements": ["au-1_smt.b"]},
]

EXPECTED_FINDING_MAP = [
    {
        "finding_uuid": "f1000001-0000-4000-8000-000000000001",
        "target_control_id": "ac-6.1",
        "finding_status": "not-satisfied",
        "control_in_baseline": True,
        "control_implemented": True,
        "has_poam_entry": True,
        "poam_status": "open"
    },
    {
        "finding_uuid": "f2000002-0000-4000-8000-000000000002",
        "target_control_id": "au-5",
        "finding_status": "not-satisfied",
        "control_in_baseline": True,
        "control_implemented": True,
        "has_poam_entry": False,
        "poam_status": None
    },
    {
        "finding_uuid": "f3000003-0000-4000-8000-000000000003",
        "target_control_id": "si-3",
        "finding_status": "not-satisfied",
        "control_in_baseline": True,
        "control_implemented": True,
        "has_poam_entry": True,
        "poam_status": "investigating"
    },
    {
        "finding_uuid": "f4000004-0000-4000-8000-000000000004",
        "target_control_id": "ac-2",
        "finding_status": "satisfied",
        "control_in_baseline": True,
        "control_implemented": True,
        "has_poam_entry": False,
        "poam_status": None
    },
]

EXPECTED_UNTRACKED_RISKS = ["d2000002-0000-4000-8000-000000000002"]

EXPECTED_COVERAGE = {
    "total_poam_items": 3,
    "valid_poam_items": 2,
    "orphaned_poam_items": 1,
    "risks_tracked": 2,
    "risks_untracked": 1,
}


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def report():
    path = "/app/reconciliation_report.json"
    assert os.path.exists(path), \
        f"reconciliation_report.json not found at {path}"
    with open(path) as f:
        return json.load(f)


# ─── Tests ─────────────────────────────────────────────────────────────────

def test_report_has_all_sections(report):
    required = [
        "catalog_control_ids", "effective_controls",
        "implementation_gaps", "stale_implementations",
        "broken_component_refs", "parameter_gaps",
        "statement_coverage_gaps",
        "finding_control_map", "untracked_risks",
        "remediation_coverage",
    ]
    for field in required:
        assert field in report, f"Missing section: {field}"


def test_catalog_control_ids(report):
    actual = sorted(report["catalog_control_ids"])
    assert actual == EXPECTED_CATALOG_IDS, (
        f"Catalog control IDs mismatch.\n"
        f"  Missing: {sorted(set(EXPECTED_CATALOG_IDS) - set(actual))}\n"
        f"  Extra:   {sorted(set(actual) - set(EXPECTED_CATALOG_IDS))}"
    )


def test_catalog_control_count(report):
    assert len(report["catalog_control_ids"]) == 37, \
        f"Expected 37 catalog controls, got {len(report['catalog_control_ids'])}"


def test_effective_controls(report):
    actual = sorted(report["effective_controls"])
    assert actual == EXPECTED_EFFECTIVE, (
        f"Effective controls mismatch.\n"
        f"  Missing: {sorted(set(EXPECTED_EFFECTIVE) - set(actual))}\n"
        f"  Extra:   {sorted(set(actual) - set(EXPECTED_EFFECTIVE))}"
    )


def test_effective_control_count(report):
    assert len(report["effective_controls"]) == 29, \
        f"Expected 29 effective controls, got {len(report['effective_controls'])}"


def test_implementation_gaps(report):
    actual = sorted(report["implementation_gaps"])
    assert actual == EXPECTED_GAPS, (
        f"Implementation gaps mismatch.\n"
        f"  Expected: {EXPECTED_GAPS}\n"
        f"  Actual:   {actual}"
    )


def test_stale_implementations(report):
    actual = sorted(report["stale_implementations"])
    assert actual == EXPECTED_STALE, (
        f"Stale implementations mismatch.\n"
        f"  Expected: {EXPECTED_STALE}\n"
        f"  Actual:   {actual}"
    )


def test_broken_component_refs_count(report):
    assert len(report["broken_component_refs"]) == 2, \
        f"Expected 2 broken component refs, got {len(report['broken_component_refs'])}"


def test_broken_component_refs_content(report):
    actual = sorted(report["broken_component_refs"],
                    key=lambda x: (x["control_id"], x["statement_id"]))
    for i, (a, e) in enumerate(zip(actual, EXPECTED_BROKEN_REFS)):
        assert a["control_id"] == e["control_id"], \
            f"Broken ref {i}: control_id {a['control_id']} != {e['control_id']}"
        assert a["statement_id"] == e["statement_id"], \
            f"Broken ref {i}: statement_id {a['statement_id']} != {e['statement_id']}"
        assert a["component_uuid"] == e["component_uuid"], \
            f"Broken ref {i}: component_uuid {a['component_uuid']} != {e['component_uuid']}"


def test_parameter_gaps(report):
    actual = sorted(report["parameter_gaps"],
                    key=lambda x: (x["control_id"], x["param_id"]))
    assert len(actual) == len(EXPECTED_PARAM_GAPS), \
        f"Expected {len(EXPECTED_PARAM_GAPS)} parameter gaps, got {len(actual)}"
    for a, e in zip(actual, EXPECTED_PARAM_GAPS):
        assert a == e, f"Parameter gap mismatch: {a} != {e}"


def test_statement_coverage_gaps(report):
    actual = sorted(report["statement_coverage_gaps"],
                    key=lambda x: x["control_id"])
    assert len(actual) == len(EXPECTED_STMT_GAPS), \
        f"Expected {len(EXPECTED_STMT_GAPS)} statement coverage gaps, got {len(actual)}"
    for a, e in zip(actual, EXPECTED_STMT_GAPS):
        assert a["control_id"] == e["control_id"], \
            f"Statement gap control_id: {a['control_id']} != {e['control_id']}"
        assert sorted(a["missing_statements"]) == sorted(e["missing_statements"]), \
            f"Statement gap for {e['control_id']}: {a['missing_statements']} != {e['missing_statements']}"


def test_finding_control_map_count(report):
    assert len(report["finding_control_map"]) == 4, \
        f"Expected 4 finding entries, got {len(report['finding_control_map'])}"


def test_finding_control_map_content(report):
    actual = sorted(report["finding_control_map"],
                     key=lambda x: x["finding_uuid"])
    expected = sorted(EXPECTED_FINDING_MAP,
                       key=lambda x: x["finding_uuid"])
    for i, (a, e) in enumerate(zip(actual, expected)):
        assert a["finding_uuid"] == e["finding_uuid"], \
            f"Finding {i}: UUID mismatch"
        assert a["target_control_id"] == e["target_control_id"], \
            f"Finding {e['finding_uuid']}: target_control_id {a['target_control_id']} != {e['target_control_id']}"
        assert a["finding_status"] == e["finding_status"], \
            f"Finding {e['finding_uuid']}: finding_status {a['finding_status']} != {e['finding_status']}"
        assert a["control_in_baseline"] == e["control_in_baseline"], \
            f"Finding {e['finding_uuid']}: control_in_baseline {a['control_in_baseline']} != {e['control_in_baseline']}"
        assert a["control_implemented"] == e["control_implemented"], \
            f"Finding {e['finding_uuid']}: control_implemented {a['control_implemented']} != {e['control_implemented']}"
        assert a["has_poam_entry"] == e["has_poam_entry"], \
            f"Finding {e['finding_uuid']}: has_poam_entry {a['has_poam_entry']} != {e['has_poam_entry']}"
        assert a["poam_status"] == e["poam_status"], \
            f"Finding {e['finding_uuid']}: poam_status {a['poam_status']} != {e['poam_status']}"


def test_untracked_risks(report):
    actual = sorted(report["untracked_risks"])
    assert actual == EXPECTED_UNTRACKED_RISKS, (
        f"Untracked risks mismatch.\n"
        f"  Expected: {EXPECTED_UNTRACKED_RISKS}\n"
        f"  Actual:   {actual}"
    )


def test_remediation_coverage(report):
    actual = report["remediation_coverage"]
    for key, expected_val in EXPECTED_COVERAGE.items():
        assert key in actual, f"Missing remediation_coverage key: {key}"
        assert actual[key] == expected_val, \
            f"remediation_coverage[{key}]: {actual[key]} != {expected_val}"
