"""Tests for the OWASP Benchmark Scoring Pipeline output.

Verifies database schema conformity, table state, per-tool per-category
TP/FN/FP/TN counts, macro-averaged overall metrics, ranking order,
audit CSV output, jq summary report, and forensic evaluation report.
"""
import csv
import json
import os
import sqlite3
import pytest


DB_PATH = "/app/benchmark.db"


@pytest.fixture(scope="session")
def scorecard():
    path = "/app/output/scorecard.json"
    assert os.path.exists(path), f"Output file {path} does not exist"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def db():
    assert os.path.exists(DB_PATH), f"Database {DB_PATH} does not exist"
    conn = sqlite3.connect(DB_PATH)
    yield conn
    conn.close()


def get_tool(scorecard, name):
    for tool in scorecard["tools"]:
        if tool["name"] == name:
            return tool
    pytest.fail(f"Tool '{name}' not found in scorecard output")


# ===================================================================
# Schema Conformity Tests — verify database uses /app/schema.sql
# ===================================================================

class TestSchemaConformity:
    """Verify database was initialized from /app/schema.sql, not inline schemas."""

    def test_findings_has_id_column(self, db):
        """findings table must have id column (schema.sql defines AUTOINCREMENT)."""
        columns = {row[1] for row in db.execute("PRAGMA table_info(findings)").fetchall()}
        assert "id" in columns, (
            "findings table missing 'id' column — "
            "database was not initialized from /app/schema.sql"
        )

    def test_classifications_check_constraint(self):
        """classifications must enforce CHECK(classification IN ('TP','FN','FP','TN'))."""
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(
                "INSERT INTO classifications VALUES "
                "('__chk__', '__chk__', 'test', 'INVALID')"
            )
            conn.rollback()
            pytest.fail(
                "classifications accepted invalid value 'INVALID' — "
                "CHECK constraint from schema.sql not applied"
            )
        except sqlite3.IntegrityError:
            pass  # Expected: CHECK constraint rejected the value
        finally:
            conn.close()


# ===================================================================
# Database State Tests — verify SQLite tables are properly populated
# ===================================================================

class TestDatabaseState:
    def test_database_exists(self):
        assert os.path.exists(DB_PATH)

    def test_expected_results_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM expected_results").fetchone()[0]
        assert count == 120, f"Expected 120 test cases, got {count}"

    def test_tools_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM tools").fetchone()[0]
        assert count == 4, f"Expected 4 tools, got {count}"

    def test_findings_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
        assert count == 236, f"Expected 236 total findings, got {count}"

    def test_findings_preserves_duplicates(self, db):
        """ToolGamma has duplicate findings for test 001 and test 074."""
        gamma_001 = db.execute(
            "SELECT COUNT(*) FROM findings WHERE tool_name='ToolGamma' AND test_name='BenchmarkTest00001'"
        ).fetchone()[0]
        assert gamma_001 == 2, (
            f"ToolGamma test 001 should have 2 findings (CWE 78 + CWE 79), got {gamma_001}"
        )

    def test_classifications_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM classifications").fetchone()[0]
        assert count == 480, f"Expected 480 classifications (4 tools * 120 tests), got {count}"

    def test_category_metrics_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM category_metrics").fetchone()[0]
        assert count == 24, f"Expected 24 category metrics (4 tools * 6 categories), got {count}"

    def test_overall_metrics_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM overall_metrics").fetchone()[0]
        assert count == 4, f"Expected 4 overall metrics, got {count}"

    def test_classification_values_valid(self, db):
        invalid = db.execute(
            "SELECT COUNT(*) FROM classifications WHERE classification NOT IN ('TP','FN','FP','TN')"
        ).fetchone()[0]
        assert invalid == 0, "All classifications must be TP, FN, FP, or TN"

    def test_counts_sum_to_category_totals(self, db):
        """Per-tool category counts must sum to the number of test cases in that category."""
        category_sizes = {"cmdi": 20, "sqli": 25, "xss": 20, "crypto": 15, "hash": 20, "pathtraver": 20}
        for cat, expected_size in category_sizes.items():
            rows = db.execute(
                "SELECT tool_name, tp+fn+fp+tn FROM category_metrics WHERE category=?",
                (cat,)
            ).fetchall()
            for tool_name, total in rows:
                assert total == expected_size, (
                    f"{tool_name}/{cat}: tp+fn+fp+tn={total}, expected {expected_size}"
                )


