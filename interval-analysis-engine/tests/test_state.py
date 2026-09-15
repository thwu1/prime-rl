"""
Tests for the value-range analysis task.

"""

import json
import os
import sqlite3
import subprocess
import pytest


@pytest.fixture(scope="session")
def run_analyzer():
    """Run the analyzer once."""
    subprocess.run(
        ["python3", "/app/analyzer.py"],
        check=True,
        cwd="/app",
        timeout=120,
    )


@pytest.fixture(scope="session")
def results(run_analyzer):
    """Load JSON results."""
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def db_conn(run_analyzer):
    """Connect to the SQLite database."""
    conn = sqlite3.connect("/app/analysis.db")
    yield conn
    conn.close()


def db_lookup(db_conn, program, variable):
    """Query a specific result from the database."""
    cur = db_conn.execute(
        "SELECT lo, hi FROM results WHERE program = ? AND variable = ?",
        (program, variable),
    )
    row = cur.fetchone()
    assert row is not None, f"No DB entry for {program}:{variable}"
    return row


# ---------------------------------------------------------------------------
# basic.ir -- intraprocedural arithmetic
# ---------------------------------------------------------------------------
class TestBasicProgram:

    def test_x_is_5(self, results):
        assert results["basic.ir"]["x"] == [5, 5]

    def test_y_is_3(self, results):
        assert results["basic.ir"]["y"] == [3, 3]

    def test_z_is_8(self, results):
        assert results["basic.ir"]["z"] == [8, 8]

    def test_w_is_40(self, results):
        assert results["basic.ir"]["w"] == [40, 40]


# ---------------------------------------------------------------------------
# interproc.ir -- interprocedural propagation
# ---------------------------------------------------------------------------
class TestInterprocProgram:

    def test_a_is_7(self, results):
        assert results["interproc.ir"]["a"] == [7, 7]

    def test_b_is_30(self, results):
        assert results["interproc.ir"]["b"] == [30, 30]

    def test_c_is_37(self, results):
        assert results["interproc.ir"]["c"] == [37, 37]


# ---------------------------------------------------------------------------
# context.ir -- call-site distinguishability
# ---------------------------------------------------------------------------
class TestContextSensitivity:

    def test_c_is_5(self, results):
        assert results["context.ir"]["c"] == [5, 5]

    def test_d_is_10(self, results):
        assert results["context.ir"]["d"] == [10, 10]

    def test_e_is_15(self, results):
        assert results["context.ir"]["e"] == [15, 15]


# ---------------------------------------------------------------------------
# loop.ir -- loop convergence
# ---------------------------------------------------------------------------
class TestLoopAnalysis:

    def test_i_after_loop(self, results):
        assert results["loop.ir"]["i"] == [10, 10]

    def test_s_lower_bound(self, results):
        assert results["loop.ir"]["s"][0] == 0

    def test_s_upper_bound(self, results):
        assert results["loop.ir"]["s"][1] == "inf"


# ---------------------------------------------------------------------------
# combined.ir -- all features together
# ---------------------------------------------------------------------------
class TestCombined:

    def test_b_is_3(self, results):
        assert results["combined.ir"]["b"] == [3, 3]

    def test_d_is_300(self, results):
        assert results["combined.ir"]["d"] == [300, 300]

    def test_i_after_loop(self, results):
        assert results["combined.ir"]["i"] == [3, 3]

    def test_r_is_303(self, results):
        assert results["combined.ir"]["r"] == [303, 303]


# ---------------------------------------------------------------------------
# SQLite database structure and content
# ---------------------------------------------------------------------------
class TestSQLiteDatabase:

    def test_db_exists(self, run_analyzer):
        assert os.path.exists("/app/analysis.db")

    def test_table_schema(self, db_conn):
        cur = db_conn.execute("PRAGMA table_info(results)")
        cols = {row[1]: row[2].upper() for row in cur.fetchall()}
        assert "program" in cols
        assert "variable" in cols
        assert "lo" in cols
        assert "hi" in cols

    def test_basic_entry_count(self, db_conn):
        cur = db_conn.execute(
            "SELECT COUNT(*) FROM results WHERE program = 'basic.ir'"
        )
        count = cur.fetchone()[0]
        assert count == 4  # x, y, z, w

    def test_basic_x_in_db(self, db_conn):
        lo, hi = db_lookup(db_conn, "basic.ir", "x")
        assert lo == "5" and hi == "5"

    def test_context_e_in_db(self, db_conn):
        lo, hi = db_lookup(db_conn, "context.ir", "e")
        assert lo == "15" and hi == "15"

    def test_loop_s_in_db(self, db_conn):
        lo, hi = db_lookup(db_conn, "loop.ir", "s")
        assert lo == "0" and hi == "inf"

    def test_combined_r_in_db(self, db_conn):
        lo, hi = db_lookup(db_conn, "combined.ir", "r")
        assert lo == "303" and hi == "303"

    def test_all_programs_present(self, db_conn):
        cur = db_conn.execute(
            "SELECT DISTINCT program FROM results ORDER BY program"
        )
        programs = [row[0] for row in cur.fetchall()]
        assert "basic.ir" in programs
        assert "interproc.ir" in programs
        assert "context.ir" in programs
        assert "loop.ir" in programs
        assert "combined.ir" in programs


# ---------------------------------------------------------------------------
# Call graph DOT/SVG files
# ---------------------------------------------------------------------------
class TestCallGraphs:

    ALL_PROGRAMS = ["basic", "interproc", "context", "loop", "combined"]

    def test_graphs_dir_exists(self, run_analyzer):
        assert os.path.isdir("/app/graphs")

    @pytest.mark.parametrize("name", ALL_PROGRAMS)
    def test_dot_file_exists(self, run_analyzer, name):
        assert os.path.exists(f"/app/graphs/{name}.dot")

    @pytest.mark.parametrize("name", ALL_PROGRAMS)
    def test_dot_is_valid_digraph(self, run_analyzer, name):
        with open(f"/app/graphs/{name}.dot") as f:
            content = f.read()
        assert "digraph" in content

    @pytest.mark.parametrize("name", ALL_PROGRAMS)
    def test_svg_file_exists(self, run_analyzer, name):
        assert os.path.exists(f"/app/graphs/{name}.svg")

    def test_interproc_has_add_edge(self, run_analyzer):
        with open("/app/graphs/interproc.dot") as f:
            content = f.read()
        assert "main" in content and "add" in content

    def test_context_has_id_edge(self, run_analyzer):
        with open("/app/graphs/context.dot") as f:
            content = f.read()
        assert "main" in content and "id" in content

    def test_combined_has_scale_edge(self, run_analyzer):
        with open("/app/graphs/combined.dot") as f:
            content = f.read()
        assert "main" in content and "scale" in content
