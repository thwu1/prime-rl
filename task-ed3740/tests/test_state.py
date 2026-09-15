"""

Tests for the Sudoku Unavoidable Set Analysis task.
Verifies correct database querying, structural correctness, and expected counts.
"""

import json
import os
import sqlite3
import subprocess
import pytest
from itertools import combinations


# ---------------------------------------------------------------------------
# C solver integration for independent verification
# ---------------------------------------------------------------------------

def _ensure_solver():
    """Compile C solver if not already built."""
    solver = "/app/tools/sudoku_solver"
    if not os.path.exists(solver):
        subprocess.run(["make", "-C", "/app/tools"], check=True)
    return solver


def count_solutions_c(puzzle_str, limit=2):
    """Count solutions using the compiled C solver."""
    solver = _ensure_solver()
    result = subprocess.run(
        [solver, puzzle_str, str(limit)],
        capture_output=True, text=True, timeout=30
    )
    return int(result.stdout.strip())


def is_unavoidable(grid_str, cell_set):
    """Check if removing cell_set from grid creates multiple completions."""
    puzzle = list(grid_str)
    for i in cell_set:
        puzzle[i] = '0'
    return count_solutions_c(''.join(puzzle), 2) >= 2


# ---------------------------------------------------------------------------
# Database verification
# ---------------------------------------------------------------------------

