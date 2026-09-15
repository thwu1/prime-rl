
"""Tests for the SARIF evaluation pipeline: jq filter, SQLite database, and JSON report."""

import json
import os
import sqlite3
import subprocess
import tempfile

import numpy as np
import pytest


RESULTS_JSON = "/app/results/evaluation.json"
RESULTS_DB = "/app/results/evaluation.db"
JQ_FILTER = "/app/pipeline/extract_rules.jq"


# ---------------------------------------------------------------
# Helper: run jq filter on a SARIF dict
# ---------------------------------------------------------------

def run_jq(sarif_data):
    """Run the jq filter on a SARIF dict and return sorted list of rule IDs."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(sarif_data, f)
        tmp_path = f.name
    try:
        result = subprocess.run(
            ['jq', '-r', '-f', JQ_FILTER, tmp_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            pytest.fail(f"jq filter failed with exit code {result.returncode}: {result.stderr}")
        lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
        return sorted(lines)
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------
# jq filter tests — basic SARIF processing
# ---------------------------------------------------------------

class TestJQFilter:
    """Verify the jq filter independently handles SARIF 2.1.0 edge cases."""

    def test_filter_exists(self):
        assert os.path.exists(JQ_FILTER), f"jq filter not found at {JQ_FILTER}"

    def test_ruleId_extraction(self):
        """Filter extracts rules referenced by ruleId, deduplicating multiple hits."""
        sarif = {
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "test", "rules": [
                    {"id": "alpha"}, {"id": "beta"}
                ]}},
                "results": [
                    {"ruleId": "alpha", "message": {"text": "m"}, "locations": []},
                    {"ruleId": "alpha", "message": {"text": "m"}, "locations": []},
                ]
            }]
        }
        assert run_jq(sarif) == ["alpha"]

    def test_ruleIndex_resolution(self):
        """Filter resolves ruleIndex to the rule ID from the same run's driver rules."""
        sarif = {
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "test", "rules": [
                    {"id": "first"}, {"id": "second"}, {"id": "third"}
                ]}},
                "results": [
                    {"ruleIndex": 2, "message": {"text": "m"}, "locations": []},
                ]
            }]
        }
        assert run_jq(sarif) == ["third"]

    def test_suppression_excluded(self):
        """Filter excludes results with non-empty suppressions array."""
        sarif = {
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "test", "rules": [
                    {"id": "kept"}, {"id": "suppressed_rule"}
                ]}},
                "results": [
                    {"ruleId": "kept", "message": {"text": "m"}, "locations": []},
                    {"ruleId": "suppressed_rule", "message": {"text": "m"}, "locations": [],
                     "suppressions": [{"kind": "inSource"}]},
                ]
            }]
        }
        assert run_jq(sarif) == ["kept"]

    def test_multirun_dedup(self):
        """Filter deduplicates rule IDs appearing across multiple SARIF runs."""
        sarif = {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": "test", "rules": [{"id": "shared"}]}},
                    "results": [
                        {"ruleId": "shared", "message": {"text": "m"}, "locations": []},
                    ]
                },
                {
                    "tool": {"driver": {"name": "test", "rules": [
                        {"id": "shared"}, {"id": "unique_rule"}
                    ]}},
                    "results": [
                        {"ruleId": "shared", "message": {"text": "m"}, "locations": []},
                        {"ruleId": "unique_rule", "message": {"text": "m"}, "locations": []},
                    ]
                }
            ]
        }
        assert run_jq(sarif) == ["shared", "unique_rule"]

    def test_empty_results(self):
        """Filter outputs nothing for an empty results array."""
        sarif = {
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "test", "rules": [{"id": "x"}]}},
                "results": []
            }]
        }
        assert run_jq(sarif) == []

    def test_mixed_ruleId_and_ruleIndex(self):
        """Filter handles a run with both ruleId and ruleIndex references."""
        sarif = {
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "test", "rules": [
                    {"id": "by-id"}, {"id": "by-index"}
                ]}},
                "results": [
                    {"ruleId": "by-id", "message": {"text": "m"}, "locations": []},
                    {"ruleIndex": 1, "message": {"text": "m"}, "locations": []},
                ]
            }]
        }
        assert run_jq(sarif) == ["by-id", "by-index"]

    def test_suppressed_ruleindex_excluded(self):
        """Suppression filtering works with ruleIndex references too."""
        sarif = {
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "test", "rules": [
                    {"id": "visible"}, {"id": "hidden"}
                ]}},
                "results": [
                    {"ruleIndex": 0, "message": {"text": "m"}, "locations": []},
                    {"ruleIndex": 1, "message": {"text": "m"}, "locations": [],
                     "suppressions": [{"kind": "inSource"}]},
                ]
            }]
        }
        assert run_jq(sarif) == ["visible"]


