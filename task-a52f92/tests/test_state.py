"""
Tests for sqllogictest --override auto-update mode.

Verifies that the override mode correctly rewrites .slt files with actual
database output, producing valid files that pass when re-run.

"""

import subprocess
import json
import os
import tempfile
import hashlib
import pytest

RUNNER = "/app/slt_runner.py"


def create_temp_slt(content):
    """Create a temporary .slt file with the given content."""
    fd, path = tempfile.mkstemp(suffix=".slt", dir="/tmp")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def run_override(filepath, labels=None):
    """Run the SLT runner with --override on a file."""
    cmd = ["python3", RUNNER, filepath, "--override"]
    if labels:
        for label in labels:
            cmd.extend(["--label", label])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def run_normal(filepath, labels=None):
    """Run the SLT runner normally and return (json_output, exit_code)."""
    cmd = ["python3", RUNNER, filepath]
    if labels:
        for label in labels:
            cmd.extend(["--label", label])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    try:
        output = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        output = None
    return output, result.returncode


def read_file(path):
    """Read file content."""
    with open(path) as f:
        return f.read()


def extract_results_after_dash(content):
    """Extract result lines after the ---- separator."""
    lines = content.split("\n")
    dash_idx = None
    for idx, l in enumerate(lines):
        if l.strip() == "----":
            dash_idx = idx
    if dash_idx is None:
        return None
    result_lines = []
    for l in lines[dash_idx + 1:]:
        if l == "":
            break
        result_lines.append(l)
    return result_lines


# ---------------------------------------------------------------------------
# CLI flag recognition
# ---------------------------------------------------------------------------

