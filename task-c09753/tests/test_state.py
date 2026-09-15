
import json
import os
import pytest

INSTANCES_DIR = "/app/instances"
RESULTS_FILE = "/app/results.json"

# Ground truth: SAT/UNSAT classification for all 15 instances
EXPECTED_SAT = {
    "instance_01": True,   # n=10, 3 pre-placed
    "instance_02": True,   # n=15, 4 pre-placed
    "instance_03": True,   # n=25, 6 pre-placed
    "instance_04": True,   # n=50, 6 pre-placed
    "instance_05": True,   # n=80, 6 pre-placed
    "instance_06": True,   # n=60, 20 pre-placed (dense)
    "instance_07": False,  # n=8,  4 pre-placed UNSAT
    "instance_08": False,  # n=10, 5 pre-placed UNSAT
    "instance_09": False,  # n=12, 8 pre-placed UNSAT
    "instance_10": True,   # n=100, 6 pre-placed
    "instance_11": True,   # n=5, 0 pre-placed
    "count_01": True,      # n=8, 0 pre-placed (counting)
    "count_02": True,      # n=10, 1 pre-placed (counting)
    "count_03": True,      # n=12, 2 pre-placed (counting)
    "count_04": True,      # n=9, 3 pre-placed (counting)
}

UNSAT_INSTANCES = ["instance_07", "instance_08", "instance_09"]
COUNTING_INSTANCES = ["count_01", "count_02", "count_03", "count_04"]

# SAT instances with n <= 25, used for backtracker cross-verification.
# Hardcoded to avoid loading instance files at module collection time.
SMALL_SAT_INSTANCES = [
    "instance_01",  # n=10
    "instance_02",  # n=15
    "instance_03",  # n=25
    "instance_11",  # n=5
    "count_01",     # n=8
    "count_02",     # n=10
    "count_03",     # n=12
    "count_04",     # n=9
]


def load_instance(name):
    path = os.path.join(INSTANCES_DIR, f"{name}.json")
    with open(path, "r") as f:
        return json.load(f)


def load_results():
    with open(RESULTS_FILE, "r") as f:
        return json.load(f)


def is_valid_solution(n, pre_placed, queens):
    """Check that a proposed solution is a valid n-queens completion."""
    if not isinstance(queens, list):
        return False, "queens must be a list"
    if len(queens) != n:
        return False, f"expected {n} queens, got {len(queens)}"

    for i, c in enumerate(queens):
        if not isinstance(c, int) or c < 0 or c >= n:
            return False, f"invalid column {c} in row {i}"

    for r, c in pre_placed:
        if queens[r] != c:
            return False, f"pre-placed queen at ({r},{c}) not preserved, got column {queens[r]}"

    if len(set(queens)) != n:
        return False, "column conflict: two queens share the same column"

    pos_diags = set()
    neg_diags = set()
    for r in range(n):
        c = queens[r]
        pd = r + c
        nd = r - c
        if pd in pos_diags:
            return False, f"positive diagonal conflict at row {r}"
        if nd in neg_diags:
            return False, f"negative diagonal conflict at row {r}"
        pos_diags.add(pd)
        neg_diags.add(nd)

    return True, "valid"


def backtrack_solve(n, pre_placed):
    """
    Backtracking solver. Returns True if satisfiable, False if unsatisfiable.
    Suitable for n <= 30.
    """
    queens = [None] * n
    used_cols = set()
    used_pos_diag = set()
    used_neg_diag = set()

    for r, c in pre_placed:
        queens[r] = c
        used_cols.add(c)
        used_pos_diag.add(r + c)
        used_neg_diag.add(r - c)

    empty_rows = sorted([r for r in range(n) if queens[r] is None])

    def solve(idx):
        if idx == len(empty_rows):
            return True
        r = empty_rows[idx]
        for c in range(n):
            if c in used_cols:
                continue
            pd = r + c
            nd = r - c
            if pd in used_pos_diag or nd in used_neg_diag:
                continue
            queens[r] = c
            used_cols.add(c)
            used_pos_diag.add(pd)
            used_neg_diag.add(nd)
            if solve(idx + 1):
                return True
            queens[r] = None
            used_cols.remove(c)
            used_pos_diag.remove(pd)
            used_neg_diag.remove(nd)
        return False

    return solve(0)