# ---------------------------------------------------------------
# jq filter tests — tool.extensions, kind, level
# ---------------------------------------------------------------

class TestJQFilterExtensions:
    """Verify the jq filter handles SARIF tool.extensions and result qualification."""

    def test_tool_extension_resolution(self):
        """Filter resolves ruleIndex via toolComponent to extension rules."""
        sarif = {
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": "test",
                        "rules": [{"id": "driver-rule-0"}]
                    },
                    "extensions": [{
                        "name": "custom-ext",
                        "rules": [
                            {"id": "ext-rule-0"},
                            {"id": "ext-rule-1"}
                        ]
                    }]
                },
                "results": [
                    {
                        "ruleIndex": 1,
                        "rule": {"toolComponent": {"name": "custom-ext", "index": 0}},
                        "message": {"text": "m"},
                        "locations": []
                    },
                ]
            }]
        }
        assert run_jq(sarif) == ["ext-rule-1"]

    def test_mixed_driver_and_extension_rules(self):
        """Filter handles both driver and extension rule references in the same run."""
        sarif = {
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": "test",
                        "rules": [{"id": "drv-001"}, {"id": "drv-002"}]
                    },
                    "extensions": [{
                        "name": "ext-a",
                        "rules": [{"id": "ext-001"}, {"id": "ext-002"}]
                    }]
                },
                "results": [
                    {"ruleId": "drv-001", "message": {"text": "m"}, "locations": []},
                    {
                        "ruleIndex": 0,
                        "rule": {"toolComponent": {"name": "ext-a", "index": 0}},
                        "message": {"text": "m"},
                        "locations": []
                    },
                ]
            }]
        }
        assert run_jq(sarif) == ["drv-001", "ext-001"]

    def test_suppressed_extension_result(self):
        """Suppression filtering works with extension-referenced results."""
        sarif = {
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {"name": "test", "rules": []},
                    "extensions": [{
                        "name": "ext",
                        "rules": [{"id": "ext-visible"}, {"id": "ext-hidden"}]
                    }]
                },
                "results": [
                    {
                        "ruleIndex": 0,
                        "rule": {"toolComponent": {"index": 0}},
                        "message": {"text": "m"},
                        "locations": []
                    },
                    {
                        "ruleIndex": 1,
                        "rule": {"toolComponent": {"index": 0}},
                        "message": {"text": "m"},
                        "locations": [],
                        "suppressions": [{"kind": "inSource"}]
                    },
                ]
            }]
        }
        assert run_jq(sarif) == ["ext-visible"]

    def test_kind_pass_excluded(self):
        """Filter excludes results with kind='pass' (rule checked, no match found)."""
        sarif = {
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "test", "rules": [
                    {"id": "rule-a"}, {"id": "rule-b"}
                ]}},
                "results": [
                    {"ruleId": "rule-a", "message": {"text": "m"}, "locations": []},
                    {"ruleId": "rule-b", "kind": "pass", "message": {"text": "m"}, "locations": []},
                ]
            }]
        }
        assert run_jq(sarif) == ["rule-a"]

    def test_kind_notApplicable_excluded(self):
        """Filter excludes results with kind='notApplicable'."""
        sarif = {
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "test", "rules": [
                    {"id": "rule-p"}
                ]}},
                "results": [
                    {"ruleId": "rule-p", "kind": "notApplicable",
                     "message": {"text": "m"}, "locations": []},
                ]
            }]
        }
        assert run_jq(sarif) == []

    def test_kind_fail_included(self):
        """Filter includes results with explicit kind='fail'."""
        sarif = {
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "test", "rules": [
                    {"id": "rule-q"}
                ]}},
                "results": [
                    {"ruleId": "rule-q", "kind": "fail",
                     "message": {"text": "m"}, "locations": []},
                ]
            }]
        }
        assert run_jq(sarif) == ["rule-q"]

    def test_level_none_excluded(self):
        """Filter excludes results with level='none' (informational only)."""
        sarif = {
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "test", "rules": [
                    {"id": "rule-x"}, {"id": "rule-y"}
                ]}},
                "results": [
                    {"ruleId": "rule-x", "message": {"text": "m"}, "locations": []},
                    {"ruleId": "rule-y", "level": "none",
                     "message": {"text": "m"}, "locations": []},
                ]
            }]
        }
        assert run_jq(sarif) == ["rule-x"]

    def test_level_error_included(self):
        """Filter includes results with level='error'."""
        sarif = {
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "test", "rules": [
                    {"id": "rule-err"}
                ]}},
                "results": [
                    {"ruleId": "rule-err", "level": "error",
                     "message": {"text": "m"}, "locations": []},
                ]
            }]
        }
        assert run_jq(sarif) == ["rule-err"]

    def test_combined_extension_kind_level(self):
        """Combined test: extension rules with kind and level filtering."""
        sarif = {
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {"name": "test", "rules": [{"id": "drv-a"}]},
                    "extensions": [{
                        "name": "ext",
                        "rules": [{"id": "ext-a"}, {"id": "ext-b"}, {"id": "ext-c"}]
                    }]
                },
                "results": [
                    # driver rule, normal — included
                    {"ruleId": "drv-a", "message": {"text": "m"}, "locations": []},
                    # extension rule 0, normal — included
                    {"ruleIndex": 0, "rule": {"toolComponent": {"index": 0}},
                     "message": {"text": "m"}, "locations": []},
                    # extension rule 1, kind=pass — excluded
                    {"ruleIndex": 1, "rule": {"toolComponent": {"index": 0}},
                     "kind": "pass", "message": {"text": "m"}, "locations": []},
                    # extension rule 2, level=none — excluded
                    {"ruleIndex": 2, "rule": {"toolComponent": {"index": 0}},
                     "level": "none", "message": {"text": "m"}, "locations": []},
                ]
            }]
        }
        assert run_jq(sarif) == ["drv-a", "ext-a"]


