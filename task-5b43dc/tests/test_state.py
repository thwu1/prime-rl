
import json
import os
import pytest


# ---------------------------------------------------------------------------
# Reference symbolic Cholesky implementation (independent of agent's code)
# ---------------------------------------------------------------------------

def parse_mm_lower(path):
    """Parse a Matrix Market file, return (n, list of (row, col, val)) lower triangle entries (0-indexed)."""
    entries = []
    n = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith('%'):
                continue
            parts = line.split()
            if n is None:
                n = int(parts[0])
                continue
            r, c, v = int(parts[0]) - 1, int(parts[1]) - 1, float(parts[2])
            entries.append((r, c, v))
    return n, entries


def build_full_adj(n, entries):
    """Build symmetric adjacency sets from lower-triangle entries."""
    adj = [set() for _ in range(n)]
    for i, j, _ in entries:
        if i != j:
            adj[i].add(j)
            adj[j].add(i)
    return adj


def symbolic_cholesky(n, entries, perm=None):
    """Run symbolic Cholesky with given ordering. Returns (nnz_L, parent, flop_count)."""
    if perm is None:
        perm = list(range(n))
    inv = [0] * n
    for new_idx, old_idx in enumerate(perm):
        inv[old_idx] = new_idx

    # Build column sets for lower triangle of permuted matrix
    cols = [set() for _ in range(n)]
    for j in range(n):
        cols[j].add(j)  # diagonal always present
    for oi, oj, _ in entries:
        ni, nj = inv[oi], inv[oj]
        if ni == nj:
            continue
        if ni > nj:
            cols[nj].add(ni)
        else:
            cols[ni].add(nj)

    # Simulate elimination
    for j in range(n):
        below = sorted(r for r in cols[j] if r > j)
        for r in below:
            for s in below:
                if s >= r:
                    cols[r].add(s)

    # Extract results
    parent = [-1] * n
    nnz_L = 0
    flops = 0
    for j in range(n):
        below = sorted(r for r in cols[j] if r > j)
        if below:
            parent[j] = below[0]
        c = len(below)
        flops += c * c + c
        nnz_L += 1 + c
    return nnz_L, parent, flops


def compute_etree_height(parent):
    """Compute elimination tree height (number of levels)."""
    n = len(parent)
    if n == 0:
        return 0
    depth = [0] * n
    for i in range(n):
        j, d = i, 0
        while parent[j] != -1:
            j = parent[j]
            d += 1
            if d > n:
                break
        depth[i] = d
    return max(depth) + 1


def connected_components(n, adj):
    vis = [False] * n
    cnt = 0
    for i in range(n):
        if not vis[i]:
            cnt += 1
            stk = [i]
            vis[i] = True
            while stk:
                nd = stk.pop()
                for nb in adj[nd]:
                    if not vis[nb]:
                        vis[nb] = True
                        stk.append(nb)
    return cnt


# ---------------------------------------------------------------------------
# Hardcoded expected values for natural ordering (fully deterministic)
# ---------------------------------------------------------------------------

EXPECTED_NATURAL = {
    "arrowhead_25": {"n": 25, "nnz_lower_A": 49, "num_components": 1,
                     "nnz_L": 325, "etree_height": 25, "flop_count": 5200},
    "grid5":        {"n": 25, "nnz_lower_A": 65, "num_components": 1,
                     "nnz_L": 129, "etree_height": 25, "flop_count": 588},
    "mesh6":        {"n": 36, "nnz_lower_A": 96, "num_components": 1,
                     "nnz_L": 221, "etree_height": 36, "flop_count": 1230},
}

MATRIX_DIR = "/app/matrices"
RESULTS_PATH = "/app/results.json"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def results():
    assert os.path.isfile(RESULTS_PATH), f"{RESULTS_PATH} does not exist"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="session", params=["arrowhead_25", "grid5", "mesh6"])
def matrix_name(request):
    return request.param