# ===================================================================
# Output Structure Tests
# ===================================================================

class TestOutputStructure:
    def test_output_exists(self):
        assert os.path.exists("/app/output/scorecard.json")

    def test_valid_json_with_required_keys(self):
        with open("/app/output/scorecard.json") as f:
            data = json.load(f)
        assert "tools" in data
        assert "ranking" in data

    def test_four_tools_present(self, scorecard):
        assert len(scorecard["tools"]) == 4

    def test_six_categories_per_tool(self, scorecard):
        expected_cats = {"cmdi", "sqli", "xss", "crypto", "hash", "pathtraver"}
        for tool in scorecard["tools"]:
            cats = set(tool["categories"].keys())
            assert cats == expected_cats, (
                f"Tool {tool['name']} has categories {cats}, expected {expected_cats}"
            )

    def test_category_has_required_fields(self, scorecard):
        for tool in scorecard["tools"]:
            for cat_name, cat in tool["categories"].items():
                for field in ("tp", "fn", "fp", "tn", "tpr", "fpr"):
                    assert field in cat, (
                        f"{tool['name']}/{cat_name} missing field '{field}'"
                    )

    def test_overall_has_required_fields(self, scorecard):
        for tool in scorecard["tools"]:
            overall = tool["overall"]
            for field in ("macro_tpr", "macro_fpr", "youdens_j"):
                assert field in overall, (
                    f"{tool['name']} overall missing field '{field}'"
                )


# ===================================================================
# ToolAlpha Tests — good baseline tool
# ===================================================================

class TestToolAlpha:
    def test_cmdi_counts(self, scorecard):
        c = get_tool(scorecard, "ToolAlpha")["categories"]["cmdi"]
        assert c["tp"] == 10 and c["fn"] == 2 and c["fp"] == 2 and c["tn"] == 6

    def test_sqli_counts(self, scorecard):
        c = get_tool(scorecard, "ToolAlpha")["categories"]["sqli"]
        assert c["tp"] == 12 and c["fn"] == 3 and c["fp"] == 1 and c["tn"] == 9

    def test_xss_counts(self, scorecard):
        c = get_tool(scorecard, "ToolAlpha")["categories"]["xss"]
        assert c["tp"] == 8 and c["fn"] == 2 and c["fp"] == 2 and c["tn"] == 8

    def test_crypto_counts(self, scorecard):
        c = get_tool(scorecard, "ToolAlpha")["categories"]["crypto"]
        assert c["tp"] == 6 and c["fn"] == 2 and c["fp"] == 1 and c["tn"] == 6

    def test_hash_counts(self, scorecard):
        c = get_tool(scorecard, "ToolAlpha")["categories"]["hash"]
        assert c["tp"] == 8 and c["fn"] == 4 and c["fp"] == 2 and c["tn"] == 6

    def test_pathtraver_counts(self, scorecard):
        c = get_tool(scorecard, "ToolAlpha")["categories"]["pathtraver"]
        assert c["tp"] == 8 and c["fn"] == 2 and c["fp"] == 1 and c["tn"] == 9

    def test_crypto_rates(self, scorecard):
        c = get_tool(scorecard, "ToolAlpha")["categories"]["crypto"]
        assert c["tpr"] == pytest.approx(6 / 8, abs=1e-4)
        assert c["fpr"] == pytest.approx(1 / 7, abs=1e-4)

    def test_cmdi_rates(self, scorecard):
        c = get_tool(scorecard, "ToolAlpha")["categories"]["cmdi"]
        assert c["tpr"] == pytest.approx(10 / 12, abs=1e-4)
        assert c["fpr"] == pytest.approx(2 / 8, abs=1e-4)

    def test_overall_metrics(self, scorecard):
        o = get_tool(scorecard, "ToolAlpha")["overall"]
        assert o["macro_tpr"] == pytest.approx(0.7750, abs=1e-3)
        assert o["macro_fpr"] == pytest.approx(0.1738, abs=1e-3)
        assert o["youdens_j"] == pytest.approx(0.6012, abs=1e-3)