# ---------------------------------------------------------------
# SQLite database tests
# ---------------------------------------------------------------

class TestSQLiteDatabase:
    """Verify the SQLite database schema and content."""

    @pytest.fixture(scope="class")
    def db(self):
        assert os.path.exists(RESULTS_DB), f"Database not found at {RESULTS_DB}"
        conn = sqlite3.connect(RESULTS_DB)
        conn.row_factory = sqlite3.Row
        yield conn
        conn.close()

    def test_table_exists(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='instance_metrics'"
        )
        assert cursor.fetchone() is not None, "Table 'instance_metrics' not found"

    def test_schema_columns(self, db):
        cursor = db.execute("PRAGMA table_info(instance_metrics)")
        columns = {row["name"] for row in cursor.fetchall()}
        required = {
            "instance_name", "positive_rules_total", "positive_rules_matched",
            "negative_rules_total", "negative_rules_matched",
            "positive_ifr", "negative_ifr", "ifr",
            "test_passed", "test_failed", "test_total",
            "test_valid", "pass_score", "alignment",
            "phantom_positive_count", "phantom_negative_count"
        }
        missing = required - columns
        assert not missing, f"Missing columns in instance_metrics: {missing}"

    def test_instance_count(self, db):
        cursor = db.execute("SELECT COUNT(*) as cnt FROM instance_metrics")
        assert cursor.fetchone()["cnt"] == 6

    def test_instance_001_positive_matched(self, db):
        row = db.execute(
            "SELECT positive_rules_matched FROM instance_metrics WHERE instance_name='instance_001'"
        ).fetchone()
        assert row is not None and row[0] == 3

    def test_instance_002_positive_matched_ruleindex(self, db):
        """Instance 002 uses ruleIndex in SARIF; must resolve to 1 matched rule."""
        row = db.execute(
            "SELECT positive_rules_matched FROM instance_metrics WHERE instance_name='instance_002'"
        ).fetchone()
        assert row is not None and row[0] == 1

    def test_instance_003_positive_matched_dedup(self, db):
        """Instance 003 has multi-run SARIF; must deduplicate to 7 matched rules."""
        row = db.execute(
            "SELECT positive_rules_matched FROM instance_metrics WHERE instance_name='instance_003'"
        ).fetchone()
        assert row is not None and row[0] == 7

    def test_instance_004_positive_ifr_null(self, db):
        row = db.execute(
            "SELECT positive_ifr FROM instance_metrics WHERE instance_name='instance_004'"
        ).fetchone()
        assert row is not None and row[0] is None

    def test_instance_005_suppression_handling(self, db):
        """Instance 005 has a suppressed SARIF result; must not count it."""
        row = db.execute(
            "SELECT positive_rules_matched, negative_rules_matched "
            "FROM instance_metrics WHERE instance_name='instance_005'"
        ).fetchone()
        assert row is not None
        assert row["positive_rules_matched"] == 2, (
            f"Expected 2 matched positive rules (1 suppressed), got {row['positive_rules_matched']}"
        )
        assert row["negative_rules_matched"] == 2

    def test_instance_005_ifr(self, db):
        row = db.execute(
            "SELECT ifr FROM instance_metrics WHERE instance_name='instance_005'"
        ).fetchone()
        assert row is not None
        assert row[0] == pytest.approx(3 / 7, abs=1e-6)

    def test_instance_006_positive_matched(self, db):
        """Instance 006 has extension rules, kind/level filtering, and phantoms.
        Only 3 positive rules should be matched (1 via extension)."""
        row = db.execute(
            "SELECT positive_rules_matched FROM instance_metrics WHERE instance_name='instance_006'"
        ).fetchone()
        assert row is not None and row[0] == 3

    def test_instance_006_negative_matched(self, db):
        row = db.execute(
            "SELECT negative_rules_matched FROM instance_metrics WHERE instance_name='instance_006'"
        ).fetchone()
        assert row is not None and row[0] == 2

    def test_instance_006_phantom_positive(self, db):
        """Instance 006 has one phantom rule in positive SARIF."""
        row = db.execute(
            "SELECT phantom_positive_count FROM instance_metrics WHERE instance_name='instance_006'"
        ).fetchone()
        assert row is not None and row[0] == 1

    def test_instance_006_phantom_negative(self, db):
        """Instance 006 has no phantom rules in negative SARIF."""
        row = db.execute(
            "SELECT phantom_negative_count FROM instance_metrics WHERE instance_name='instance_006'"
        ).fetchone()
        assert row is not None and row[0] == 0

    def test_instance_006_ifr(self, db):
        """ifr = (3 matched + 1 avoided) / (5 + 3) = 4/8 = 0.5"""
        row = db.execute(
            "SELECT ifr FROM instance_metrics WHERE instance_name='instance_006'"
        ).fetchone()
        assert row is not None
        assert row[0] == pytest.approx(0.5, abs=1e-6)

    def test_instances_001_005_no_phantoms(self, db):
        """Instances 001-005 should have zero phantom rules."""
        rows = db.execute(
            "SELECT instance_name, phantom_positive_count, phantom_negative_count "
            "FROM instance_metrics WHERE instance_name != 'instance_006'"
        ).fetchall()
        for row in rows:
            assert row["phantom_positive_count"] == 0, (
                f"{row['instance_name']} has phantom_positive_count={row['phantom_positive_count']}"
            )
            assert row["phantom_negative_count"] == 0, (
                f"{row['instance_name']} has phantom_negative_count={row['phantom_negative_count']}"
            )


