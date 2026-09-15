
"""Verification tests for the RTL mutation adequacy pipeline.

These tests check that the pipeline correctly:
1. Applies mutations and runs Verilator simulations
2. Kills all non-equivalent mutations via targeted test vectors
3. Correctly identifies equivalent mutations (commutative operations)
4. Computes a correct mutation adequacy score
5. Generates a complete report with aggregate statistics
"""
import json
import os
import pytest

REPORT_PATH = "/app/results/report.json"
RESULTS_DIR = "/app/results"

TRULY_EQUIVALENT = {"mut_004", "mut_005"}
ALL_MUTATIONS = {f"mut_{i:03d}" for i in range(1, 9)}
NON_EQUIVALENT = ALL_MUTATIONS - TRULY_EQUIVALENT


@pytest.fixture(scope="module")
def report():
    """Load the pipeline report."""
    assert os.path.exists(REPORT_PATH), (
        f"Report not found at {REPORT_PATH}. "
        "The pipeline must run successfully before tests can verify results."
    )
    with open(REPORT_PATH) as f:
        return json.load(f)


def test_report_has_mutations(report):
    """Report must contain a 'mutations' array with exactly 8 entries."""
    assert "mutations" in report, "Report missing 'mutations' key"
    assert isinstance(report["mutations"], list), "'mutations' must be a list"
    assert len(report["mutations"]) == 8, (
        f"Expected 8 mutations, got {len(report['mutations'])}"
    )


def test_report_has_aggregate(report):
    """Report must contain an 'aggregate' object with scoring statistics."""
    assert "aggregate" in report, "Report missing 'aggregate' key"
    agg = report["aggregate"]
    assert "total_mutants" in agg, "Aggregate missing 'total_mutants'"
    assert "killed" in agg, "Aggregate missing 'killed'"
    assert "equivalent" in agg, "Aggregate missing 'equivalent'"
    assert "adequacy_score" in agg, "Aggregate missing 'adequacy_score'"


def test_simulation_logs_exist():
    """Simulation log files must exist for all 8 mutations."""
    for i in range(1, 9):
        mut_id = f"mut_{i:03d}"
        log_path = os.path.join(RESULTS_DIR, mut_id, "simulation.log")
        assert os.path.exists(log_path), (
            f"Missing simulation log for {mut_id} at {log_path}"
        )


def test_non_equivalent_mutations_killed(report):
    """All 6 non-equivalent mutations must be KILLED by the testbench."""
    mutations_by_id = {m["id"]: m for m in report["mutations"]}
    for mut_id in NON_EQUIVALENT:
        assert mut_id in mutations_by_id, (
            f"Missing mutation {mut_id} in report"
        )
        m = mutations_by_id[mut_id]
        assert m["status"] == "KILLED", (
            f"Non-equivalent mutation {mut_id} should be KILLED, "
            f"got '{m['status']}'. Title: {m['title']}"
        )


def test_equivalent_mutations_classified_correctly(report):
    """Equivalent mutations must have equivalent=true, others false."""
    mutations_by_id = {m["id"]: m for m in report["mutations"]}
    for mut_id in TRULY_EQUIVALENT:
        assert mut_id in mutations_by_id, (
            f"Missing mutation {mut_id} in report"
        )
        m = mutations_by_id[mut_id]
        assert m["equivalent"] is True, (
            f"Mutation {mut_id} is truly equivalent (commutative operation) "
            f"but classified as non-equivalent. Title: {m['title']}"
        )
    for mut_id in NON_EQUIVALENT:
        assert mut_id in mutations_by_id, (
            f"Missing mutation {mut_id} in report"
        )
        m = mutations_by_id[mut_id]
        assert m["equivalent"] is False, (
            f"Mutation {mut_id} is NOT equivalent but classified as "
            f"equivalent. Title: {m['title']}"
        )


def test_adequacy_score(report):
    """Adequacy score must be 1.0 (6 killed / (8 total - 2 equivalent))."""
    agg = report["aggregate"]
    assert agg["total_mutants"] == 8, (
        f"Expected 8 total mutants, got {agg['total_mutants']}"
    )
    assert agg["killed"] == 6, (
        f"Expected 6 killed mutants, got {agg['killed']}"
    )
    assert agg["equivalent"] == 2, (
        f"Expected 2 equivalent mutants, got {agg['equivalent']}"
    )
    assert abs(agg["adequacy_score"] - 1.0) < 1e-9, (
        f"Expected adequacy_score 1.0, got {agg['adequacy_score']}. "
        f"Formula should be killed/(total-equivalent) = 6/(8-2) = 1.0"
    )


def test_mutation_test_counts(report):
    """Test counts must be non-zero for all mutations (simulations ran)."""
    for m in report["mutations"]:
        assert m["tests"]["total"] > 0, (
            f"Mutation {m['id']}: total test count should be > 0 "
            f"(simulation should produce test results)"
        )


def test_killed_mutations_have_failures(report):
    """Killed mutations must have at least one test failure."""
    for m in report["mutations"]:
        if m["status"] == "KILLED":
            assert m["tests"]["failed"] > 0, (
                f"Mutation {m['id']} is KILLED but has 0 test failures"
            )


def test_survived_equivalents_no_failures(report):
    """Equivalent mutations that survived must have 0 test failures."""
    mutations_by_id = {m["id"]: m for m in report["mutations"]}
    for mut_id in TRULY_EQUIVALENT:
        m = mutations_by_id[mut_id]
        if m["status"] == "SURVIVED":
            assert m["tests"]["failed"] == 0, (
                f"Equivalent mutation {mut_id} survived but has "
                f"{m['tests']['failed']} test failures"
            )
