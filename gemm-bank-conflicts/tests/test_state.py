
import json
import os
import sqlite3
import subprocess
import pytest


@pytest.fixture(scope="module")
def results():
    """Run the bank conflict analyzer and load results."""
    script = "/app/bank_conflicts.py"
    assert os.path.isfile(script), f"Solution script not found at {script}"

    # Clean up any previous run outputs
    for f in ["/app/results.json", "/app/analysis.db"]:
        if os.path.exists(f):
            os.remove(f)

    proc = subprocess.run(
        ["python3", script],
        capture_output=True,
        text=True,
        timeout=180,
        cwd="/app",
    )
    assert proc.returncode == 0, (
        f"bank_conflicts.py exited with code {proc.returncode}.\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )

    results_path = "/app/results.json"
    assert os.path.isfile(results_path), "results.json was not created"

    with open(results_path) as f:
        data = json.load(f)

    assert "scenarios" in data, "results.json missing 'scenarios' key"
    return data


def _get(results, name):
    for s in results["scenarios"]:
        if s["name"] == name:
            return s
    raise ValueError(f"Scenario '{name}' not found in results")


# ---------------------------------------------------------------------------
# Verify C library was compiled
# ---------------------------------------------------------------------------
class TestLibraryBuild:
    def test_libbank_exists(self, results):
        assert os.path.isfile("/app/src/libbank.so"), (
            "C shared library /app/src/libbank.so was not compiled"
        )


# ---------------------------------------------------------------------------
# small_tiles: BM=32, BN=32, BK=8, TM=4, TN=4
# ---------------------------------------------------------------------------
class TestSmallTilesStructure:
    def test_num_threads(self, results):
        assert _get(results, "small_tiles")["num_threads"] == 64

    def test_num_warps(self, results):
        assert _get(results, "small_tiles")["num_warps"] == 2

    def test_a_dimensions(self, results):
        assert _get(results, "small_tiles")["a_tile"]["dimensions"] == [32, 8]

    def test_b_dimensions(self, results):
        assert _get(results, "small_tiles")["b_tile"]["dimensions"] == [8, 32]


class TestSmallTilesConflicts:
    def test_a_conflicts_no_padding(self, results):
        assert _get(results, "small_tiles")["a_tile"]["conflicts_no_padding"] == 192

    def test_b_conflicts_no_padding(self, results):
        assert _get(results, "small_tiles")["b_tile"]["conflicts_no_padding"] == 0

    def test_a_optimal_skew(self, results):
        assert _get(results, "small_tiles")["a_tile"]["optimal_skew"] == 1

    def test_a_conflicts_with_padding(self, results):
        assert _get(results, "small_tiles")["a_tile"]["conflicts_with_padding"] == 0

    def test_b_optimal_skew(self, results):
        assert _get(results, "small_tiles")["b_tile"]["optimal_skew"] == 0

    def test_b_conflicts_with_padding(self, results):
        assert _get(results, "small_tiles")["b_tile"]["conflicts_with_padding"] == 0

    def test_total_no_padding(self, results):
        assert _get(results, "small_tiles")["total_conflicts_no_padding"] == 192

    def test_total_with_padding(self, results):
        assert _get(results, "small_tiles")["total_conflicts_with_padding"] == 0


# ---------------------------------------------------------------------------
# medium_tiles: BM=64, BN=64, BK=8, TM=4, TN=4
# ---------------------------------------------------------------------------
class TestMediumTilesStructure:
    def test_num_threads(self, results):
        assert _get(results, "medium_tiles")["num_threads"] == 256

    def test_num_warps(self, results):
        assert _get(results, "medium_tiles")["num_warps"] == 8


class TestMediumTilesConflicts:
    def test_a_conflicts_no_padding(self, results):
        assert _get(results, "medium_tiles")["a_tile"]["conflicts_no_padding"] == 256

    def test_b_conflicts_no_padding(self, results):
        assert _get(results, "medium_tiles")["b_tile"]["conflicts_no_padding"] == 256

    def test_a_optimal_skew(self, results):
        assert _get(results, "medium_tiles")["a_tile"]["optimal_skew"] == 1

    def test_a_conflicts_with_padding(self, results):
        assert _get(results, "medium_tiles")["a_tile"]["conflicts_with_padding"] == 0

    def test_b_optimal_skew(self, results):
        assert _get(results, "medium_tiles")["b_tile"]["optimal_skew"] == 0

    def test_b_conflicts_with_padding(self, results):
        assert _get(results, "medium_tiles")["b_tile"]["conflicts_with_padding"] == 256

    def test_total_no_padding(self, results):
        assert _get(results, "medium_tiles")["total_conflicts_no_padding"] == 512

    def test_total_with_padding(self, results):
        assert _get(results, "medium_tiles")["total_conflicts_with_padding"] == 256


# ---------------------------------------------------------------------------
# large_tiles: BM=128, BN=128, BK=16, TM=8, TN=8
# ---------------------------------------------------------------------------
class TestLargeTilesStructure:
    def test_num_threads(self, results):
        assert _get(results, "large_tiles")["num_threads"] == 256

    def test_num_warps(self, results):
        assert _get(results, "large_tiles")["num_warps"] == 8


class TestLargeTilesConflicts:
    def test_a_conflicts_no_padding(self, results):
        assert _get(results, "large_tiles")["a_tile"]["conflicts_no_padding"] == 1024

    def test_b_conflicts_no_padding(self, results):
        assert _get(results, "large_tiles")["b_tile"]["conflicts_no_padding"] == 3072

    def test_a_optimal_skew(self, results):
        assert _get(results, "large_tiles")["a_tile"]["optimal_skew"] == 1

    def test_a_conflicts_with_padding(self, results):
        assert _get(results, "large_tiles")["a_tile"]["conflicts_with_padding"] == 0

    def test_b_optimal_skew(self, results):
        assert _get(results, "large_tiles")["b_tile"]["optimal_skew"] == 0

    def test_b_conflicts_with_padding(self, results):
        assert _get(results, "large_tiles")["b_tile"]["conflicts_with_padding"] == 3072

    def test_total_no_padding(self, results):
        assert _get(results, "large_tiles")["total_conflicts_no_padding"] == 4096

    def test_total_with_padding(self, results):
        assert _get(results, "large_tiles")["total_conflicts_with_padding"] == 3072


# ---------------------------------------------------------------------------
# Cross-scenario consistency checks
# ---------------------------------------------------------------------------
class TestCrossScenario:
    def test_all_scenarios_present(self, results):
        names = {s["name"] for s in results["scenarios"]}
        assert names == {"small_tiles", "medium_tiles", "large_tiles"}

    def test_totals_are_sums(self, results):
        for s in results["scenarios"]:
            assert s["total_conflicts_no_padding"] == (
                s["a_tile"]["conflicts_no_padding"]
                + s["b_tile"]["conflicts_no_padding"]
            ), f"total mismatch for {s['name']} (no padding)"
            assert s["total_conflicts_with_padding"] == (
                s["a_tile"]["conflicts_with_padding"]
                + s["b_tile"]["conflicts_with_padding"]
            ), f"total mismatch for {s['name']} (with padding)"

    def test_padding_never_increases_conflicts(self, results):
        for s in results["scenarios"]:
            assert (
                s["a_tile"]["conflicts_with_padding"]
                <= s["a_tile"]["conflicts_no_padding"]
            )
            assert (
                s["b_tile"]["conflicts_with_padding"]
                <= s["b_tile"]["conflicts_no_padding"]
            )


# ---------------------------------------------------------------------------
# SQLite output verification
# ---------------------------------------------------------------------------
class TestSQLiteOutput:
    @pytest.fixture(scope="class")
    def db_rows(self, results):
        """Load analysis.db rows. Depends on results to ensure script has run."""
        db_path = "/app/analysis.db"
        assert os.path.isfile(db_path), "analysis.db was not created"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM conflict_analysis ORDER BY kernel_name"
        ).fetchall()
        conn.close()
        return {r["kernel_name"]: dict(r) for r in rows}

    def test_table_has_all_kernels(self, db_rows):
        assert len(db_rows) == 3
        assert set(db_rows.keys()) == {"small_tiles", "medium_tiles", "large_tiles"}

    def test_small_tiles_db(self, db_rows):
        r = db_rows["small_tiles"]
        assert r["num_threads"] == 64
        assert r["num_warps"] == 2
        assert r["a_conflicts_no_padding"] == 192
        assert r["a_optimal_skew"] == 1
        assert r["a_conflicts_with_padding"] == 0
        assert r["b_conflicts_no_padding"] == 0
        assert r["b_optimal_skew"] == 0
        assert r["b_conflicts_with_padding"] == 0
        assert r["total_conflicts_no_padding"] == 192
        assert r["total_conflicts_with_padding"] == 0

    def test_medium_tiles_db(self, db_rows):
        r = db_rows["medium_tiles"]
        assert r["num_threads"] == 256
        assert r["num_warps"] == 8
        assert r["a_conflicts_no_padding"] == 256
        assert r["a_optimal_skew"] == 1
        assert r["a_conflicts_with_padding"] == 0
        assert r["b_conflicts_no_padding"] == 256
        assert r["b_optimal_skew"] == 0
        assert r["b_conflicts_with_padding"] == 256
        assert r["total_conflicts_no_padding"] == 512
        assert r["total_conflicts_with_padding"] == 256

    def test_large_tiles_db(self, db_rows):
        r = db_rows["large_tiles"]
        assert r["num_threads"] == 256
        assert r["num_warps"] == 8
        assert r["a_conflicts_no_padding"] == 1024
        assert r["a_optimal_skew"] == 1
        assert r["a_conflicts_with_padding"] == 0
        assert r["b_conflicts_no_padding"] == 3072
        assert r["b_optimal_skew"] == 0
        assert r["b_conflicts_with_padding"] == 3072
        assert r["total_conflicts_no_padding"] == 4096
        assert r["total_conflicts_with_padding"] == 3072

    def test_db_json_consistency(self, results, db_rows):
        """Verify SQLite and JSON outputs match."""
        for s in results["scenarios"]:
            name = s["name"]
            assert name in db_rows, f"{name} missing from analysis.db"
            r = db_rows[name]
            assert r["num_threads"] == s["num_threads"]
            assert r["num_warps"] == s["num_warps"]
            assert r["a_conflicts_no_padding"] == s["a_tile"]["conflicts_no_padding"]
            assert r["a_optimal_skew"] == s["a_tile"]["optimal_skew"]
            assert r["a_conflicts_with_padding"] == s["a_tile"]["conflicts_with_padding"]
            assert r["b_conflicts_no_padding"] == s["b_tile"]["conflicts_no_padding"]
            assert r["b_optimal_skew"] == s["b_tile"]["optimal_skew"]
            assert r["b_conflicts_with_padding"] == s["b_tile"]["conflicts_with_padding"]
            assert r["total_conflicts_no_padding"] == s["total_conflicts_no_padding"]
            assert r["total_conflicts_with_padding"] == s["total_conflicts_with_padding"]