# ---------------------------------------------------------------
# JSON report fixtures
# ---------------------------------------------------------------

@pytest.fixture(scope="module")
def results():
    """Load the evaluation JSON report."""
    assert os.path.exists(RESULTS_JSON), (
        f"JSON report not found at {RESULTS_JSON}. Did you run the pipeline?"
    )
    with open(RESULTS_JSON) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def instances(results):
    assert "instances" in results, "Missing 'instances' key in JSON output"
    return results["instances"]


@pytest.fixture(scope="module")
def aggregate(results):
    assert "aggregate" in results, "Missing 'aggregate' key in JSON output"
    return results["aggregate"]


# ---------------------------------------------------------------
# JSON structure tests
# ---------------------------------------------------------------

class TestOutputStructure:
    def test_instance_count(self, instances):
        assert len(instances) == 6, f"Expected 6 instances, got {len(instances)}"

    def test_all_instances_present(self, instances):
        expected = {
            "instance_001", "instance_002", "instance_003",
            "instance_004", "instance_005", "instance_006"
        }
        assert set(instances.keys()) == expected

    def test_instance_keys(self, instances):
        required_keys = {
            "positive_rules_total", "positive_rules_matched",
            "negative_rules_total", "negative_rules_matched",
            "positive_ifr", "negative_ifr", "ifr",
            "test_passed", "test_failed", "test_total",
            "test_valid", "pass_score", "alignment",
            "phantom_positive_count", "phantom_negative_count",
        }
        for name, inst in instances.items():
            missing = required_keys - set(inst.keys())
            assert not missing, f"Instance {name} missing keys: {missing}"

    def test_aggregate_keys(self, aggregate):
        required_keys = {
            "mean_positive_ifr", "mean_negative_ifr", "mean_ifr",
            "mean_pass", "mean_alignment",
            "ci95_alignment", "ci95_ifr", "ci95_pass",
            "num_instances", "total_phantom_rules",
        }
        missing = required_keys - set(aggregate.keys())
        assert not missing, f"Aggregate missing keys: {missing}"