def backtrack_count(n, pre_placed):
    """
    Count all valid n-queens completions using backtracking.
    Suitable for n <= 14.
    """
    queens = [None] * n
    used_cols = set()
    used_pos_diag = set()
    used_neg_diag = set()

    for r, c in pre_placed:
        queens[r] = c
        used_cols.add(c)
        used_pos_diag.add(r + c)
        used_neg_diag.add(r - c)

    empty_rows = sorted([r for r in range(n) if queens[r] is None])
    count = [0]

    def solve(idx):
        if idx == len(empty_rows):
            count[0] += 1
            return
        r = empty_rows[idx]
        for c in range(n):
            if c in used_cols:
                continue
            pd = r + c
            nd = r - c
            if pd in used_pos_diag or nd in used_neg_diag:
                continue
            queens[r] = c
            used_cols.add(c)
            used_pos_diag.add(pd)
            used_neg_diag.add(nd)
            solve(idx + 1)
            queens[r] = None
            used_cols.remove(c)
            used_pos_diag.remove(pd)
            used_neg_diag.remove(nd)

    solve(0)
    return count[0]


class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.isfile(RESULTS_FILE), f"{RESULTS_FILE} not found"

    def test_results_valid_json(self):
        results = load_results()
        assert isinstance(results, dict), "results.json must be a JSON object"


class TestAllInstancesCovered:
    def test_all_instances_present(self):
        results = load_results()
        for name in EXPECTED_SAT:
            assert name in results, f"missing result for {name}"


class TestPrePlacedValidity:
    """Verify that pre-placed queens in instances are mutually non-attacking."""

    @pytest.mark.parametrize("name", list(EXPECTED_SAT.keys()))
    def test_pre_placed_valid(self, name):
        instance = load_instance(name)
        n = instance["n"]
        pre_placed = instance["pre_placed"]

        rows = set()
        cols = set()
        pos_diags = set()
        neg_diags = set()

        for r, c in pre_placed:
            assert 0 <= r < n, f"row {r} out of range"
            assert 0 <= c < n, f"col {c} out of range"
            assert r not in rows, f"duplicate row {r}"
            assert c not in cols, f"duplicate col {c}"
            assert (r + c) not in pos_diags, f"positive diagonal conflict"
            assert (r - c) not in neg_diags, f"negative diagonal conflict"
            rows.add(r)
            cols.add(c)
            pos_diags.add(r + c)
            neg_diags.add(r - c)


class TestSatisfiableInstances:
    """Verify solutions for instances expected to be SAT."""

    @pytest.mark.parametrize("name", [k for k, v in EXPECTED_SAT.items() if v])
    def test_sat_instance(self, name):
        results = load_results()
        assert name in results, f"missing result for {name}"
        result = results[name]

        assert result["satisfiable"] is True, \
            f"{name} should be satisfiable but was reported as unsatisfiable"

        instance = load_instance(name)
        n = instance["n"]
        pre_placed = instance["pre_placed"]
        queens = result["queens"]

        valid, msg = is_valid_solution(n, pre_placed, queens)
        assert valid, f"{name} solution invalid: {msg}"


class TestUnsatisfiableInstances:
    """Verify UNSAT classification for instances expected to be UNSAT."""

    @pytest.mark.parametrize("name", UNSAT_INSTANCES)
    def test_unsat_instance(self, name):
        results = load_results()
        assert name in results, f"missing result for {name}"
        result = results[name]

        assert result["satisfiable"] is False, \
            f"{name} should be unsatisfiable but was reported as satisfiable"
        assert result["queens"] is None, \
            f"{name} is UNSAT, queens should be null"

    @pytest.mark.parametrize("name", UNSAT_INSTANCES)
    def test_unsat_verified_by_backtracker(self, name):
        """Double-check UNSAT classification using independent backtracking solver."""
        instance = load_instance(name)
        n = instance["n"]
        pre_placed = instance["pre_placed"]

        if n > 30:
            pytest.skip(f"n={n} too large for backtracking verification")

        is_sat = backtrack_solve(n, pre_placed)
        assert not is_sat, \
            f"{name} was reported UNSAT but backtracker found a solution"


