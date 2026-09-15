"""
Tests for the distributed database consistency audit pipeline.

Verifies correct classification of register and transactional histories,
plus the audit pipeline outputs (DOT/SVG graphs, SQLite database).

"""

import json
import os
import re
import sqlite3 as sqlite3_lib
import subprocess

import pytest


def run_checker(history_file):
    """Run the checker tool and parse its JSON output."""
    result = subprocess.run(
        ["python3", "/app/checker.py", history_file],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Checker exited with code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        pytest.fail(f"Checker output is not valid JSON: {result.stdout!r}")


# ── Register linearizability tests ──────────────────────────────────


class TestRegisterLinearizability:
    """Tests for single-register linearizability checking."""

    def test_register_01_sequential_linearizable(self):
        """Fully sequential history: write(1), read->1, write(2), read->2."""
        result = run_checker("/app/histories/register_01.json")
        assert "linearizable" in result, "Missing 'linearizable' key"
        assert result["linearizable"] is True

    def test_register_02_stale_read_not_linearizable(self):
        """Read returns 1 after write(2) has completed — stale read."""
        result = run_checker("/app/histories/register_02.json")
        assert result["linearizable"] is False

    def test_register_03_concurrent_linearizable(self):
        """Overlapping write(1)/write(2) with reads 1 then 2 — linearizable."""
        result = run_checker("/app/histories/register_03.json")
        assert result["linearizable"] is True

    def test_register_04_conflicting_reads_not_linearizable(self):
        """Two non-overlapping reads after concurrent writes return
        different values with the later read seeing the earlier write —
        no valid linearization exists."""
        result = run_checker("/app/histories/register_04.json")
        assert result["linearizable"] is False

    def test_register_05_cas_linearizable(self):
        """CAS(0->1) then read->1 then CAS(1->2) then read->2."""
        result = run_checker("/app/histories/register_05.json")
        assert result["linearizable"] is True

    def test_register_06_double_cas_not_linearizable(self):
        """Two concurrent CAS(0->X) both succeed — impossible."""
        result = run_checker("/app/histories/register_06.json")
        assert result["linearizable"] is False


# ── Transaction consistency tests ───────────────────────────────────


class TestTransactionConsistency:
    """Tests for transaction anomaly detection and consistency classification."""

    def test_txn_01_strict_serializable(self):
        """Clean sequential history T1->T2->T3, no anomalies."""
        result = run_checker("/app/histories/txn_01.json")
        assert result["serializable"] is True
        assert result["strict_serializable"] is True
        assert result["anomalies"] == []

    def test_txn_02_g1a_aborted_read(self):
        """Committed T2 reads a value written only by aborted T1."""
        result = run_checker("/app/histories/txn_02.json")
        assert result["serializable"] is False
        assert result["strict_serializable"] is False
        assert "G1a" in result["anomalies"]

    def test_txn_03_g1c_circular_wr_dependency(self):
        """T1 writes x, reads y from T2; T2 writes y, reads x from T1 — wr cycle."""
        result = run_checker("/app/histories/txn_03.json")
        assert result["serializable"] is False
        assert "G1c" in result["anomalies"]
        assert "G2" not in result["anomalies"], "G1c cycle should not also be labeled G2"

    def test_txn_04_g2_anti_dependency_cycle(self):
        """T1 reads x=0/writes y; T2 reads y=0/writes x — rw-anti-dependency cycle."""
        result = run_checker("/app/histories/txn_04.json")
        assert result["serializable"] is False
        assert "G2" in result["anomalies"]

    def test_txn_05_causal_reverse(self):
        """T1 writes x before T2 writes y. T3 sees y=1 but not x=1.
        Serializable (order T2,T3,T1) but not strict serializable
        (T1 completed before T2 started)."""
        result = run_checker("/app/histories/txn_05.json")
        assert result["serializable"] is True
        assert result["strict_serializable"] is False
        assert "causal_reverse" in result["anomalies"]


# ── Audit pipeline tests ────────────────────────────────────────────


class TestAuditPipeline:
    """Tests for the audit.sh pipeline: graphs, SQLite DB, tool usage."""

    @pytest.fixture(scope="class", autouse=True)
    def run_audit(self):
        """Run audit.sh once before all pipeline tests."""
        result = subprocess.run(
            ["bash", "/app/audit.sh"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"audit.sh failed with code {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_svg_files_exist_for_transactional_histories(self):
        """An SVG file is produced for every transactional history."""
        txn_files = sorted(
            f for f in os.listdir("/app/histories") if f.startswith("txn_")
        )
        assert len(txn_files) > 0, "No transactional history files found"
        for fname in txn_files:
            name = fname.replace(".json", "")
            svg = f"/app/output/graphs/{name}.svg"
            assert os.path.isfile(svg), f"Missing SVG: {svg}"
            assert os.path.getsize(svg) > 100, f"SVG too small (likely empty): {svg}"

    def test_dot_files_contain_valid_graph(self):
        """DOT files contain a valid directed graph with edges."""
        txn_files = sorted(
            f for f in os.listdir("/app/histories") if f.startswith("txn_")
        )
        for fname in txn_files:
            name = fname.replace(".json", "")
            dot_path = f"/app/output/graphs/{name}.dot"
            assert os.path.isfile(dot_path), f"Missing DOT file: {dot_path}"
            content = open(dot_path).read()
            assert "digraph" in content, f"No 'digraph' keyword in {dot_path}"
            assert "->" in content, f"No edges (no '->') in {dot_path}"

    def test_audit_db_exists_with_schema(self):
        """SQLite audit database exists with the required table and columns."""
        db_path = "/app/output/audit.db"
        assert os.path.isfile(db_path), f"Missing database: {db_path}"
        db = sqlite3_lib.connect(db_path)
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='results'"
        )
        assert cursor.fetchone() is not None, "Missing 'results' table in audit.db"
        cursor = db.execute("PRAGMA table_info(results)")
        cols = {row[1] for row in cursor.fetchall()}
        for col in ("history_name", "history_type", "result_json", "pass"):
            assert col in cols, f"Missing column '{col}' in results table"
        db.close()

    def test_audit_db_has_all_entries(self):
        """Audit database contains one entry per history file."""
        all_names = sorted(
            f.replace(".json", "") for f in os.listdir("/app/histories")
        )
        db = sqlite3_lib.connect("/app/output/audit.db")
        cursor = db.execute("SELECT history_name FROM results ORDER BY history_name")
        db_names = sorted(row[0] for row in cursor.fetchall())
        db.close()
        assert all_names == db_names, (
            f"Mismatch: expected {all_names}, got {db_names}"
        )

    def test_audit_db_pass_fail_values(self):
        """Pass/fail classification in audit.db matches expected outcomes."""
        expected = {
            "register_01": 1,
            "register_02": 0,
            "register_03": 1,
            "register_04": 0,
            "register_05": 1,
            "register_06": 0,
            "txn_01": 1,
            "txn_02": 0,
            "txn_03": 0,
            "txn_04": 0,
            "txn_05": 0,
        }
        db = sqlite3_lib.connect("/app/output/audit.db")
        for name, exp_pass in expected.items():
            cursor = db.execute(
                "SELECT pass FROM results WHERE history_name=?", (name,)
            )
            row = cursor.fetchone()
            assert row is not None, f"No entry for '{name}' in audit.db"
            assert row[0] == exp_pass, (
                f"{name}: expected pass={exp_pass}, got {row[0]}"
            )
        db.close()

    def test_audit_sh_integrates_required_tools(self):
        """audit.sh uses jq, graphviz dot, and sqlite3 CLI."""
        with open("/app/audit.sh") as f:
            script = f.read()
        assert re.search(r"\bjq\b", script), (
            "audit.sh must use jq for JSON processing"
        )
        assert re.search(r"\bdot\b", script), (
            "audit.sh must use graphviz dot for SVG rendering"
        )
        assert re.search(r"\bsqlite3\b", script), (
            "audit.sh must use sqlite3 CLI for database operations"
        )