def get_pending_ua_mcn_grids():
    """Independently query database for grids with pending ua_mcn tasks."""
    conn = sqlite3.connect("/app/sudoku_archive.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT g.grid_id, g.grid_string
        FROM completed_grids g
        JOIN analysis_queue q ON g.grid_id = q.grid_id
        WHERE q.analysis_type = 'ua_mcn' AND q.status = 'pending'
        ORDER BY g.grid_id
    """)
    rows = cur.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}


# ---------------------------------------------------------------------------
# Expected values (computed by reference solution)
# ---------------------------------------------------------------------------

EXPECTED = {
    7: {"ua4_count": 0, "ua6_count": 108, "mcn": 12},
    12: {"ua4_count": 13, "ua6_count": 6, "mcn": 9},
}

GRIDS = {
    7: "123456789456789123789123456231564897564897231897231564312645978645978312978312645",
    12: "483921657967345821251876493548132976729564138136798245372689514814253769695417382",
}


# ---------------------------------------------------------------------------
# Load results
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), f"Results file not found at {results_path}"
    with open(results_path) as f:
        data = json.load(f)
    assert isinstance(data, list), "Results must be a JSON list"
    assert len(data) == 2, f"Expected 2 grid results, got {len(data)}"
    return {r["grid_id"]: r for r in data}


# ---------------------------------------------------------------------------
# Database integration tests
# ---------------------------------------------------------------------------

class TestDatabaseIntegration:
    def test_correct_grids_selected(self, results):
        """Agent should have selected exactly the grids with pending ua_mcn tasks."""
        expected_ids = set(EXPECTED.keys())
        actual_ids = set(results.keys())
        assert actual_ids == expected_ids, \
            f"Expected grid_ids {expected_ids}, got {actual_ids}. " \
            f"Agent must query the database for pending ua_mcn analysis tasks."

    def test_grid_ids_match_database(self):
        """Verify our expected grid_ids match what's actually in the database."""
        pending = get_pending_ua_mcn_grids()
        assert set(pending.keys()) == set(EXPECTED.keys())


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestStructure:
    def test_results_format(self, results):
        for gid, r in results.items():
            assert isinstance(r, dict)
            for key in ["grid_id", "ua4_count", "ua6_count", "mcn",
                        "max_clique", "ua4_sets", "ua6_sets"]:
                assert key in r, f"Grid {gid} missing key '{key}'"

    def test_grid_ids_present(self, results):
        assert set(results.keys()) == {7, 12}


# ---------------------------------------------------------------------------
# Grid 7 (canonical) tests
# ---------------------------------------------------------------------------

class TestGrid7:
    GID = 7

    def test_ua4_count(self, results):
        r = results[self.GID]
        assert r["ua4_count"] == EXPECTED[self.GID]["ua4_count"], \
            f"Grid {self.GID}: expected {EXPECTED[self.GID]['ua4_count']} UA4 sets, got {r['ua4_count']}"

    def test_ua6_count(self, results):
        r = results[self.GID]
        assert r["ua6_count"] == EXPECTED[self.GID]["ua6_count"], \
            f"Grid {self.GID}: expected {EXPECTED[self.GID]['ua6_count']} UA6 sets, got {r['ua6_count']}"

    def test_mcn(self, results):
        r = results[self.GID]
        assert r["mcn"] == EXPECTED[self.GID]["mcn"], \
            f"Grid {self.GID}: expected MCN {EXPECTED[self.GID]['mcn']}, got {r['mcn']}"

    def test_ua4_sets_empty(self, results):
        assert len(results[self.GID]["ua4_sets"]) == 0, \
            "Grid 7 (canonical) should have no size-4 UA sets"

    def test_ua6_sets_are_unavoidable(self, results):
        """Verify a sample of claimed UA6 sets are truly unavoidable via C solver."""
        r = results[self.GID]
        grid_str = GRIDS[self.GID]
        sample = r["ua6_sets"][:5] + r["ua6_sets"][-5:]
        for s in sample:
            assert len(s) == 6, f"UA6 set should have 6 elements, got {len(s)}"
            assert is_unavoidable(grid_str, s), \
                f"Claimed UA6 set {s} is NOT unavoidable for grid {self.GID}"

    def test_ua6_digit_structure(self, results):
        """Each UA6 set should contain exactly 3 distinct digits, each appearing twice."""
        r = results[self.GID]
        grid_str = GRIDS[self.GID]
        for s in r["ua6_sets"]:
            digits = [int(grid_str[ci]) for ci in s]
            counts = {}
            for d in digits:
                counts[d] = counts.get(d, 0) + 1
            assert len(counts) == 3, \
                f"UA6 set {s} should have 3 distinct digits, got {len(counts)}"
            assert all(v == 2 for v in counts.values()), \
                f"UA6 set {s} digits should each appear twice, got {counts}"

    def test_max_clique_valid(self, results):
        """The max clique should consist of pairwise disjoint sets."""
        r = results[self.GID]
        clique = r["max_clique"]
        assert len(clique) == r["mcn"], \
            f"Max clique size {len(clique)} != MCN {r['mcn']}"
        for i in range(len(clique)):
            for j in range(i + 1, len(clique)):
                overlap = set(clique[i]) & set(clique[j])
                assert len(overlap) == 0, \
                    f"Clique sets {i} and {j} overlap: {overlap}"

    def test_max_clique_from_ua_sets(self, results):
        """Each set in the max clique should be in ua4_sets or ua6_sets."""
        r = results[self.GID]
        all_ua = set()
        for s in r["ua4_sets"]:
            all_ua.add(tuple(sorted(s)))
        for s in r["ua6_sets"]:
            all_ua.add(tuple(sorted(s)))
        for s in r["max_clique"]:
            assert tuple(sorted(s)) in all_ua, \
                f"Clique set {s} not found in UA sets"


# ---------------------------------------------------------------------------
# Grid 12 tests
# ---------------------------------------------------------------------------

class TestGrid12:
    GID = 12

    def test_ua4_count(self, results):
        r = results[self.GID]
        assert r["ua4_count"] == EXPECTED[self.GID]["ua4_count"], \
            f"Grid {self.GID}: expected {EXPECTED[self.GID]['ua4_count']} UA4 sets, got {r['ua4_count']}"

    def test_ua6_count(self, results):
        r = results[self.GID]
        assert r["ua6_count"] == EXPECTED[self.GID]["ua6_count"], \
            f"Grid {self.GID}: expected {EXPECTED[self.GID]['ua6_count']} UA6 sets, got {r['ua6_count']}"

    def test_mcn(self, results):
        r = results[self.GID]
        assert r["mcn"] == EXPECTED[self.GID]["mcn"], \
            f"Grid {self.GID}: expected MCN {EXPECTED[self.GID]['mcn']}, got {r['mcn']}"

    def test_ua4_sets_are_unavoidable(self, results):
        """Verify all claimed UA4 sets are truly unavoidable via C solver."""
        r = results[self.GID]
        grid_str = GRIDS[self.GID]
        for s in r["ua4_sets"]:
            assert len(s) == 4, f"UA4 set should have 4 elements, got {len(s)}"
            assert is_unavoidable(grid_str, s), \
                f"Claimed UA4 set {s} is NOT unavoidable for grid {self.GID}"

    def test_ua4_digit_structure(self, results):
        """Each UA4 set should contain exactly 2 distinct digits, each appearing twice."""
        r = results[self.GID]
        grid_str = GRIDS[self.GID]
        for s in r["ua4_sets"]:
            digits = [int(grid_str[ci]) for ci in s]
            counts = {}
            for d in digits:
                counts[d] = counts.get(d, 0) + 1
            assert len(counts) == 2, \
                f"UA4 set {s} should have 2 distinct digits, got {len(counts)}"
            assert all(v == 2 for v in counts.values()), \
                f"UA4 set {s} digits should each appear twice, got {counts}"

    def test_ua6_sets_are_unavoidable(self, results):
        """Verify all claimed UA6 sets are truly unavoidable via C solver."""
        r = results[self.GID]
        grid_str = GRIDS[self.GID]
        for s in r["ua6_sets"]:
            assert len(s) == 6, f"UA6 set should have 6 elements, got {len(s)}"
            assert is_unavoidable(grid_str, s), \
                f"Claimed UA6 set {s} is NOT unavoidable for grid {self.GID}"

    def test_max_clique_valid(self, results):
        """The max clique should consist of pairwise disjoint sets."""
        r = results[self.GID]
        clique = r["max_clique"]
        assert len(clique) == r["mcn"], \
            f"Max clique size {len(clique)} != MCN {r['mcn']}"
        for i in range(len(clique)):
            for j in range(i + 1, len(clique)):
                overlap = set(clique[i]) & set(clique[j])
                assert len(overlap) == 0, \
                    f"Clique sets {i} and {j} overlap: {overlap}"

    def test_max_clique_from_ua_sets(self, results):
        """Each set in the max clique should be in ua4_sets or ua6_sets."""
        r = results[self.GID]
        all_ua = set()
        for s in r["ua4_sets"]:
            all_ua.add(tuple(sorted(s)))
        for s in r["ua6_sets"]:
            all_ua.add(tuple(sorted(s)))
        for s in r["max_clique"]:
            assert tuple(sorted(s)) in all_ua, \
                f"Clique set {s} not found in UA sets"

    def test_ua6_minimality(self, results):
        """UA6 sets should not contain any UA4 subset."""
        r = results[self.GID]
        ua4_tuples = set(tuple(sorted(s)) for s in r["ua4_sets"])
        for s in r["ua6_sets"]:
            for combo in combinations(sorted(s), 4):
                assert combo not in ua4_tuples, \
                    f"UA6 set {s} contains UA4 subset {combo} — not minimal"


# ---------------------------------------------------------------------------
# Cross-grid consistency tests
# ---------------------------------------------------------------------------

class TestConsistency:
    def test_sets_sorted(self, results):
        """All sets should be sorted internally."""
        for gid, r in results.items():
            for s in r["ua4_sets"]:
                assert s == sorted(s), f"Grid {gid}: UA4 set {s} not sorted"
            for s in r["ua6_sets"]:
                assert s == sorted(s), f"Grid {gid}: UA6 set {s} not sorted"

    def test_sets_lexicographically_ordered(self, results):
        """Set lists should be in lexicographic order."""
        for gid, r in results.items():
            for label in ["ua4_sets", "ua6_sets"]:
                sets = r[label]
                for i in range(len(sets) - 1):
                    assert sets[i] <= sets[i + 1], \
                        f"Grid {gid}: {label} not lexicographically sorted at index {i}"

    def test_no_duplicate_sets(self, results):
        """No duplicate sets within ua4_sets or ua6_sets."""
        for gid, r in results.items():
            ua4_tuples = [tuple(s) for s in r["ua4_sets"]]
            assert len(ua4_tuples) == len(set(ua4_tuples)), \
                f"Grid {gid}: duplicate UA4 sets"
            ua6_tuples = [tuple(s) for s in r["ua6_sets"]]
            assert len(ua6_tuples) == len(set(ua6_tuples)), \
                f"Grid {gid}: duplicate UA6 sets"

    def test_cell_indices_in_range(self, results):
        """All cell indices should be in [0, 80]."""
        for gid, r in results.items():
            for s in r["ua4_sets"] + r["ua6_sets"]:
                for ci in s:
                    assert 0 <= ci <= 80, f"Grid {gid}: cell index {ci} out of range"

    def test_mcn_positive_when_sets_exist(self, results):
        """MCN should be at least 1 if any UA sets exist."""
        for gid, r in results.items():
            total = len(r["ua4_sets"]) + len(r["ua6_sets"])
            if total > 0:
                assert r["mcn"] >= 1, f"Grid {gid}: MCN should be >= 1"