# ---------------------------------------------------------------
# Instance 001: rename-method
# 5 pos rules, 3 match; 4 neg rules, 1 match
# ---------------------------------------------------------------

class TestInstance001:
    @pytest.fixture(autouse=True)
    def setup(self, instances):
        self.inst = instances["instance_001"]

    def test_positive_rules(self):
        assert self.inst["positive_rules_total"] == 5
        assert self.inst["positive_rules_matched"] == 3

    def test_negative_rules(self):
        assert self.inst["negative_rules_total"] == 4
        assert self.inst["negative_rules_matched"] == 1

    def test_positive_ifr(self):
        assert self.inst["positive_ifr"] == pytest.approx(3 / 5, abs=1e-6)

    def test_negative_ifr(self):
        assert self.inst["negative_ifr"] == pytest.approx(3 / 4, abs=1e-6)

    def test_ifr(self):
        assert self.inst["ifr"] == pytest.approx(6 / 9, abs=1e-6)

    def test_test_metrics(self):
        assert self.inst["test_passed"] == 50
        assert self.inst["test_failed"] == 2
        assert self.inst["test_total"] == 55

    def test_test_valid(self):
        assert self.inst["test_valid"] is True

    def test_pass_and_alignment(self):
        assert self.inst["pass_score"] == pytest.approx(1.0)
        assert self.inst["alignment"] == pytest.approx(6 / 9, abs=1e-6)

    def test_no_phantoms(self):
        assert self.inst["phantom_positive_count"] == 0
        assert self.inst["phantom_negative_count"] == 0


# ---------------------------------------------------------------
# Instance 002: extract-interface (ruleIndex edge case)
# 3 pos rules, 1 match (via ruleIndex); 6 neg rules, 4 match
# ---------------------------------------------------------------

class TestInstance002:
    @pytest.fixture(autouse=True)
    def setup(self, instances):
        self.inst = instances["instance_002"]

    def test_ruleindex_positive_matched(self):
        """Must resolve ruleIndex=1 to pos-ext-002-impl-class."""
        assert self.inst["positive_rules_matched"] == 1

    def test_positive_ifr(self):
        assert self.inst["positive_ifr"] == pytest.approx(1 / 3, abs=1e-6)

    def test_negative_ifr(self):
        assert self.inst["negative_ifr"] == pytest.approx(2 / 6, abs=1e-6)

    def test_ifr(self):
        assert self.inst["ifr"] == pytest.approx(3 / 9, abs=1e-6)

    def test_test_metrics(self):
        assert self.inst["test_passed"] == 30
        assert self.inst["test_failed"] == 1

    def test_alignment(self):
        assert self.inst["alignment"] == pytest.approx(3 / 9, abs=1e-6)


# ---------------------------------------------------------------
# Instance 003: update-imports (multi-run SARIF, broken tests)
# 8 pos rules, 7 match (dedup across 2 SARIF runs); 2 neg, 0 match
# ---------------------------------------------------------------

