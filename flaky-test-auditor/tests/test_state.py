"""
Tests for IDoFT cross-dataset reconciliation engine.
Verifies that all cross-referential integrity violations are correctly identified.

"""

import json
import os
import subprocess
import pytest


REPORT_PATH = "/app/reconciliation_report.json"


@pytest.fixture(scope="module")
def report():
    """Load the reconciliation report."""
    assert os.path.exists(REPORT_PATH), (
        "Reconciliation report not found at /app/reconciliation_report.json"
    )
    with open(REPORT_PATH) as f:
        return json.load(f)


# --- Schema and structure ---

def test_schema_validation():
    """Report must pass jq-based schema validation."""
    result = subprocess.run(
        ["bash", "/app/validate.sh"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Schema validation failed: {result.stdout}"


def test_report_structure(report):
    """Report must have the required top-level structure."""
    assert "reconciliation_results" in report
    rr = report["reconciliation_results"]
    assert "total_violations" in rr
    assert "by_category" in rr
    assert "violations" in rr
    assert isinstance(rr["violations"], list)
    assert isinstance(rr["by_category"], dict)


def test_violations_count_matches(report):
    """Violations list length must equal total_violations."""
    rr = report["reconciliation_results"]
    assert len(rr["violations"]) == rr["total_violations"]


def test_by_category_sum_matches(report):
    """Sum of by_category values must equal total_violations."""
    rr = report["reconciliation_results"]
    cat_sum = sum(rr["by_category"].values())
    assert cat_sum == rr["total_violations"], (
        f"by_category sum ({cat_sum}) != total_violations ({rr['total_violations']})"
    )


# --- Total count ---

def test_total_violations(report):
    """Exactly 13 violations should be detected across all tables."""
    assert report["reconciliation_results"]["total_violations"] == 13, (
        f"Expected 13 total, got {report['reconciliation_results']['total_violations']}"
    )


# --- Per-category counts ---

def test_moved_to_gradle_count(report):
    count = report["reconciliation_results"]["by_category"].get(
        "moved_to_gradle_unmatched", 0)
    assert count == 2, f"Expected 2 moved_to_gradle_unmatched, got {count}"


def test_developer_fixed_count(report):
    count = report["reconciliation_results"]["by_category"].get(
        "developer_fixed_no_fix_record", 0)
    assert count == 2, f"Expected 2 developer_fixed_no_fix_record, got {count}"


def test_odr_category_mismatch_count(report):
    count = report["reconciliation_results"]["by_category"].get(
        "odr_category_mismatch", 0)
    assert count == 3, f"Expected 3 odr_category_mismatch, got {count}"


def test_odr_type_conflict_count(report):
    count = report["reconciliation_results"]["by_category"].get(
        "odr_type_conflict", 0)
    assert count == 2, f"Expected 2 odr_type_conflict, got {count}"


def test_orphaned_odr_count(report):
    count = report["reconciliation_results"]["by_category"].get(
        "orphaned_odr_reference", 0)
    assert count == 2, f"Expected 2 orphaned_odr_reference, got {count}"


def test_cross_build_duplicate_count(report):
    count = report["reconciliation_results"]["by_category"].get(
        "cross_build_duplicate", 0)
    assert count == 1, f"Expected 1 cross_build_duplicate, got {count}"


def test_orphaned_fix_record_count(report):
    count = report["reconciliation_results"]["by_category"].get(
        "orphaned_fix_record", 0)
    assert count == 1, f"Expected 1 orphaned_fix_record, got {count}"


# --- Helpers ---

def _violations_by_id(report, source_table, source_id):
    return [v for v in report["reconciliation_results"]["violations"]
            if v.get("source_table") == source_table
            and v.get("source_id") == source_id]


def _violations_by_category(report, category):
    return [v for v in report["reconciliation_results"]["violations"]
            if v["category"] == category]


# --- Specific violation spot-checks ---

def test_moved_to_gradle_elasticsearch(report):
    """pr_data row 7 (elasticsearch) has MovedToGradle but no gr_data match."""
    vs = _violations_by_id(report, "pr_data", 7)
    assert any(v["category"] == "moved_to_gradle_unmatched" for v in vs), (
        "Expected moved_to_gradle_unmatched at pr_data id=7"
    )


def test_moved_to_gradle_guava(report):
    """pr_data row 14 (guava) has MovedToGradle but no gr_data match."""
    vs = _violations_by_id(report, "pr_data", 14)
    assert any(v["category"] == "moved_to_gradle_unmatched" for v in vs), (
        "Expected moved_to_gradle_unmatched at pr_data id=14"
    )


def test_developer_fixed_dropwizard(report):
    """pr_data row 11 (dropwizard) has DeveloperFixed but no tic_fic entry."""
    vs = _violations_by_id(report, "pr_data", 11)
    assert any(v["category"] == "developer_fixed_no_fix_record" for v in vs), (
        "Expected developer_fixed_no_fix_record at pr_data id=11"
    )


def test_developer_fixed_guice_extensions(report):
    """pr_data row 23 (guice extensions) has DeveloperFixed but no tic_fic entry."""
    vs = _violations_by_id(report, "pr_data", 23)
    assert any(v["category"] == "developer_fixed_no_fix_record" for v in vs), (
        "Expected developer_fixed_no_fix_record at pr_data id=23"
    )


def test_odr_mismatch_retrofit(report):
    """pr_data row 4 (retrofit NOD) appears in odr_tests — category mismatch."""
    vs = _violations_by_id(report, "pr_data", 4)
    assert any(v["category"] == "odr_category_mismatch" for v in vs), (
        "Expected odr_category_mismatch at pr_data id=4"
    )


def test_odr_mismatch_spring_beans(report):
    """pr_data row 16 (spring-beans NOD) appears in odr_tests — category mismatch."""
    vs = _violations_by_id(report, "pr_data", 16)
    assert any(v["category"] == "odr_category_mismatch" for v in vs), (
        "Expected odr_category_mismatch at pr_data id=16"
    )


def test_odr_mismatch_rxjava_observable(report):
    """pr_data row 19 (RxJava NIO) appears in odr_tests — category mismatch."""
    vs = _violations_by_id(report, "pr_data", 19)
    assert any(v["category"] == "odr_category_mismatch" for v in vs), (
        "Expected odr_category_mismatch at pr_data id=19"
    )


def test_odr_type_conflict_hbase(report):
    """pr_data row 26 (hbase OD-Vic) but odr_tests says brittle — type conflict."""
    vs = _violations_by_id(report, "pr_data", 26)
    assert any(v["category"] == "odr_type_conflict" for v in vs), (
        "Expected odr_type_conflict at pr_data id=26"
    )


def test_odr_type_conflict_flink_table(report):
    """pr_data row 30 (flink OD-Brit) but odr_tests says victim — type conflict."""
    vs = _violations_by_id(report, "pr_data", 30)
    assert any(v["category"] == "odr_type_conflict" for v in vs), (
        "Expected odr_type_conflict at pr_data id=30"
    )


def test_orphaned_odr_mockito(report):
    """odr_tests row 14 (mockito) has no matching pr_data/gr_data entry."""
    vs = _violations_by_id(report, "odr_tests", 14)
    assert any(v["category"] == "orphaned_odr_reference" for v in vs), (
        "Expected orphaned_odr_reference at odr_tests id=14"
    )


def test_orphaned_odr_assertj(report):
    """odr_tests row 15 (assertj) has no matching pr_data/gr_data entry."""
    vs = _violations_by_id(report, "odr_tests", 15)
    assert any(v["category"] == "orphaned_odr_reference" for v in vs), (
        "Expected orphaned_odr_reference at odr_tests id=15"
    )


def test_cross_build_duplicate_flink(report):
    """flink TestTaskManager.testHeartbeat appears in both pr_data and gr_data."""
    vs = _violations_by_id(report, "pr_data", 20)
    assert any(v["category"] == "cross_build_duplicate" for v in vs), (
        "Expected cross_build_duplicate at pr_data id=20"
    )


def test_orphaned_fix_record_mockito(report):
    """tic_fic_data row 8 (mockito TestVerification) has no main table match."""
    vs = _violations_by_id(report, "tic_fic_data", 8)
    assert any(v["category"] == "orphaned_fix_record" for v in vs), (
        "Expected orphaned_fix_record at tic_fic_data id=8"
    )


# --- False positive checks (the buggy engine would flag these incorrectly) ---

def test_no_false_positive_hadoop_ndod(report):
    """pr_data row 13 (hadoop NDOD) is a different test from the hadoop odr entry
    and must NOT be flagged as odr_category_mismatch."""
    vs = _violations_by_id(report, "pr_data", 13)
    assert not any(v["category"] == "odr_category_mismatch" for v in vs), (
        "pr_data id=13 was falsely flagged: different test from odr hadoop entry"
    )


def test_no_false_positive_spring_nio(report):
    """pr_data row 6 (spring NIO) is a different test from the spring odr entries
    and must NOT be flagged as odr_category_mismatch."""
    vs = _violations_by_id(report, "pr_data", 6)
    assert not any(v["category"] == "odr_category_mismatch" for v in vs), (
        "pr_data id=6 was falsely flagged: different test from odr spring entries"
    )


def test_no_false_positive_flink_td(report):
    """pr_data row 9 (flink TD) is a different test from the flink odr entries
    and must NOT be flagged as odr_category_mismatch."""
    vs = _violations_by_id(report, "pr_data", 9)
    assert not any(v["category"] == "odr_category_mismatch" for v in vs), (
        "pr_data id=9 was falsely flagged: different test from odr flink entries"
    )


def test_no_false_positive_fastjson_nod(report):
    """pr_data row 27 (fastjson NOD TestJSONPath) is a different test from the
    fastjson odr entry (TestSerializer) and must NOT be flagged."""
    vs = _violations_by_id(report, "pr_data", 27)
    assert not any(v["category"] == "odr_category_mismatch" for v in vs), (
        "pr_data id=27 was falsely flagged: different test from odr fastjson entry"
    )


def test_correct_developer_fixed_not_flagged(report):
    """pr_data rows 3 and 17 have DeveloperFixed AND matching tic_fic entries,
    so they must NOT be flagged as developer_fixed_no_fix_record."""
    for row_id in [3, 17]:
        vs = _violations_by_id(report, "pr_data", row_id)
        assert not any(v["category"] == "developer_fixed_no_fix_record" for v in vs), (
            f"pr_data id={row_id} has a matching tic_fic entry and should not be flagged"
        )


def test_gr_developer_fixed_not_flagged(report):
    """gr_data row 7 has DeveloperFixed AND a matching tic_fic entry,
    so it must NOT be flagged."""
    vs = _violations_by_id(report, "gr_data", 7)
    assert not any(v["category"] == "developer_fixed_no_fix_record" for v in vs), (
        "gr_data id=7 has a matching tic_fic entry and should not be flagged"
    )
