"""
Verification tests for the sqllogictest runner.

"""

import subprocess
import os
import pytest

TEST_FILES_DIR = "/app/test_files"
RUNNER = "/app/sqllogictest_runner.py"
TIMEOUT = 60


def run_runner(test_file, timeout=TIMEOUT):
    """Run the sqllogictest runner on a test file and return the result."""
    result = subprocess.run(
        ["python3", RUNNER, test_file],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


class TestRunnerExists:
    """Verify the runner exists and has basic CLI behavior."""

    def test_runner_file_exists(self):
        assert os.path.exists(RUNNER), f"Runner not found at {RUNNER}"

    def test_runner_nonexistent_file(self):
        result = subprocess.run(
            ["python3", RUNNER, "/nonexistent/file.test"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0, "Should fail on nonexistent file"


class TestPassingFiles:
    """Test files that must pass (exit code 0)."""

    @pytest.mark.parametrize(
        "test_file",
        [
            "01_basic.test",
            "02_sorting.test",
            "03_nulls.test",
            "04_hashing.test",
            "05_loops.test",
            "06_regex.test",
            "07_labels.test",
            "08_error_matching.test",
            "10_combined.test",
            "11_connections.test",
            "12_explain_verify.test",
            "13_reconnect.test",
            "14_interactions.test",
            "15_mode_verify.test",
            "16_mode_skip.test",
        ],
    )
    def test_should_pass(self, test_file):
        filepath = os.path.join(TEST_FILES_DIR, test_file)
        result = run_runner(filepath)
        assert result.returncode == 0, (
            f"{test_file} should pass but failed.\n"
            f"stdout: {result.stdout[-500:]}\n"
            f"stderr: {result.stderr[-500:]}"
        )


class TestRequireSkip:
    """Test that require directive properly skips unavailable extensions."""

    def test_require_nonexistent_extension_skips(self):
        filepath = os.path.join(TEST_FILES_DIR, "09_require_skip.test")
        result = run_runner(filepath)
        assert result.returncode == 0, (
            "Test with 'require nonexistent_extension_xyz_999' should be "
            "skipped (exit 0), not fail.\n"
            f"stdout: {result.stdout[-500:]}\n"
            f"stderr: {result.stderr[-500:]}"
        )


class TestFailingFiles:
    """Test files that must fail (non-zero exit code)."""

    def test_wrong_result_fails(self):
        filepath = os.path.join(TEST_FILES_DIR, "fail_wrong_result.test")
        result = run_runner(filepath)
        assert result.returncode != 0, (
            "fail_wrong_result.test has wrong expected results and "
            "should fail, but the runner reported success.\n"
            f"stdout: {result.stdout[-500:]}"
        )

    def test_bad_error_message_fails(self):
        filepath = os.path.join(TEST_FILES_DIR, "fail_bad_error.test")
        result = run_runner(filepath)
        assert result.returncode != 0, (
            "fail_bad_error.test has wrong error message expectation and "
            "should fail, but the runner reported success.\n"
            f"stdout: {result.stdout[-500:]}"
        )


class TestFeatureVerification:
    """Verify specific features produce correct results by running
    isolated test snippets through the runner."""

    def _write_and_run(self, content, filename="temp_test.test"):
        """Write a temporary test file and run it."""
        filepath = os.path.join("/tmp", filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        result = run_runner(filepath)
        os.remove(filepath)
        return result

    # --- Basic features ---

    def test_null_representation(self):
        result = self._write_and_run(
            "query I\nSELECT NULL::INTEGER\n----\nNULL\n"
        )
        assert result.returncode == 0, (
            f"NULL should render as 'NULL'.\nstderr: {result.stderr[-300:]}"
        )

    def test_empty_string_representation(self):
        result = self._write_and_run(
            "query T\nSELECT ''\n----\n(empty)\n"
        )
        assert result.returncode == 0, (
            f"Empty string should render as '(empty)'.\nstderr: {result.stderr[-300:]}"
        )

    def test_hash_single_column(self):
        result = self._write_and_run(
            "query I\nSELECT * FROM range(10) t(i)\n----\n"
            "10 values hashing to e20b902b49a98b1a05ed62804c757f94\n"
        )
        assert result.returncode == 0, (
            f"Hash verification for range(10) failed.\nstderr: {result.stderr[-300:]}"
        )

    def test_hash_multi_column(self):
        result = self._write_and_run(
            "query II\nSELECT i, i*i FROM range(10) t(i)\n----\n"
            "20 values hashing to 726adea2fb076db15567b4c5b0bb30c3\n"
        )
        assert result.returncode == 0, (
            f"Hash verification for 2-col range(10) failed.\nstderr: {result.stderr[-300:]}"
        )

    def test_wrong_hash_fails(self):
        result = self._write_and_run(
            "query I\nSELECT * FROM range(10) t(i)\n----\n"
            "10 values hashing to 0000000000000000000000000000dead\n"
        )
        assert result.returncode != 0, "Wrong hash should cause failure"

    def test_rowsort_order_independent(self):
        result = self._write_and_run(
            "query I rowsort\n"
            "SELECT * FROM (VALUES (3), (1), (2)) t(x)\n"
            "----\n1\n2\n3\n"
        )
        assert result.returncode == 0, (
            f"rowsort should pass.\nstderr: {result.stderr[-300:]}"
        )

    def test_label_equivalence(self):
        result = self._write_and_run(
            "query I nosort eq1\nSELECT 42\n----\n\n"
            "query I nosort eq1\nSELECT 42\n----\n"
        )
        assert result.returncode == 0, (
            f"Same label, same result should pass.\nstderr: {result.stderr[-300:]}"
        )

    def test_label_mismatch_fails(self):
        result = self._write_and_run(
            "query I nosort eq2\nSELECT 1\n----\n\n"
            "query I nosort eq2\nSELECT 2\n----\n"
        )
        assert result.returncode != 0, (
            "Same label, different result should fail"
        )

    def test_loop_variable_substitution(self):
        result = self._write_and_run(
            "statement ok\nCREATE TABLE lv(x INTEGER)\n\n"
            "loop i 0 3\n\n"
            "statement ok\nINSERT INTO lv VALUES (${i})\n\n"
            "endloop\n\n"
            "query I\nSELECT SUM(x) FROM lv\n----\n3\n"
        )
        assert result.returncode == 0, (
            f"Loop sum(0+1+2)=3 should pass.\nstderr: {result.stderr[-300:]}"
        )

    def test_foreach_substitution(self):
        result = self._write_and_run(
            "foreach val 10 20 30\n\n"
            "statement ok\nSELECT ${val}\n\n"
            "endforeach\n"
        )
        assert result.returncode == 0, (
            f"Foreach should pass.\nstderr: {result.stderr[-300:]}"
        )

    def test_error_substring_matching(self):
        result = self._write_and_run(
            "statement error\n"
            "DROP TABLE nonexistent_xyz_table\n"
            "----\n"
            "does not exist\n"
        )
        assert result.returncode == 0, (
            f"Error substring match should pass.\nstderr: {result.stderr[-300:]}"
        )

    def test_statement_ok_failure_detected(self):
        result = self._write_and_run(
            "statement ok\n"
            "THIS IS INVALID SQL\n"
        )
        assert result.returncode != 0, (
            "statement ok with invalid SQL should fail"
        )

    def test_regex_matching(self):
        result = self._write_and_run(
            "query T\nSELECT 'abc123def'\n----\n<REGEX>:abc\\d+def\n"
        )
        assert result.returncode == 0, (
            f"Regex match should pass.\nstderr: {result.stderr[-300:]}"
        )

    def test_valuesort_flattening(self):
        result = self._write_and_run(
            "query IT valuesort\n"
            "SELECT * FROM (VALUES (2, 'b'), (1, 'a')) t(x, y)\n"
            "----\n1\n2\na\nb\n"
        )
        assert result.returncode == 0, (
            f"valuesort should flatten and sort.\nstderr: {result.stderr[-300:]}"
        )

    def test_multiline_sql(self):
        result = self._write_and_run(
            "statement ok\n"
            "CREATE TABLE ml(\n"
            "    a INTEGER,\n"
            "    b VARCHAR\n"
            ")\n\n"
            "statement ok\nDROP TABLE ml\n"
        )
        assert result.returncode == 0, (
            f"Multi-line SQL should work.\nstderr: {result.stderr[-300:]}"
        )

    # --- Negative regex ---

    def test_negative_regex_matching(self):
        result = self._write_and_run(
            "query T\nSELECT 'hello world'\n----\n<!REGEX>:\\d+\n"
        )
        assert result.returncode == 0, (
            f"Negative regex should pass when pattern absent.\n"
            f"stderr: {result.stderr[-300:]}"
        )

    def test_negative_regex_fails_when_present(self):
        result = self._write_and_run(
            "query T\nSELECT 'abc123'\n----\n<!REGEX>:\\d+\n"
        )
        assert result.returncode != 0, (
            "Negative regex should fail when pattern IS present"
        )

    # --- Multi-connection ---

    def test_multi_connection_shared_tables(self):
        result = self._write_and_run(
            "statement ok\nCREATE TABLE mcs(x INTEGER)\n\n"
            "statement ok\nINSERT INTO mcs VALUES (42)\n\n"
            "query I @other\nSELECT x FROM mcs\n----\n42\n\n"
            "statement ok\nDROP TABLE mcs\n"
        )
        assert result.returncode == 0, (
            f"Named connection should see shared table.\n"
            f"stderr: {result.stderr[-300:]}"
        )

    def test_multi_connection_write_read(self):
        result = self._write_and_run(
            "statement ok\nCREATE TABLE mcw(x INTEGER)\n\n"
            "statement ok @writer\nINSERT INTO mcw VALUES (7)\n\n"
            "query I @reader\nSELECT x FROM mcw\n----\n7\n\n"
            "statement ok\nDROP TABLE mcw\n"
        )
        assert result.returncode == 0, (
            f"Write on one connection, read on another should work.\n"
            f"stderr: {result.stderr[-300:]}"
        )

    def test_multi_connection_in_query(self):
        result = self._write_and_run(
            "statement ok\nCREATE TABLE mcq(v INTEGER)\n\n"
            "statement ok\nINSERT INTO mcq VALUES (1), (2), (3)\n\n"
            "query I @c1\nSELECT SUM(v) FROM mcq\n----\n6\n\n"
            "statement ok\nDROP TABLE mcq\n"
        )
        assert result.returncode == 0, (
            f"Query on named connection should work.\n"
            f"stderr: {result.stderr[-300:]}"
        )

    # --- Reconnect ---

    def test_reconnect_preserves_data(self):
        result = self._write_and_run(
            "statement ok\nCREATE TABLE rc(x INTEGER)\n\n"
            "statement ok\nINSERT INTO rc VALUES (42)\n\n"
            "reconnect\n\n"
            "query I\nSELECT x FROM rc\n----\n42\n\n"
            "statement ok\nDROP TABLE rc\n"
        )
        assert result.returncode == 0, (
            f"Reconnect should preserve persistent data.\n"
            f"stderr: {result.stderr[-300:]}"
        )

    def test_reconnect_allows_new_connections(self):
        result = self._write_and_run(
            "statement ok\nCREATE TABLE rcn(x INTEGER)\n\n"
            "statement ok\nINSERT INTO rcn VALUES (99)\n\n"
            "query I @old_conn\nSELECT x FROM rcn\n----\n99\n\n"
            "reconnect\n\n"
            "query I @new_conn\nSELECT x FROM rcn\n----\n99\n\n"
            "statement ok\nDROP TABLE rcn\n"
        )
        assert result.returncode == 0, (
            f"New connections should work after reconnect.\n"
            f"stderr: {result.stderr[-300:]}"
        )

    # --- EXPLAIN regex ---

    def test_explain_regex_scan(self):
        result = self._write_and_run(
            "statement ok\nPRAGMA explain_output = PHYSICAL_ONLY;\n\n"
            "statement ok\nCREATE TABLE ert(x INTEGER)\n\n"
            "statement ok\nINSERT INTO ert VALUES (1)\n\n"
            "query TT\nEXPLAIN SELECT * FROM ert\n----\n"
            "physical_plan\t<REGEX>:.*SCAN.*\n\n"
            "statement ok\nDROP TABLE ert\n"
        )
        assert result.returncode == 0, (
            f"EXPLAIN regex for SCAN should match.\n"
            f"stderr: {result.stderr[-300:]}"
        )

    def test_explain_negative_regex(self):
        result = self._write_and_run(
            "statement ok\nPRAGMA explain_output = PHYSICAL_ONLY;\n\n"
            "statement ok\nCREATE TABLE ern(x INTEGER)\n\n"
            "query TT\nEXPLAIN SELECT x FROM ern\n----\n"
            "physical_plan\t<!REGEX>:.*JOIN.*\n\n"
            "statement ok\nDROP TABLE ern\n"
        )
        assert result.returncode == 0, (
            f"EXPLAIN negative regex should pass (no JOIN in scan plan).\n"
            f"stderr: {result.stderr[-300:]}"
        )

    # --- hash_threshold ---

    def test_hash_threshold_auto_hashing(self):
        result = self._write_and_run(
            "hash_threshold 5\n\n"
            "query I\nSELECT * FROM range(10) t(i)\n----\n"
            "0\n1\n2\n3\n4\n5\n6\n7\n8\n9\n"
        )
        assert result.returncode == 0, (
            f"hash_threshold should auto-hash and pass.\n"
            f"stderr: {result.stderr[-300:]}"
        )

    def test_hash_threshold_mismatch_fails(self):
        result = self._write_and_run(
            "hash_threshold 3\n\n"
            "query I\nSELECT * FROM range(5) t(i)\n----\n"
            "0\n1\n2\n3\n999\n"
        )
        assert result.returncode != 0, (
            "hash_threshold with wrong expected values should fail"
        )

    # --- DOTALL regex for multi-line values ---

    def test_regex_dotall_multiline(self):
        """Regex with DOTALL should match across newlines in EXPLAIN output."""
        result = self._write_and_run(
            "statement ok\nPRAGMA explain_output = PHYSICAL_ONLY;\n\n"
            "statement ok\nCREATE TABLE rdm(a INTEGER, b INTEGER)\n\n"
            "statement ok\nINSERT INTO rdm SELECT range, range FROM range(10)\n\n"
            "query TT\nEXPLAIN SELECT a, SUM(b) FROM rdm GROUP BY a\n----\n"
            "physical_plan\t<REGEX>:.*GROUP.*\n\n"
            "statement ok\nDROP TABLE rdm\n"
        )
        assert result.returncode == 0, (
            f"DOTALL regex should match multi-line EXPLAIN output.\n"
            f"stderr: {result.stderr[-300:]}"
        )

    # --- Loop + connection interaction ---

    def test_loop_with_connection(self):
        result = self._write_and_run(
            "statement ok\nCREATE TABLE lwc(x INTEGER)\n\n"
            "loop i 0 3\n\n"
            "statement ok @conn\nINSERT INTO lwc VALUES (${i})\n\n"
            "endloop\n\n"
            "query I\nSELECT COUNT(*) FROM lwc\n----\n3\n\n"
            "statement ok\nDROP TABLE lwc\n"
        )
        assert result.returncode == 0, (
            f"Loop with named connection should work.\n"
            f"stderr: {result.stderr[-300:]}"
        )

    # --- Nested control flow ---

    def test_nested_loops(self):
        """Nested loops must track nesting depth and isolate variable scopes."""
        result = self._write_and_run(
            "statement ok\nCREATE TABLE nl(a INTEGER, b INTEGER)\n\n"
            "loop i 0 3\n\n"
            "loop j 0 2\n\n"
            "statement ok\nINSERT INTO nl VALUES (${i}, ${j})\n\n"
            "endloop\n\n"
            "endloop\n\n"
            "query I\nSELECT COUNT(*) FROM nl\n----\n6\n\n"
            "statement ok\nDROP TABLE nl\n"
        )
        assert result.returncode == 0, (
            f"Nested loops (3*2=6 inserts) should work.\n"
            f"stderr: {result.stderr[-300:]}"
        )

    def test_nested_foreach(self):
        """Nested foreach must isolate variable scopes."""
        result = self._write_and_run(
            "statement ok\nCREATE TABLE nf(a VARCHAR, b VARCHAR)\n\n"
            "foreach x A B\n\n"
            "foreach y 1 2 3\n\n"
            "statement ok\nINSERT INTO nf VALUES ('${x}', '${y}')\n\n"
            "endforeach\n\n"
            "endforeach\n\n"
            "query I\nSELECT COUNT(*) FROM nf\n----\n6\n\n"
            "statement ok\nDROP TABLE nf\n"
        )
        assert result.returncode == 0, (
            f"Nested foreach (2*3=6 inserts) should work.\n"
            f"stderr: {result.stderr[-300:]}"
        )

    def test_nested_loop_variable_isolation(self):
        """Inner loop variable must not overwrite outer variable."""
        result = self._write_and_run(
            "statement ok\nCREATE TABLE nvi(outer_val INTEGER, inner_val INTEGER)\n\n"
            "loop i 10 12\n\n"
            "loop j 0 2\n\n"
            "statement ok\nINSERT INTO nvi VALUES (${i}, ${j})\n\n"
            "endloop\n\n"
            "endloop\n\n"
            "query II\nSELECT * FROM nvi ORDER BY outer_val, inner_val\n----\n"
            "10\t0\n10\t1\n11\t0\n11\t1\n"
        )
        assert result.returncode == 0, (
            f"Nested loop variable isolation should work.\n"
            f"stderr: {result.stderr[-300:]}"
        )

    # --- Mode verify (dual-execution plan verification) ---

    def test_mode_verify_basic(self):
        """mode verify: queries pass when optimized and unoptimized produce same results."""
        result = self._write_and_run(
            "mode verify\n\n"
            "statement ok\nCREATE TABLE mvb(x INTEGER)\n\n"
            "statement ok\nINSERT INTO mvb VALUES (1), (2), (3)\n\n"
            "query I\nSELECT SUM(x) FROM mvb\n----\n6\n\n"
            "query I rowsort\nSELECT x FROM mvb\n----\n1\n2\n3\n\n"
            "mode noverify\n\n"
            "statement ok\nDROP TABLE mvb\n"
        )
        assert result.returncode == 0, (
            f"mode verify should pass for correct queries.\n"
            f"stderr: {result.stderr[-500:]}"
        )

    def test_mode_verify_with_join(self):
        """mode verify: join queries where optimizer may reorder sides."""
        result = self._write_and_run(
            "mode verify\n\n"
            "statement ok\nCREATE TABLE mvj1(a INTEGER)\n\n"
            "statement ok\nINSERT INTO mvj1 VALUES (1), (2), (3)\n\n"
            "statement ok\nCREATE TABLE mvj2(b INTEGER)\n\n"
            "statement ok\nINSERT INTO mvj2 VALUES (2), (3), (4)\n\n"
            "query II rowsort\n"
            "SELECT a, b FROM mvj1 JOIN mvj2 ON mvj1.a = mvj2.b\n"
            "----\n2\t2\n3\t3\n\n"
            "mode noverify\n\n"
            "statement ok\nDROP TABLE mvj2\n\n"
            "statement ok\nDROP TABLE mvj1\n"
        )
        assert result.returncode == 0, (
            f"mode verify with join should pass.\n"
            f"stderr: {result.stderr[-500:]}"
        )

    def test_mode_verify_with_subquery(self):
        """mode verify: subquery where optimizer may decorrelate."""
        result = self._write_and_run(
            "mode verify\n\n"
            "statement ok\nCREATE TABLE mvs1(x INTEGER)\n\n"
            "statement ok\nINSERT INTO mvs1 VALUES (1), (2), (3), (4), (5)\n\n"
            "query I rowsort\n"
            "SELECT x FROM mvs1 WHERE x IN (SELECT x FROM mvs1 WHERE x > 3)\n"
            "----\n4\n5\n\n"
            "mode noverify\n\n"
            "statement ok\nDROP TABLE mvs1\n"
        )
        assert result.returncode == 0, (
            f"mode verify with subquery should pass.\n"
            f"stderr: {result.stderr[-500:]}"
        )

    def test_mode_verify_unordered_results(self):
        """mode verify correctly handles different row orders from optimizer."""
        result = self._write_and_run(
            "mode verify\n\n"
            "statement ok\nCREATE TABLE mvu(x INTEGER)\n\n"
            "statement ok\nINSERT INTO mvu VALUES (3), (1), (4), (1), (5)\n\n"
            "query I rowsort\nSELECT x FROM mvu\n----\n1\n1\n3\n4\n5\n\n"
            "mode noverify\n\n"
            "statement ok\nDROP TABLE mvu\n"
        )
        assert result.returncode == 0, (
            f"mode verify with unordered results should pass.\n"
            f"stderr: {result.stderr[-500:]}"
        )

    def test_mode_noverify_stops_verification(self):
        """mode noverify disables the dual-execution check."""
        result = self._write_and_run(
            "mode verify\n\n"
            "statement ok\nCREATE TABLE mnv(x INTEGER)\n\n"
            "statement ok\nINSERT INTO mnv VALUES (1)\n\n"
            "query I\nSELECT x FROM mnv\n----\n1\n\n"
            "mode noverify\n\n"
            "query I\nSELECT x FROM mnv\n----\n1\n\n"
            "statement ok\nDROP TABLE mnv\n"
        )
        assert result.returncode == 0, (
            f"mode noverify should work.\nstderr: {result.stderr[-300:]}"
        )

    # --- Mode skip (execution flow control) ---

    def test_mode_skip_skips_invalid(self):
        """mode skip must not execute invalid SQL."""
        result = self._write_and_run(
            "statement ok\nCREATE TABLE mss(x INTEGER)\n\n"
            "statement ok\nINSERT INTO mss VALUES (42)\n\n"
            "mode skip\n\n"
            "statement ok\nTHIS IS NOT VALID SQL\n\n"
            "query I\nSELECT * FROM nonexistent_xyz\n----\n999\n\n"
            "mode unskip\n\n"
            "query I\nSELECT x FROM mss\n----\n42\n\n"
            "statement ok\nDROP TABLE mss\n"
        )
        assert result.returncode == 0, (
            f"mode skip should skip invalid SQL.\n"
            f"stderr: {result.stderr[-500:]}"
        )

    def test_mode_skip_preserves_state(self):
        """mode skip must preserve database state from before the skip block."""
        result = self._write_and_run(
            "statement ok\nCREATE TABLE msp(a INTEGER, b VARCHAR)\n\n"
            "statement ok\nINSERT INTO msp VALUES (1, 'kept')\n\n"
            "mode skip\n\n"
            "statement ok\nDROP TABLE msp\n\n"
            "statement ok\nINSERT INTO msp VALUES (2, 'should_not_exist')\n\n"
            "mode unskip\n\n"
            "query IT\nSELECT * FROM msp\n----\n1\tkept\n\n"
            "statement ok\nDROP TABLE msp\n"
        )
        assert result.returncode == 0, (
            f"mode skip should preserve state.\n"
            f"stderr: {result.stderr[-500:]}"
        )

    def test_mode_skip_with_loop(self):
        """mode skip must handle loops without executing their bodies."""
        result = self._write_and_run(
            "statement ok\nCREATE TABLE msl(x INTEGER)\n\n"
            "statement ok\nINSERT INTO msl VALUES (1)\n\n"
            "mode skip\n\n"
            "loop i 0 1000\n\n"
            "statement ok\nINSERT INTO msl VALUES (${i})\n\n"
            "endloop\n\n"
            "mode unskip\n\n"
            "query I\nSELECT COUNT(*) FROM msl\n----\n1\n\n"
            "statement ok\nDROP TABLE msl\n"
        )
        assert result.returncode == 0, (
            f"mode skip should skip loops without executing.\n"
            f"stderr: {result.stderr[-500:]}"
        )

    def test_mode_skip_with_nested_foreach(self):
        """mode skip must handle nested foreach without executing."""
        result = self._write_and_run(
            "statement ok\nCREATE TABLE msf(x INTEGER)\n\n"
            "statement ok\nINSERT INTO msf VALUES (1)\n\n"
            "mode skip\n\n"
            "foreach a 1 2 3\n\n"
            "foreach b 4 5 6\n\n"
            "statement ok\nINSERT INTO msf VALUES (${a})\n\n"
            "endforeach\n\n"
            "endforeach\n\n"
            "mode unskip\n\n"
            "query I\nSELECT COUNT(*) FROM msf\n----\n1\n\n"
            "statement ok\nDROP TABLE msf\n"
        )
        assert result.returncode == 0, (
            f"mode skip should handle nested foreach.\n"
            f"stderr: {result.stderr[-500:]}"
        )