class TestInstance003:
    @pytest.fixture(autouse=True)
    def setup(self, instances):
        self.inst = instances["instance_003"]

    def test_multirun_dedup(self):
        """pos-imp-001 appears in both SARIF runs; must deduplicate to 7."""
        assert self.inst["positive_rules_matched"] == 7

    def test_positive_ifr(self):
        assert self.inst["positive_ifr"] == pytest.approx(7 / 8, abs=1e-6)

    def test_negative_ifr(self):
        assert self.inst["negative_ifr"] == pytest.approx(1.0, abs=1e-6)

    def test_ifr(self):
        assert self.inst["ifr"] == pytest.approx(9 / 10, abs=1e-6)

    def test_test_metrics(self):
        assert self.inst["test_passed"] == 7
        assert self.inst["test_failed"] == 18
        assert self.inst["test_total"] == 25

    def test_test_invalid(self):
        """best_passed/total = 7/25 = 0.28 < 0.3 threshold."""
        assert self.inst["test_valid"] is False

    def test_alignment_zero(self):
        """Alignment must be 0.0 when tests are invalid, even if IFR is high."""
        assert self.inst["pass_score"] == pytest.approx(0.0)
        assert self.inst["alignment"] == pytest.approx(0.0)


# ---------------------------------------------------------------
# Instance 004: modernize-types (no positive rules)
# 0 pos rules; 3 neg rules, 0 match. positive_ifr = null.
# ---------------------------------------------------------------

class TestInstance004:
    @pytest.fixture(autouse=True)
    def setup(self, instances):
        self.inst = instances["instance_004"]

    def test_positive_ifr_null(self):
        assert self.inst["positive_ifr"] is None

    def test_negative_ifr(self):
        assert self.inst["negative_ifr"] == pytest.approx(1.0, abs=1e-6)

    def test_ifr(self):
        assert self.inst["ifr"] == pytest.approx(1.0, abs=1e-6)

    def test_test_metrics(self):
        assert self.inst["test_passed"] == 100
        assert self.inst["test_failed"] == 0

    def test_alignment(self):
        assert self.inst["alignment"] == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------
# Instance 005: inline-method (suppressed results)
# 4 pos rules, 2 effective match (1 suppressed); 3 neg rules, 2 match
# ---------------------------------------------------------------

class TestInstance005:
    @pytest.fixture(autouse=True)
    def setup(self, instances):
        self.inst = instances["instance_005"]

    def test_suppression_handling(self):
        """One positive SARIF result is suppressed; only 2 should count."""
        assert self.inst["positive_rules_total"] == 4
        assert self.inst["positive_rules_matched"] == 2

    def test_negative_rules(self):
        assert self.inst["negative_rules_total"] == 3
        assert self.inst["negative_rules_matched"] == 2

    def test_positive_ifr(self):
        assert self.inst["positive_ifr"] == pytest.approx(2 / 4, abs=1e-6)

    def test_negative_ifr(self):
        assert self.inst["negative_ifr"] == pytest.approx(1 / 3, abs=1e-6)

    def test_ifr(self):
        assert self.inst["ifr"] == pytest.approx(3 / 7, abs=1e-6)

    def test_test_metrics(self):
        assert self.inst["test_passed"] == 40
        assert self.inst["test_failed"] == 5
        assert self.inst["test_total"] == 45
        assert self.inst["test_valid"] is True

    def test_alignment(self):
        assert self.inst["pass_score"] == pytest.approx(1.0)
        assert self.inst["alignment"] == pytest.approx(3 / 7, abs=1e-6)


# ---------------------------------------------------------------
# Instance 006: extract-class
# 5 pos rules, 3 match (1 via extension, kind/level filter 2 others)
# 3 neg rules, 2 match
# 1 phantom positive rule, 0 phantom negative
# ---------------------------------------------------------------