@pytest.fixture(scope="session")
def matrix_data():
    """Load all matrix files once."""
    data = {}
    for fname in os.listdir(MATRIX_DIR):
        if fname.endswith(".mtx"):
            name = fname[:-4]
            n, entries = parse_mm_lower(os.path.join(MATRIX_DIR, fname))
            data[name] = (n, entries)
    return data


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestResultsStructure:
    def test_results_file_exists(self, results):
        assert isinstance(results, dict)

    def test_all_matrices_present(self, results):
        for name in EXPECTED_NATURAL:
            assert name in results, f"Missing matrix {name} in results"

    def test_required_keys(self, results):
        for name in EXPECTED_NATURAL:
            r = results[name]
            for key in ["n", "nnz_lower_A", "num_components", "natural", "amd", "rcm", "best_ordering"]:
                assert key in r, f"Missing key {key} for {name}"
            for ordering in ["natural", "amd", "rcm"]:
                for metric in ["nnz_L", "etree_height", "flop_count"]:
                    assert metric in r[ordering], f"Missing {metric} in {name}.{ordering}"
            for ordering in ["amd", "rcm"]:
                assert "ordering" in r[ordering], f"Missing ordering vector in {name}.{ordering}"


class TestBasicProperties:
    @pytest.mark.parametrize("matrix_name", ["arrowhead_25", "grid5", "mesh6"])
    def test_dimension(self, results, matrix_name):
        exp = EXPECTED_NATURAL[matrix_name]
        assert results[matrix_name]["n"] == exp["n"]

    @pytest.mark.parametrize("matrix_name", ["arrowhead_25", "grid5", "mesh6"])
    def test_nnz_lower_A(self, results, matrix_name):
        exp = EXPECTED_NATURAL[matrix_name]
        assert results[matrix_name]["nnz_lower_A"] == exp["nnz_lower_A"]

    @pytest.mark.parametrize("matrix_name", ["arrowhead_25", "grid5", "mesh6"])
    def test_num_components(self, results, matrix_name):
        exp = EXPECTED_NATURAL[matrix_name]
        assert results[matrix_name]["num_components"] == exp["num_components"]


class TestNaturalOrdering:
    @pytest.mark.parametrize("matrix_name", ["arrowhead_25", "grid5", "mesh6"])
    def test_nnz_L(self, results, matrix_name):
        exp = EXPECTED_NATURAL[matrix_name]
        assert results[matrix_name]["natural"]["nnz_L"] == exp["nnz_L"], \
            f"{matrix_name}: expected nnz_L={exp['nnz_L']}, got {results[matrix_name]['natural']['nnz_L']}"

    @pytest.mark.parametrize("matrix_name", ["arrowhead_25", "grid5", "mesh6"])
    def test_etree_height(self, results, matrix_name):
        exp = EXPECTED_NATURAL[matrix_name]
        assert results[matrix_name]["natural"]["etree_height"] == exp["etree_height"]

    @pytest.mark.parametrize("matrix_name", ["arrowhead_25", "grid5", "mesh6"])
    def test_flop_count(self, results, matrix_name):
        exp = EXPECTED_NATURAL[matrix_name]
        assert results[matrix_name]["natural"]["flop_count"] == exp["flop_count"]


class TestOrderingValidity:
    """Verify that reported orderings are valid permutations."""
    @pytest.mark.parametrize("matrix_name", ["arrowhead_25", "grid5", "mesh6"])
    @pytest.mark.parametrize("ordering_name", ["amd", "rcm"])
    def test_valid_permutation(self, results, matrix_name, ordering_name):
        r = results[matrix_name]
        n = r["n"]
        perm = r[ordering_name]["ordering"]
        assert len(perm) == n, f"Ordering length {len(perm)} != n={n}"
        assert sorted(perm) == list(range(n)), \
            f"Ordering is not a valid permutation of 0..{n-1}"