# ===================================================================
# AppScanLike Tests — CWE 327->328 exception via prefix matching
# ===================================================================

class TestAppScanLikeCWEException:
    """AppScanLike reports CWE 327 for hash tests (expected CWE 328).
    The CWE exception must accept CWE 327 as CWE 328 for AppScan* tools."""

    def test_hash_counts_with_exception(self, scorecard):
        c = get_tool(scorecard, "AppScanLike")["categories"]["hash"]
        assert c["tp"] == 8, (
            "CWE 327->328 exception must be applied for AppScan-prefixed tools"
        )
        assert c["fn"] == 4
        assert c["fp"] == 3
        assert c["tn"] == 5

    def test_hash_rates(self, scorecard):
        c = get_tool(scorecard, "AppScanLike")["categories"]["hash"]
        assert c["tpr"] == pytest.approx(8 / 12, abs=1e-4)
        assert c["fpr"] == pytest.approx(3 / 8, abs=1e-4)

    def test_crypto_unaffected_by_hash_exception(self, scorecard):
        c = get_tool(scorecard, "AppScanLike")["categories"]["crypto"]
        assert c["tp"] == 5 and c["fn"] == 3
        assert c["fp"] == 2 and c["tn"] == 5

    def test_cmdi_counts(self, scorecard):
        c = get_tool(scorecard, "AppScanLike")["categories"]["cmdi"]
        assert c["tp"] == 7 and c["fn"] == 5 and c["fp"] == 3 and c["tn"] == 5

    def test_sqli_counts(self, scorecard):
        c = get_tool(scorecard, "AppScanLike")["categories"]["sqli"]
        assert c["tp"] == 10 and c["fn"] == 5 and c["fp"] == 2 and c["tn"] == 8

    def test_overall_with_exception(self, scorecard):
        o = get_tool(scorecard, "AppScanLike")["overall"]
        assert o["macro_tpr"] == pytest.approx(0.6569, abs=1e-3)
        assert o["macro_fpr"] == pytest.approx(0.2893, abs=1e-3)
        assert o["youdens_j"] == pytest.approx(0.3677, abs=1e-3)


# ===================================================================
# ToolGamma Tests — duplicate findings must be preserved
# ===================================================================

class TestToolGammaDuplicates:
    """ToolGamma has duplicate findings: test 001 has CWE 78 + CWE 79,
    test 074 has CWE 327 + CWE 328. All findings must be stored and checked."""

    def test_cmdi_all_detected(self, scorecard):
        """Test 001 has two findings (CWE 78 correct, CWE 79 wrong). TP must be 12."""
        c = get_tool(scorecard, "ToolGamma")["categories"]["cmdi"]
        assert c["tp"] == 12 and c["fn"] == 0
        assert c["fp"] == 2 and c["tn"] == 6

    def test_crypto_counts(self, scorecard):
        """Test 074 has CWE 327 (matches crypto) + CWE 328.
        Both findings must be stored; CWE 327 matches expected 327 -> FP."""
        c = get_tool(scorecard, "ToolGamma")["categories"]["crypto"]
        assert c["tp"] == 3 and c["fn"] == 5
        assert c["fp"] == 6 and c["tn"] == 1

    def test_hash_counts(self, scorecard):
        c = get_tool(scorecard, "ToolGamma")["categories"]["hash"]
        assert c["tp"] == 9 and c["fn"] == 3
        assert c["fp"] == 5 and c["tn"] == 3

    def test_sqli_all_detected(self, scorecard):
        c = get_tool(scorecard, "ToolGamma")["categories"]["sqli"]
        assert c["tp"] == 15 and c["fn"] == 0

    def test_overall_gamma(self, scorecard):
        o = get_tool(scorecard, "ToolGamma")["overall"]
        assert o["macro_tpr"] == pytest.approx(0.8542, abs=1e-3)
        assert o["macro_fpr"] == pytest.approx(0.4887, abs=1e-3)
        assert o["youdens_j"] == pytest.approx(0.3655, abs=1e-3)