class TestMinimalUnsatCore:
    """Verify that minimal_unsat_core is correct for UNSAT instances."""

    @pytest.mark.parametrize("name", UNSAT_INSTANCES)
    def test_mus_field_present(self, name):
        """UNSAT instances must include a minimal_unsat_core field."""
        results = load_results()
        result = results[name]
        assert "minimal_unsat_core" in result, \
            f"{name}: missing minimal_unsat_core field"
        mus = result["minimal_unsat_core"]
        assert isinstance(mus, list) and len(mus) > 0, \
            f"{name}: minimal_unsat_core must be a non-empty list"

    @pytest.mark.parametrize("name", UNSAT_INSTANCES)
    def test_mus_is_subset_of_preplaced(self, name):
        """MUS queens must be a subset of the original pre-placed queens."""
        results = load_results()
        instance = load_instance(name)
        mus = results[name]["minimal_unsat_core"]
        pre_set = {tuple(q) for q in instance["pre_placed"]}
        for q in mus:
            assert tuple(q) in pre_set, \
                f"{name}: MUS queen {q} is not in the original pre-placed set"

    @pytest.mark.parametrize("name", UNSAT_INSTANCES)
    def test_mus_queens_non_attacking(self, name):
        """MUS queens must be mutually non-attacking."""
        results = load_results()
        instance = load_instance(name)
        n = instance["n"]
        mus = results[name]["minimal_unsat_core"]
        rows = set()
        cols = set()
        pos_diags = set()
        neg_diags = set()
        for r, c in mus:
            assert r not in rows, f"duplicate row {r} in MUS"
            assert c not in cols, f"duplicate col {c} in MUS"
            assert (r + c) not in pos_diags, f"diagonal conflict in MUS"
            assert (r - c) not in neg_diags, f"diagonal conflict in MUS"
            rows.add(r)
            cols.add(c)
            pos_diags.add(r + c)
            neg_diags.add(r - c)

    @pytest.mark.parametrize("name", UNSAT_INSTANCES)
    def test_mus_is_unsatisfiable(self, name):
        """The MUS itself must be unsatisfiable."""
        results = load_results()
        instance = load_instance(name)
        n = instance["n"]
        mus = results[name]["minimal_unsat_core"]

        if n > 30:
            pytest.skip(f"n={n} too large for backtracking verification")

        assert not backtrack_solve(n, mus), \
            f"{name}: reported MUS is actually satisfiable"

    @pytest.mark.parametrize("name", UNSAT_INSTANCES)
    def test_mus_is_minimal(self, name):
        """Removing any single queen from the MUS must restore satisfiability."""
        results = load_results()
        instance = load_instance(name)
        n = instance["n"]
        mus = results[name]["minimal_unsat_core"]

        if n > 30:
            pytest.skip(f"n={n} too large for backtracking verification")

        for i in range(len(mus)):
            reduced = mus[:i] + mus[i+1:]
            assert backtrack_solve(n, reduced), \
                f"{name}: MUS is not minimal — still UNSAT after removing queen {mus[i]}"


class TestSolutionCounting:
    """Verify exact solution counts for counting instances."""

    @pytest.mark.parametrize("name", COUNTING_INSTANCES)
    def test_count_field_present(self, name):
        """Counting instances must include a solution_count field."""
        results = load_results()
        result = results[name]
        assert "solution_count" in result, \
            f"{name}: missing solution_count field"
        assert isinstance(result["solution_count"], int), \
            f"{name}: solution_count must be an integer"
        assert result["solution_count"] > 0, \
            f"{name}: solution_count must be positive (instance is SAT)"

    def test_eight_queens_known_count(self):
        """Verify the well-known 8-queens count (92) as a sanity check."""
        results = load_results()
        assert "count_01" in results, "missing count_01"
        assert results["count_01"]["solution_count"] == 92, \
            f"count_01 (standard 8-queens) must have exactly 92 solutions, " \
            f"got {results['count_01']['solution_count']}"

    @pytest.mark.parametrize("name", COUNTING_INSTANCES)
    def test_count_verified_by_backtracker(self, name):
        """Independently compute solution count and compare."""
        results = load_results()
        instance = load_instance(name)
        n = instance["n"]
        pre_placed = instance["pre_placed"]

        if n > 14:
            pytest.skip(f"n={n} too large for counting verification")

        expected_count = backtrack_count(n, pre_placed)
        reported_count = results[name]["solution_count"]
        assert reported_count == expected_count, \
            f"{name}: reported {reported_count} solutions, " \
            f"independently computed {expected_count}"


class TestSatInstancesVerifiedByBacktracker:
    """Cross-check SAT instances with small n using independent backtracker."""

    @pytest.mark.parametrize("name", SMALL_SAT_INSTANCES)
    def test_sat_verified_by_backtracker(self, name):
        instance = load_instance(name)
        n = instance["n"]
        pre_placed = instance["pre_placed"]

        is_sat = backtrack_solve(n, pre_placed)
        assert is_sat, \
            f"{name} expected SAT but backtracker found no solution"