class TestOrderingConsistency:
    """Independently verify nnz_L, etree_height, flop_count for reported orderings."""

    @pytest.mark.parametrize("matrix_name", ["arrowhead_25", "grid5", "mesh6"])
    @pytest.mark.parametrize("ordering_name", ["amd", "rcm"])
    def test_nnz_L_consistent(self, results, matrix_data, matrix_name, ordering_name):
        r = results[matrix_name]
        perm = r[ordering_name]["ordering"]
        n, entries = matrix_data[matrix_name]
        ref_nnz, _, _ = symbolic_cholesky(n, entries, perm)
        assert r[ordering_name]["nnz_L"] == ref_nnz, \
            f"{matrix_name}/{ordering_name}: reported nnz_L={r[ordering_name]['nnz_L']}, independently computed={ref_nnz}"

    @pytest.mark.parametrize("matrix_name", ["arrowhead_25", "grid5", "mesh6"])
    @pytest.mark.parametrize("ordering_name", ["amd", "rcm"])
    def test_etree_height_consistent(self, results, matrix_data, matrix_name, ordering_name):
        r = results[matrix_name]
        perm = r[ordering_name]["ordering"]
        n, entries = matrix_data[matrix_name]
        _, parent, _ = symbolic_cholesky(n, entries, perm)
        ref_height = compute_etree_height(parent)
        assert r[ordering_name]["etree_height"] == ref_height, \
            f"{matrix_name}/{ordering_name}: reported height={r[ordering_name]['etree_height']}, independently computed={ref_height}"

    @pytest.mark.parametrize("matrix_name", ["arrowhead_25", "grid5", "mesh6"])
    @pytest.mark.parametrize("ordering_name", ["amd", "rcm"])
    def test_flop_count_consistent(self, results, matrix_data, matrix_name, ordering_name):
        r = results[matrix_name]
        perm = r[ordering_name]["ordering"]
        n, entries = matrix_data[matrix_name]
        _, _, ref_flops = symbolic_cholesky(n, entries, perm)
        assert r[ordering_name]["flop_count"] == ref_flops, \
            f"{matrix_name}/{ordering_name}: reported flops={r[ordering_name]['flop_count']}, independently computed={ref_flops}"


class TestFillReduction:
    """Verify that orderings actually reduce fill-in."""

    @pytest.mark.parametrize("matrix_name", ["arrowhead_25", "grid5", "mesh6"])
    @pytest.mark.parametrize("ordering_name", ["amd", "rcm"])
    def test_not_worse_than_natural(self, results, matrix_name, ordering_name):
        nat_nnz = results[matrix_name]["natural"]["nnz_L"]
        opt_nnz = results[matrix_name][ordering_name]["nnz_L"]
        assert opt_nnz <= nat_nnz, \
            f"{matrix_name}/{ordering_name}: nnz_L={opt_nnz} > natural nnz_L={nat_nnz}"

    def test_arrowhead_dramatic_reduction(self, results):
        """Arrowhead matrix should show >80% fill reduction with any reasonable ordering."""
        nat_nnz = results["arrowhead_25"]["natural"]["nnz_L"]  # 325
        for ordering_name in ["amd", "rcm"]:
            opt_nnz = results["arrowhead_25"][ordering_name]["nnz_L"]
            reduction = 1.0 - opt_nnz / nat_nnz
            assert reduction > 0.80, \
                f"arrowhead_25/{ordering_name}: fill reduction {reduction:.2%} < 80%"

    @pytest.mark.parametrize("matrix_name", ["grid5", "mesh6"])
    def test_grid_some_reduction(self, results, matrix_name):
        """Grid matrices should show at least some fill reduction with AMD."""
        nat_nnz = results[matrix_name]["natural"]["nnz_L"]
        amd_nnz = results[matrix_name]["amd"]["nnz_L"]
        assert amd_nnz < nat_nnz, \
            f"{matrix_name}/amd: no fill reduction (nnz_L={amd_nnz} vs natural={nat_nnz})"


class TestBestOrdering:
    @pytest.mark.parametrize("matrix_name", ["arrowhead_25", "grid5", "mesh6"])
    def test_best_ordering_correct(self, results, matrix_name):
        r = results[matrix_name]
        orderings = {"natural": r["natural"]["nnz_L"],
                     "amd": r["amd"]["nnz_L"],
                     "rcm": r["rcm"]["nnz_L"]}
        actual_best = min(orderings, key=orderings.get)
        reported_best = r["best_ordering"]
        # The reported best must have the same nnz_L as the actual best (ties allowed)
        assert orderings[reported_best] == orderings[actual_best], \
            f"{matrix_name}: best_ordering={reported_best} has nnz_L={orderings[reported_best]}, " \
            f"but {actual_best} has nnz_L={orderings[actual_best]}"