class TestInstance006:
    @pytest.fixture(autouse=True)
    def setup(self, instances):
        self.inst = instances["instance_006"]

    def test_positive_rules_total(self):
        assert self.inst["positive_rules_total"] == 5

    def test_positive_rules_matched(self):
        """Only 3 of 5 positive rules match:
        - pos-cls-001: ruleId match
        - pos-cls-002: ruleId match
        - pos-cls-004: extension ruleIndex match
        - pos-cls-005: excluded (kind='pass')
        - pos-cls-003: excluded (level='none')
        """
        assert self.inst["positive_rules_matched"] == 3

    def test_negative_rules(self):
        assert self.inst["negative_rules_total"] == 3
        assert self.inst["negative_rules_matched"] == 2

    def test_positive_ifr(self):
        assert self.inst["positive_ifr"] == pytest.approx(3 / 5, abs=1e-6)

    def test_negative_ifr(self):
        assert self.inst["negative_ifr"] == pytest.approx(1 / 3, abs=1e-6)

    def test_ifr(self):
        """ifr = (3 matched + 1 avoided) / (5 + 3) = 4/8 = 0.5"""
        assert self.inst["ifr"] == pytest.approx(0.5, abs=1e-6)

    def test_test_metrics(self):
        assert self.inst["test_passed"] == 35
        assert self.inst["test_failed"] == 5
        assert self.inst["test_total"] == 40
        assert self.inst["test_valid"] is True

    def test_alignment(self):
        assert self.inst["pass_score"] == pytest.approx(1.0)
        assert self.inst["alignment"] == pytest.approx(0.5, abs=1e-6)

    def test_phantom_positive(self):
        """SARIF references 'phantom-quality-check' which is not in rules YAML."""
        assert self.inst["phantom_positive_count"] == 1

    def test_phantom_negative(self):
        assert self.inst["phantom_negative_count"] == 0


# ---------------------------------------------------------------
# Aggregate metrics (6 instances)
# ---------------------------------------------------------------

class TestAggregateMetrics:
    def test_num_instances(self, aggregate):
        assert aggregate["num_instances"] == 6

    def test_mean_ifr(self, aggregate):
        # IFR values: [6/9, 3/9, 9/10, 1.0, 3/7, 0.5]
        expected = (6/9 + 3/9 + 9/10 + 1.0 + 3/7 + 0.5) / 6
        assert aggregate["mean_ifr"] == pytest.approx(expected, abs=1e-4)

    def test_mean_positive_ifr(self, aggregate):
        # Instance 004 excluded (null positive_ifr)
        # Values: [3/5, 1/3, 7/8, 2/4, 3/5]
        expected = (3/5 + 1/3 + 7/8 + 2/4 + 3/5) / 5
        assert aggregate["mean_positive_ifr"] == pytest.approx(expected, abs=1e-4)

    def test_mean_negative_ifr(self, aggregate):
        # All 6: [3/4, 2/6, 1.0, 1.0, 1/3, 1/3]
        expected = (3/4 + 2/6 + 1.0 + 1.0 + 1/3 + 1/3) / 6
        assert aggregate["mean_negative_ifr"] == pytest.approx(expected, abs=1e-4)

    def test_mean_pass(self, aggregate):
        # [1.0, 1.0, 0.0, 1.0, 1.0, 1.0] → 5/6
        assert aggregate["mean_pass"] == pytest.approx(5/6, abs=1e-6)

    def test_mean_alignment(self, aggregate):
        # [6/9, 3/9, 0.0, 1.0, 3/7, 0.5]
        expected = (6/9 + 3/9 + 0.0 + 1.0 + 3/7 + 0.5) / 6
        assert aggregate["mean_alignment"] == pytest.approx(expected, abs=1e-4)

    def test_total_phantom_rules(self, aggregate):
        assert aggregate["total_phantom_rules"] == 1


# ---------------------------------------------------------------
# Bootstrap confidence intervals
# ---------------------------------------------------------------

def _bootstrap_ci(values, seed=42, n_bootstrap=10000):
    """Reference bootstrap CI computation."""
    rng = np.random.RandomState(seed)
    n = len(values)
    means = []
    for _ in range(n_bootstrap):
        sample = rng.choice(values, size=n, replace=True)
        means.append(float(np.mean(sample)))
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