# ===================================================================
# ToolDelta Tests — conservative tool with zero-FP categories
# ===================================================================

class TestToolDelta:
    def test_cmdi_zero_fp(self, scorecard):
        c = get_tool(scorecard, "ToolDelta")["categories"]["cmdi"]
        assert c["tp"] == 4 and c["fn"] == 8
        assert c["fp"] == 0 and c["tn"] == 8
        assert c["fpr"] == pytest.approx(0.0, abs=1e-6)

    def test_xss_zero_fp(self, scorecard):
        c = get_tool(scorecard, "ToolDelta")["categories"]["xss"]
        assert c["tp"] == 4 and c["fn"] == 6
        assert c["fp"] == 0 and c["tn"] == 10

    def test_hash_zero_fp(self, scorecard):
        c = get_tool(scorecard, "ToolDelta")["categories"]["hash"]
        assert c["tp"] == 5 and c["fn"] == 7
        assert c["fp"] == 0 and c["tn"] == 8

    def test_overall_delta(self, scorecard):
        o = get_tool(scorecard, "ToolDelta")["overall"]
        assert o["macro_tpr"] == pytest.approx(0.4042, abs=1e-3)
        assert o["macro_fpr"] == pytest.approx(0.0571, abs=1e-3)
        assert o["youdens_j"] == pytest.approx(0.3470, abs=1e-3)


# ===================================================================
# Ranking Tests
# ===================================================================

class TestRanking:
    def test_ranking_order(self, scorecard):
        """Correct descending order by macro-averaged Youden's J."""
        names = [r["name"] for r in scorecard["ranking"]]
        assert names == ["ToolAlpha", "AppScanLike", "ToolGamma", "ToolDelta"]

    def test_ranking_descending_scores(self, scorecard):
        ranking = scorecard["ranking"]
        for i in range(len(ranking) - 1):
            assert ranking[i]["youdens_j"] >= ranking[i + 1]["youdens_j"]

    def test_rank_numbers(self, scorecard):
        for i, entry in enumerate(scorecard["ranking"]):
            assert entry["rank"] == i + 1

    def test_ranking_j_values(self, scorecard):
        ranking = scorecard["ranking"]
        expected = [
            ("ToolAlpha",    0.6012),
            ("AppScanLike",  0.3677),
            ("ToolGamma",    0.3655),
            ("ToolDelta",    0.3470),
        ]
        for entry, (name, j) in zip(ranking, expected):
            assert entry["name"] == name
            assert entry["youdens_j"] == pytest.approx(j, abs=2e-3)


# ===================================================================
# Macro vs Micro Averaging Test
# ===================================================================

class TestMacroAveraging:
    """With imbalanced category sizes, macro and micro averaging diverge."""

    def test_gamma_uses_macro_not_micro(self, scorecard):
        """Micro TPR for ToolGamma ~0.8806 vs macro ~0.8542."""
        o = get_tool(scorecard, "ToolGamma")["overall"]
        micro_tpr = 59 / 67
        macro_tpr = 0.8542
        assert abs(o["macro_tpr"] - macro_tpr) < abs(o["macro_tpr"] - micro_tpr)

    def test_gamma_fpr_uses_macro(self, scorecard):
        """Micro FPR ~0.4717 vs macro ~0.4887."""
        o = get_tool(scorecard, "ToolGamma")["overall"]
        micro_fpr = 25 / 53
        macro_fpr = 0.4887
        assert abs(o["macro_fpr"] - macro_fpr) < abs(o["macro_fpr"] - micro_fpr)


# ===================================================================
# Audit CSV Output Tests
# ===================================================================