class TestOverrideCLI:
    def test_override_flag_accepted(self):
        """The --override flag must be recognized by the CLI."""
        path = create_temp_slt(
            "statement ok\n"
            "CREATE TABLE cli_flag_test(x INTEGER)\n"
        )
        try:
            result = run_override(path)
            assert result.returncode == 0, (
                f"Override should exit 0, got {result.returncode}. "
                f"stderr: {result.stderr}"
            )
            # Must NOT show usage error about unrecognized arguments
            assert "unrecognized" not in result.stderr.lower(), (
                f"--override flag not recognized: {result.stderr}"
            )
        finally:
            os.unlink(path)

    def test_override_exit_zero_on_failures(self):
        """Override must exit 0 even when the original file had failures."""
        path = create_temp_slt(
            "statement ok\n"
            "CREATE TABLE exit_test(x INTEGER)\n"
            "\n"
            "query I nosort\n"
            "SELECT x FROM exit_test\n"
            "----\n"
            "wrong_value_999\n"
        )
        try:
            result = run_override(path)
            assert result.returncode == 0, (
                f"Override should always exit 0, got {result.returncode}"
            )
        finally:
            os.unlink(path)

    def test_override_emits_json(self):
        """Override must still emit JSON report to stdout."""
        path = create_temp_slt(
            "statement ok\n"
            "CREATE TABLE json_test(x INTEGER)\n"
        )
        try:
            result = run_override(path)
            try:
                data = json.loads(result.stdout)
            except (json.JSONDecodeError, ValueError):
                data = None
            assert data is not None, (
                f"Override must emit JSON to stdout. Got: {result.stdout!r}"
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Query result override
# ---------------------------------------------------------------------------

class TestOverrideQueryResults:
    def test_wrong_result_updated(self):
        """Override replaces wrong query results; round-trip passes."""
        path = create_temp_slt(
            "statement ok\n"
            "CREATE TABLE qr1(x INTEGER)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO qr1 VALUES(42)\n"
            "\n"
            "query I nosort\n"
            "SELECT x FROM qr1\n"
            "----\n"
            "999\n"
        )
        try:
            run_override(path)
            out, code = run_normal(path)
            assert out is not None, "No JSON output after override"
            assert code == 0, f"Round-trip failed: {out}"
            assert out["failed"] == 0
            content = read_file(path)
            assert "42" in content, "Correct value must appear"
            assert "999" not in content, "Wrong value must be gone"
        finally:
            os.unlink(path)

    def test_valuesort_format(self):
        """Override writes valuesort output as flattened sorted individual values."""
        path = create_temp_slt(
            "statement ok\n"
            "CREATE TABLE vs1(a INTEGER, b TEXT)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO vs1 VALUES(2, 'banana')\n"
            "\n"
            "statement ok\n"
            "INSERT INTO vs1 VALUES(1, 'apple')\n"
            "\n"
            "query IT valuesort\n"
            "SELECT a, b FROM vs1\n"
            "----\n"
            "wrong\n"
        )
        try:
            run_override(path)
            content = read_file(path)
            # Old wrong value must be replaced
            assert "wrong" not in content, "Wrong value must be replaced"
            # Valuesort flattens all cell values and sorts lexicographically
            # Expected individual values sorted: 1, 2, apple, banana
            result_lines = extract_results_after_dash(content)
            assert result_lines is not None, "---- delimiter must exist"
            assert len(result_lines) == 4, (
                f"Expected 4 individual values for valuesort, got {len(result_lines)}: {result_lines}"
            )
            # Each value must be on its own line, sorted lexicographically
            assert result_lines == sorted(result_lines), (
                f"Values not in sorted order: {result_lines}"
            )
            assert set(result_lines) == {"1", "2", "apple", "banana"}, (
                f"Unexpected values: {result_lines}"
            )
        finally:
            os.unlink(path)

    def test_multi_column_nosort(self):
        """Override formats multi-column results as space-separated values."""
        path = create_temp_slt(
            "statement ok\n"
            "CREATE TABLE mc1(a INTEGER, b TEXT, c REAL)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO mc1 VALUES(7, 'test', 3.14)\n"
            "\n"
            "query ITR nosort\n"
            "SELECT a, b, c FROM mc1\n"
            "----\n"
            "wrong wrong wrong\n"
        )
        try:
            run_override(path)
            out, code = run_normal(path)
            assert code == 0, f"Multi-column round-trip failed: {out}"
        finally:
            os.unlink(path)

    def test_rowsort_format(self):
        """Override respects rowsort ordering in output."""
        path = create_temp_slt(
            "statement ok\n"
            "CREATE TABLE rs1(a INTEGER, b TEXT)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO rs1 VALUES(2, 'b')\n"
            "\n"
            "statement ok\n"
            "INSERT INTO rs1 VALUES(1, 'a')\n"
            "\n"
            "query IT rowsort\n"
            "SELECT a, b FROM rs1\n"
            "----\n"
            "wrong\n"
        )
        try:
            run_override(path)
            out, code = run_normal(path)
            assert code == 0, f"Rowsort round-trip failed: {out}"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Statement count override
# ---------------------------------------------------------------------------

class TestOverrideStatementCount:
    def test_count_updated(self):
        """Override updates statement count to actual affected rows."""
        path = create_temp_slt(
            "statement ok\n"
            "CREATE TABLE sc1(x INTEGER)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO sc1 VALUES(1)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO sc1 VALUES(2)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO sc1 VALUES(3)\n"
            "\n"
            "statement count 999\n"
            "UPDATE sc1 SET x = x + 10 WHERE x <= 2\n"
        )
        try:
            run_override(path)
            out, code = run_normal(path)
            assert code == 0, f"Count round-trip failed: {out}"
            content = read_file(path)
            assert "statement count 2" in content, "Count must be updated to 2"
            assert "999" not in content, "Old count must be gone"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Error <-> success conversions
# ---------------------------------------------------------------------------

class TestOverrideErrorConversion:
    def test_error_to_ok(self):
        """statement error that succeeds must become statement ok."""
        path = create_temp_slt(
            "statement error\n"
            "CREATE TABLE eo1(x INTEGER)\n"
        )
        try:
            run_override(path)
            content = read_file(path)
            assert "statement ok" in content
            # "statement error" should no longer appear as a record header
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped.startswith("statement "):
                    assert "error" not in stripped, (
                        f"statement error should be converted to ok: {stripped}"
                    )
            out, code = run_normal(path)
            assert code == 0, f"Error-to-ok round-trip failed: {out}"
        finally:
            os.unlink(path)

    def test_ok_to_error(self):
        """statement ok that errors must become statement error with pattern."""
        path = create_temp_slt(
            "statement ok\n"
            "SELECT * FROM nonexistent_override_table_zyx\n"
        )
        try:
            run_override(path)
            content = read_file(path)
            assert "statement error" in content, "Must convert to statement error"
            # The error line must not contain "statement ok"
            has_statement_ok = any(
                l.strip() == "statement ok"
                for l in content.split("\n")
            )
            assert not has_statement_ok, "statement ok must be removed"
            out, code = run_normal(path)
            assert code == 0, f"Ok-to-error round-trip failed: {out}"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# System stdout override
# ---------------------------------------------------------------------------

class TestOverrideSystemStdout:
    def test_stdout_updated(self):
        """Override replaces wrong system stdout with actual output."""
        path = create_temp_slt(
            "system ok\n"
            "echo override_stdout_test_value\n"
            "----\n"
            "wrong_stdout_placeholder\n"
            "\n"
            "\n"
        )
        try:
            run_override(path)
            content = read_file(path)
            assert "override_stdout_test_value" in content
            assert "wrong_stdout_placeholder" not in content
            out, code = run_normal(path)
            assert code == 0, f"System stdout round-trip failed: {out}"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Halt handling
# ---------------------------------------------------------------------------

class TestOverrideHalt:
    def test_halt_preserves_following_records(self):
        """Records after halt must be written as-is without execution."""
        path = create_temp_slt(
            "statement ok\n"
            "CREATE TABLE halt1(x INTEGER)\n"
            "\n"
            "halt\n"
            "\n"
            "query I nosort\n"
            "SELECT x FROM nonexistent_halt_table\n"
            "----\n"
            "preserved_sentinel_67890\n"
        )
        try:
            run_override(path)
            content = read_file(path)
            assert "halt" in content, "halt directive must be preserved"
            assert "preserved_sentinel_67890" in content, (
                "Content after halt must be preserved as-is"
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Hash-threshold interaction
# ---------------------------------------------------------------------------

class TestOverrideHashThreshold:
    def test_hash_applied_during_override(self):
        """Override with active hash-threshold produces hash format for large results."""
        path = create_temp_slt(
            "hash-threshold 3\n"
            "\n"
            "statement ok\n"
            "CREATE TABLE ht1(x INTEGER)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO ht1 VALUES(1)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO ht1 VALUES(2)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO ht1 VALUES(3)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO ht1 VALUES(4)\n"
            "\n"
            "query I nosort\n"
            "SELECT x FROM ht1 ORDER BY x\n"
            "----\n"
            "wrong\n"
        )
        try:
            run_override(path)
            content = read_file(path)
            # 4 values > threshold 3 -> must use hash format
            assert "values hashing to" in content, (
                "Hash-threshold must produce hash format in override output"
            )
            out, code = run_normal(path)
            assert code == 0, f"Hash-threshold round-trip failed: {out}"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Preservation of correct results
# ---------------------------------------------------------------------------

class TestOverridePreservation:
    def test_passing_file_not_broken(self):
        """Override on a file that already passes must not break it."""
        path = create_temp_slt(
            "statement ok\n"
            "CREATE TABLE pf1(x INTEGER)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO pf1 VALUES(42)\n"
            "\n"
            "query I nosort\n"
            "SELECT x FROM pf1\n"
            "----\n"
            "42\n"
        )
        try:
            out1, code1 = run_normal(path)
            assert code1 == 0, "File should pass before override"
            run_override(path)
            out2, code2 = run_normal(path)
            assert code2 == 0, f"Passing file broken by override: {out2}"
            assert out2["failed"] == 0
        finally:
            os.unlink(path)

    def test_comments_preserved(self):
        """Comments in the file must survive override."""
        path = create_temp_slt(
            "# Top-level comment about this test\n"
            "# Another header comment\n"
            "\n"
            "statement ok\n"
            "CREATE TABLE cp1(x INTEGER)\n"
            "\n"
            "# Mid-file comment\n"
            "statement ok\n"
            "INSERT INTO cp1 VALUES(1)\n"
            "\n"
            "query I nosort\n"
            "SELECT x FROM cp1\n"
            "----\n"
            "999\n"
        )
        try:
            run_override(path)
            content = read_file(path)
            assert "# Top-level comment about this test" in content
            assert "# Another header comment" in content
            assert "# Mid-file comment" in content
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Complex round-trip
# ---------------------------------------------------------------------------

class TestOverrideRoundTrip:
    def test_complex_multi_record_roundtrip(self):
        """Override a file with multiple wrong records; re-run must pass."""
        path = create_temp_slt(
            "# Complex round-trip test\n"
            "\n"
            "statement ok\n"
            "CREATE TABLE rt1(a INTEGER, b TEXT)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO rt1 VALUES(1, 'first')\n"
            "\n"
            "statement ok\n"
            "INSERT INTO rt1 VALUES(2, 'second')\n"
            "\n"
            "# Query with wrong results\n"
            "query IT nosort\n"
            "SELECT a, b FROM rt1 ORDER BY a\n"
            "----\n"
            "wrong1\n"
            "wrong2\n"
            "\n"
            "statement count 999\n"
            "UPDATE rt1 SET a = a + 10 WHERE a = 1\n"
            "\n"
            "system ok\n"
            "echo roundtrip_sentinel\n"
            "----\n"
            "wrong_system_output\n"
            "\n"
            "\n"
        )
        try:
            run_override(path)
            out, code = run_normal(path)
            assert out is not None, "No JSON output after complex override"
            assert code == 0, f"Complex round-trip failed: {out}"
            assert out["failed"] == 0, f"Failures remain: {out['errors']}"
            content = read_file(path)
            assert "# Complex round-trip test" in content
            assert "# Query with wrong results" in content
        finally:
            os.unlink(path)

    def test_multiple_sort_modes_roundtrip(self):
        """Override handles nosort, rowsort, and valuesort in same file."""
        path = create_temp_slt(
            "statement ok\n"
            "CREATE TABLE sm1(x INTEGER)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO sm1 VALUES(3)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO sm1 VALUES(1)\n"
            "\n"
            "statement ok\n"
            "INSERT INTO sm1 VALUES(2)\n"
            "\n"
            "query I nosort\n"
            "SELECT x FROM sm1 ORDER BY x\n"
            "----\n"
            "wrong\n"
            "\n"
            "query I rowsort\n"
            "SELECT x FROM sm1\n"
            "----\n"
            "wrong\n"
            "\n"
            "query I valuesort\n"
            "SELECT x FROM sm1\n"
            "----\n"
            "wrong\n"
        )
        try:
            run_override(path)
            out, code = run_normal(path)
            assert code == 0, f"Multi-sort round-trip failed: {out}"
            assert out["failed"] == 0
        finally:
            os.unlink(path)