class TestBootstrapCI:
    def test_ci95_alignment_structure(self, aggregate):
        ci = aggregate["ci95_alignment"]
        assert isinstance(ci, list) and len(ci) == 2

    def test_ci95_alignment_bounds(self, aggregate):
        ci = aggregate["ci95_alignment"]
        mean = aggregate["mean_alignment"]
        assert ci[0] < mean < ci[1], "CI must bracket the mean"
        assert ci[0] >= 0.0

    def test_ci95_alignment_values(self, aggregate):
        values = [6/9, 3/9, 0.0, 1.0, 3/7, 0.5]
        expected = _bootstrap_ci(values)
        ci = aggregate["ci95_alignment"]
        assert ci[0] == pytest.approx(expected[0], abs=0.02)
        assert ci[1] == pytest.approx(expected[1], abs=0.02)

    def test_ci95_ifr_structure(self, aggregate):
        ci = aggregate["ci95_ifr"]
        assert isinstance(ci, list) and len(ci) == 2

    def test_ci95_ifr_values(self, aggregate):
        values = [6/9, 3/9, 9/10, 1.0, 3/7, 0.5]
        expected = _bootstrap_ci(values)
        ci = aggregate["ci95_ifr"]
        assert ci[0] == pytest.approx(expected[0], abs=0.02)
        assert ci[1] == pytest.approx(expected[1], abs=0.02)

    def test_ci95_pass_structure(self, aggregate):
        ci = aggregate["ci95_pass"]
        assert isinstance(ci, list) and len(ci) == 2

    def test_ci95_pass_values(self, aggregate):
        values = [1.0, 1.0, 0.0, 1.0, 1.0, 1.0]
        expected = _bootstrap_ci(values)
        ci = aggregate["ci95_pass"]
        assert ci[0] == pytest.approx(expected[0], abs=0.02)
        assert ci[1] == pytest.approx(expected[1], abs=0.02)


# ---------------------------------------------------------------
# Cross-cutting edge case tests
# ---------------------------------------------------------------

class TestEdgeCases:
    def test_null_positive_ifr_excluded_from_mean(self, instances, aggregate):
        """Instance 004 has null positive_ifr; mean should exclude it."""
        non_null = [
            inst["positive_ifr"]
            for inst in instances.values()
            if inst["positive_ifr"] is not None
        ]
        assert len(non_null) == 5
        assert aggregate["mean_positive_ifr"] == pytest.approx(
            sum(non_null) / len(non_null), abs=1e-4
        )

    def test_alignment_zero_when_tests_invalid(self, instances):
        for name, inst in instances.items():
            if not inst["test_valid"]:
                assert inst["alignment"] == 0.0, (
                    f"Instance {name} has invalid tests but alignment != 0"
                )

    def test_alignment_equals_ifr_when_pass(self, instances):
        for name, inst in instances.items():
            if inst["pass_score"] == 1.0 and inst["ifr"] is not None:
                assert inst["alignment"] == pytest.approx(
                    inst["ifr"], abs=1e-6
                ), f"Instance {name}: alignment should equal ifr when pass=1"

    def test_suppressed_result_not_counted(self, instances):
        """Instance 005 has a suppressed positive result; verify it's excluded."""
        inst = instances["instance_005"]
        assert inst["positive_rules_matched"] == 2, (
            "Suppressed result must not count toward positive_rules_matched"
        )

    def test_phantom_excluded_from_matched(self, instances):
        """Instance 006 has a phantom positive rule; verify it's excluded from matched count."""
        inst = instances["instance_006"]
        assert inst["positive_rules_matched"] == 3, (
            "Phantom rule must not count toward positive_rules_matched"
        )
        assert inst["phantom_positive_count"] == 1, (
            "Phantom rule must be counted in phantom_positive_count"
        )

    def test_extension_rule_counted(self, instances):
        """Instance 006 has a rule matched via tool.extensions; verify it's counted."""
        inst = instances["instance_006"]
        # pos-cls-004 is resolved via extension ruleIndex, contributing to the
        # 3 matched positive rules. If extension handling fails, this would be 2.
        assert inst["positive_rules_matched"] == 3

    def test_kind_pass_not_counted(self, instances):
        """Instance 006 has a result with kind='pass'; verify it's not a match."""
        inst = instances["instance_006"]
        # If kind='pass' were incorrectly counted, positive_rules_matched would be 4
        assert inst["positive_rules_matched"] == 3

    def test_level_none_not_counted(self, instances):
        """Instance 006 has a result with level='none'; verify it's not a match."""
        inst = instances["instance_006"]
        # If level='none' were incorrectly counted, positive_rules_matched would be 4
        assert inst["positive_rules_matched"] == 3