class TestAuditOutput:
    def test_audit_csv_exists(self):
        assert os.path.exists("/app/output/audit.csv"), "audit.csv must be generated"

    def test_audit_csv_row_count(self):
        with open("/app/output/audit.csv") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)
        assert len(rows) == 24, f"audit.csv should have 24 data rows (4 tools * 6 categories), got {len(rows)}"

    def test_audit_csv_has_required_columns(self):
        with open("/app/output/audit.csv") as f:
            reader = csv.reader(f)
            header = next(reader)
        required = {"tool_name", "category", "tp", "fn", "fp", "tn", "tpr", "fpr",
                     "macro_tpr", "macro_fpr", "youdens_j"}
        actual = set(header)
        assert required.issubset(actual), f"Missing columns: {required - actual}"

    def test_audit_csv_sorted_by_youdens_j_desc(self):
        with open("/app/output/audit.csv") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        j_values = [float(r["youdens_j"]) for r in rows]
        first_j = j_values[0]
        last_j = j_values[-1]
        assert first_j >= last_j, "audit.csv should be sorted by youdens_j descending"


# ===================================================================
# Summary Report Tests — jq-generated report from scorecard
# ===================================================================

class TestSummaryReport:
    """Verify summary_report.json was generated using the fixed jq template."""

    @pytest.fixture(scope="class")
    def summary(self):
        path = "/app/output/summary_report.json"
        assert os.path.exists(path), "summary_report.json must be generated using jq"
        with open(path) as f:
            return json.load(f)

    def test_has_required_keys(self, summary):
        for key in ("top_tool", "tool_count", "average_j", "blind_spots"):
            assert key in summary, f"summary_report.json missing key '{key}'"

    def test_top_tool_name(self, summary):
        assert summary["top_tool"]["name"] == "ToolAlpha"

    def test_top_tool_j_value(self, summary):
        assert summary["top_tool"]["youdens_j"] == pytest.approx(0.6012, abs=1e-3)

    def test_tool_count(self, summary):
        assert summary["tool_count"] == 4

    def test_average_j(self, summary):
        assert summary["average_j"] == pytest.approx(0.4204, abs=1e-2)

    def test_no_blind_spots(self, summary):
        """No tool has TPR=0 in any category in the correct scorecard."""
        assert summary["blind_spots"] == []


# ===================================================================
# Evaluation Report Tests — forensic comparison with reference
# ===================================================================

class TestEvaluationReport:
    """Verify evaluation.json correctly identifies reference scorecard errors."""

    @pytest.fixture(scope="class")
    def evaluation(self):
        path = "/app/output/evaluation.json"
        assert os.path.exists(path), "evaluation.json must be generated"
        with open(path) as f:
            return json.load(f)

    def test_has_required_structure(self, evaluation):
        assert "incorrect_tools" in evaluation
        assert "discrepancies" in evaluation
        assert "root_cause" in evaluation

    def test_appscanlike_is_only_incorrect_tool(self, evaluation):
        assert evaluation["incorrect_tools"] == ["AppScanLike"]

    def test_discrepancies_exist(self, evaluation):
        assert len(evaluation["discrepancies"]) > 0

    def test_all_discrepancies_are_appscanlike(self, evaluation):
        for d in evaluation["discrepancies"]:
            assert d["tool"] == "AppScanLike", (
                f"Only AppScanLike should have discrepancies, found {d['tool']}"
            )

    def test_hash_category_flagged(self, evaluation):
        categories = {d["category"] for d in evaluation["discrepancies"]}
        assert "hash" in categories, "Hash category must be identified as having errors"

    def test_hash_tp_discrepancy(self, evaluation):
        """Reference has hash tp=0, correct is tp=8."""
        for d in evaluation["discrepancies"]:
            if d.get("category") == "hash" and d.get("field") == "tp":
                assert d["reference_value"] == 0, "Reference hash TP should be 0"
                assert d["correct_value"] == 8, "Correct hash TP should be 8"
                return
        pytest.fail("Missing discrepancy entry for AppScanLike hash tp field")

    def test_root_cause_mentions_prefix_matching(self, evaluation):
        rc = evaluation["root_cause"].lower()
        assert any(term in rc for term in ["prefix", "startswith", "starts_with"]), (
            "Root cause must mention prefix matching (startsWith vs exact equality)"
        )
