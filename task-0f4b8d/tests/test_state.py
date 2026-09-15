"""
Test suite for Sudoku Unavoidable Set Pipeline Analysis.

Verifies correctness, minimality, completeness (for sizes 4 and 6),
MCN validity, clique counts, and database state.

"""

import json
import os
import sqlite3
import pytest
from itertools import combinations


# -- Grid utilities --

def parse_grid(filepath):
    grid = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and len(line) >= 9:
                grid.append([int(c) for c in line[:9]])
    return grid


def ci(r, c):
    return r * 9 + c


def rc(idx):
    return idx // 9, idx % 9


def box_of(r, c):
    return (r // 3) * 3 + c // 3


# -- Sudoku solver --

def solve_count(grid, empty_cells, max_count=2):
    board = [row[:] for row in grid]
    for r, c in empty_cells:
        board[r][c] = 0

    row_used = [0] * 9
    col_used = [0] * 9
    box_used = [0] * 9
    for r in range(9):
        for c in range(9):
            if board[r][c]:
                bit = 1 << board[r][c]
                row_used[r] |= bit
                col_used[c] |= bit
                box_used[box_of(r, c)] |= bit

    empties = []
    for r, c in empty_cells:
        b = box_of(r, c)
        used = row_used[r] | col_used[c] | box_used[b]
        ncands = bin(((1 << 10) - 2) & ~used).count('1')
        empties.append((ncands, r, c))
    empties.sort()
    empties = [(r, c) for _, r, c in empties]

    count = [0]

    def solve(idx):
        if count[0] >= max_count:
            return
        if idx == len(empties):
            count[0] += 1
            return
        r, c = empties[idx]
        b = box_of(r, c)
        used = row_used[r] | col_used[c] | box_used[b]
        for v in range(1, 10):
            bit = 1 << v
            if not (used & bit):
                board[r][c] = v
                row_used[r] |= bit
                col_used[c] |= bit
                box_used[b] |= bit
                solve(idx + 1)
                if count[0] >= max_count:
                    board[r][c] = 0
                    row_used[r] ^= bit
                    col_used[c] ^= bit
                    box_used[b] ^= bit
                    return
                board[r][c] = 0
                row_used[r] ^= bit
                col_used[c] ^= bit
                box_used[b] ^= bit

    solve(0)
    return count[0]


def is_unavoidable(grid, cells):
    empty = [rc(idx) for idx in cells]
    return solve_count(grid, empty, 2) >= 2


# -- Independent unavoidable set finder for sizes 4 and 6 --

def find_all_size4_sets(grid):
    results = set()
    for r1, r2 in combinations(range(9), 2):
        for c1, c2 in combinations(range(9), 2):
            v11 = grid[r1][c1]
            v12 = grid[r1][c2]
            v21 = grid[r2][c1]
            v22 = grid[r2][c2]
            if v11 == v22 and v12 == v21 and v11 != v12:
                boxes = {}
                for idx in [ci(r1, c1), ci(r1, c2), ci(r2, c1), ci(r2, c2)]:
                    rr, cc = rc(idx)
                    bx = box_of(rr, cc)
                    boxes[bx] = boxes.get(bx, 0) + 1
                if all(cnt >= 2 for cnt in boxes.values()):
                    cells = tuple(sorted([ci(r1, c1), ci(r1, c2), ci(r2, c1), ci(r2, c2)]))
                    if is_unavoidable(grid, list(cells)):
                        results.add(cells)
    return results


def find_all_size6_2digit_sets(grid):
    results = set()
    for a in range(1, 10):
        for b in range(a + 1, 10):
            pos_a = {}
            pos_b = {}
            for r in range(9):
                for c in range(9):
                    if grid[r][c] == a:
                        pos_a[r] = c
                    elif grid[r][c] == b:
                        pos_b[r] = c

            row_of_col_a = {}
            for r in range(9):
                row_of_col_a[pos_a[r]] = r

            col_perm = {}
            for c_val in range(9):
                r = row_of_col_a[c_val]
                col_perm[c_val] = pos_b[r]

            visited = set()
            for start in range(9):
                if start in visited:
                    continue
                cycle_cols = []
                c_val = start
                while c_val not in visited:
                    visited.add(c_val)
                    cycle_cols.append(c_val)
                    c_val = col_perm[c_val]
                if len(cycle_cols) == 3:
                    rows = frozenset(row_of_col_a[cc] for cc in cycle_cols)
                    bx_perm = {}
                    for r in rows:
                        ba = box_of(r, pos_a[r])
                        bb = box_of(r, pos_b[r])
                        bx_perm[ba] = bb
                    box_vals = list(bx_perm.keys())
                    bx_visited = set()
                    all_ok = True
                    for start_b in box_vals:
                        if start_b in bx_visited:
                            continue
                        x = start_b
                        while x not in bx_visited:
                            bx_visited.add(x)
                            if x not in bx_perm:
                                all_ok = False
                                break
                            x = bx_perm[x]
                        if not all_ok:
                            break
                    if all_ok:
                        cells = tuple(sorted(
                            [ci(r, pos_a[r]) for r in rows] +
                            [ci(r, pos_b[r]) for r in rows]
                        ))
                        if is_unavoidable(grid, list(cells)):
                            results.add(cells)
    return results


def find_all_size6_3digit_sets(grid):
    results = set()

    for band in range(3):
        brows = [band * 3 + i for i in range(3)]
        for r1, r2 in combinations(brows, 2):
            for c1, c2, c3 in combinations(range(9), 3):
                cells_list = [ci(r1, c1), ci(r1, c2), ci(r1, c3),
                              ci(r2, c1), ci(r2, c2), ci(r2, c3)]
                vals = set(grid[rc(idx)[0]][rc(idx)[1]] for idx in cells_list)
                if len(vals) != 3:
                    continue
                v1 = [grid[r1][c] for c in [c1, c2, c3]]
                v2 = [grid[r2][c] for c in [c1, c2, c3]]
                if set(v1) != vals or set(v2) != vals:
                    continue
                if any(v1[i] == v2[i] for i in range(3)):
                    continue
                bx_counts = {}
                for idx in cells_list:
                    rr, cc = rc(idx)
                    bx = box_of(rr, cc)
                    bx_counts[bx] = bx_counts.get(bx, 0) + 1
                if any(cnt == 1 for cnt in bx_counts.values()):
                    continue
                cells = tuple(sorted(cells_list))
                if is_unavoidable(grid, list(cells)):
                    results.add(cells)

    for stack in range(3):
        scols = [stack * 3 + i for i in range(3)]
        for c1, c2 in combinations(scols, 2):
            for r1, r2, r3 in combinations(range(9), 3):
                cells_list = [ci(r1, c1), ci(r1, c2),
                              ci(r2, c1), ci(r2, c2),
                              ci(r3, c1), ci(r3, c2)]
                vals = set(grid[rc(idx)[0]][rc(idx)[1]] for idx in cells_list)
                if len(vals) != 3:
                    continue
                for cc in [c1, c2]:
                    col_vals = [grid[r][cc] for r in [r1, r2, r3]]
                    if set(col_vals) != vals:
                        vals = set()
                        break
                if len(vals) != 3:
                    continue
                for r in [r1, r2, r3]:
                    if grid[r][c1] == grid[r][c2]:
                        vals = set()
                        break
                if len(vals) != 3:
                    continue
                bx_counts = {}
                for idx in cells_list:
                    rr, cc_v = rc(idx)
                    bx = box_of(rr, cc_v)
                    bx_counts[bx] = bx_counts.get(bx, 0) + 1
                if any(cnt == 1 for cnt in bx_counts.values()):
                    continue
                cells = tuple(sorted(cells_list))
                if is_unavoidable(grid, list(cells)):
                    results.add(cells)

    for rows_t in combinations(range(9), 3):
        for cols_t in combinations(range(9), 3):
            perms = [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)]
            for perm in perms:
                cells_list = []
                for i in range(3):
                    for j in range(3):
                        if j != perm[i]:
                            cells_list.append(ci(rows_t[i], cols_t[j]))
                vals = set(grid[rc(idx)[0]][rc(idx)[1]] for idx in cells_list)
                if len(vals) != 3:
                    continue
                bx_counts = {}
                for idx in cells_list:
                    rr, cc_v = rc(idx)
                    bx = box_of(rr, cc_v)
                    bx_counts[bx] = bx_counts.get(bx, 0) + 1
                if any(cnt == 1 for cnt in bx_counts.values()):
                    continue
                cells = tuple(sorted(cells_list))
                if is_unavoidable(grid, list(cells)):
                    is_min = True
                    for sub in combinations(cells, 4):
                        if is_unavoidable(grid, list(sub)):
                            is_min = False
                            break
                    if is_min:
                        results.add(cells)

    return results


# -- Clique utilities --

def build_disj_adj(sets_list):
    n = len(sets_list)
    adj = {i: set() for i in range(n)}
    for i in range(n):
        si = set(sets_list[i])
        for j in range(i + 1, n):
            if not (si & set(sets_list[j])):
                adj[i].add(j)
                adj[j].add(i)
    return adj


def max_clique_bk(adj, n):
    best = []
    def bk(R, P, X):
        nonlocal best
        if not P and not X:
            if len(R) > len(best):
                best = list(R)
            return
        if not P:
            return
        pivot = max(P | X, key=lambda v: len(adj[v] & P))
        for v in sorted(P - adj[pivot]):
            bk(R | {v}, P & adj[v], X & adj[v])
            P -= {v}
            X |= {v}
    bk(set(), set(range(n)), set())
    return best


def count_cliques(adj, n, target):
    count = [0]
    def enum(clique, candidates, min_v):
        if len(clique) == target:
            count[0] += 1
            return
        rem = target - len(clique)
        cands = sorted(v for v in candidates if v >= min_v)
        for idx_c, v in enumerate(cands):
            if len(cands) - idx_c < rem:
                break
            new_cands = set(cands[idx_c + 1:]) & adj[v]
            enum(clique + [v], new_cands, v + 1)
    enum([], set(range(n)), 0)
    return count[0]


# -- Fixtures --

@pytest.fixture(scope="module")
def grid():
    return parse_grid('/app/grid.txt')


@pytest.fixture(scope="module")
def results():
    assert os.path.exists('/app/results.json'), "results.json not found"
    with open('/app/results.json') as f:
        return json.load(f)


@pytest.fixture(scope="module")
def ref_size4(grid):
    return find_all_size4_sets(grid)


@pytest.fixture(scope="module")
def ref_size6_2dig(grid):
    return find_all_size6_2digit_sets(grid)


@pytest.fixture(scope="module")
def ref_size6_3dig(grid):
    return find_all_size6_3digit_sets(grid)


# -- Tests --

class TestResultsFormat:
    def test_results_file_exists(self):
        assert os.path.exists('/app/results.json')

    def test_required_keys(self, results):
        for key in ["unavoidable_sets", "total_count", "mcn", "max_clique_indices", "clique_counts"]:
            assert key in results, f"Missing key: {key}"

    def test_total_count_matches(self, results):
        assert results["total_count"] == len(results["unavoidable_sets"])

    def test_sets_are_sorted(self, results):
        for s in results["unavoidable_sets"]:
            assert s == sorted(s), f"Unavoidable set not sorted: {s}"

    def test_cell_indices_valid(self, results):
        for s in results["unavoidable_sets"]:
            for idx in s:
                assert 0 <= idx <= 80, f"Invalid cell index: {idx}"

    def test_no_duplicate_sets(self, results):
        tuples = [tuple(s) for s in results["unavoidable_sets"]]
        assert len(tuples) == len(set(tuples)), "Duplicate unavoidable sets found"

    def test_reasonable_count(self, results):
        assert results["total_count"] >= 30, "Too few unavoidable sets"

    def test_sizes_within_limit(self, results):
        for s in results["unavoidable_sets"]:
            assert len(s) <= 12, f"Set exceeds size limit: {len(s)}"


class TestUnavoidability:
    def test_sample_sets_unavoidable(self, grid, results):
        sets = results["unavoidable_sets"]
        tested = 0
        for s in sets:
            if len(s) <= 6 or tested < 50:
                assert is_unavoidable(grid, s), f"Set {s} is NOT unavoidable"
                tested += 1

    def test_sample_sets_minimal(self, grid, results):
        sets = results["unavoidable_sets"]
        tested = 0
        for s in sets:
            if len(s) <= 6 or tested < 30:
                for i in range(len(s)):
                    subset = s[:i] + s[i + 1:]
                    assert not is_unavoidable(grid, subset), \
                        f"Set {s} is not minimal: subset without index {s[i]} is also unavoidable"
                tested += 1


class TestCompleteness:
    def test_all_size4_found(self, results, ref_size4):
        reported = set(tuple(s) for s in results["unavoidable_sets"] if len(s) == 4)
        for s in ref_size4:
            assert s in reported, f"Missing size-4 unavoidable set: {s}"

    def test_size4_count(self, results, ref_size4):
        reported_4 = [s for s in results["unavoidable_sets"] if len(s) == 4]
        assert len(reported_4) == len(ref_size4), \
            f"Size-4 count mismatch: reported {len(reported_4)}, expected {len(ref_size4)}"

    def test_all_size6_2digit_found(self, results, ref_size6_2dig):
        reported = set(tuple(s) for s in results["unavoidable_sets"] if len(s) == 6)
        for s in ref_size6_2dig:
            assert s in reported, f"Missing 2-digit size-6 unavoidable set: {s}"

    def test_all_size6_3digit_found(self, results, ref_size6_3dig):
        reported = set(tuple(s) for s in results["unavoidable_sets"] if len(s) == 6)
        for s in ref_size6_3dig:
            assert s in reported, f"Missing 3-digit size-6 unavoidable set: {s}"


class TestMCN:
    def test_mcn_positive(self, results):
        assert results["mcn"] >= 2, "MCN should be at least 2"

    def test_max_clique_valid(self, results):
        sets = results["unavoidable_sets"]
        clique_idx = results["max_clique_indices"]
        assert len(clique_idx) == results["mcn"]

        for i, j in combinations(clique_idx, 2):
            si = set(sets[i])
            sj = set(sets[j])
            assert not (si & sj), \
                f"Max clique contains non-disjoint sets at indices {i} and {j}"

    def test_max_clique_indices_valid(self, results):
        clique_idx = results["max_clique_indices"]
        n = results["total_count"]
        for idx in clique_idx:
            assert 0 <= idx < n, f"Invalid clique index: {idx}"

    def test_mcn_independently(self, results):
        sets = results["unavoidable_sets"]
        adj = build_disj_adj(sets)
        mc = max_clique_bk(adj, len(sets))
        assert results["mcn"] == len(mc), \
            f"MCN mismatch: reported {results['mcn']}, computed {len(mc)}"


class TestCliqueCounts:
    def test_clique_counts_present(self, results):
        for k in ["2", "3", "4", "5"]:
            assert k in results["clique_counts"], f"Missing clique count for size {k}"

    def test_clique_count_size2(self, results):
        sets = results["unavoidable_sets"]
        adj = build_disj_adj(sets)
        expected = count_cliques(adj, len(sets), 2)
        assert results["clique_counts"]["2"] == expected, \
            f"Size-2 clique count mismatch: reported {results['clique_counts']['2']}, expected {expected}"

    def test_clique_count_size3(self, results):
        sets = results["unavoidable_sets"]
        adj = build_disj_adj(sets)
        expected = count_cliques(adj, len(sets), 3)
        assert results["clique_counts"]["3"] == expected, \
            f"Size-3 clique count mismatch: reported {results['clique_counts']['3']}, expected {expected}"

    def test_clique_count_nonnegative(self, results):
        for k, v in results["clique_counts"].items():
            assert v >= 0, f"Negative clique count for size {k}"

    def test_clique_count_monotone(self, results):
        cc = results["clique_counts"]
        mcn = results["mcn"]
        for k_str, cnt in cc.items():
            k = int(k_str)
            if k > mcn:
                assert cnt == 0, f"Clique of size {k} > MCN={mcn} should be 0"


class TestDatabaseUpdate:
    def test_valid_clique_analysis_exists(self):
        conn = sqlite3.connect('/app/analysis.db')
        row = conn.execute(
            "SELECT mcn FROM clique_analysis WHERE grid_id=1 AND is_valid=1"
        ).fetchone()
        conn.close()
        assert row is not None, "No valid clique analysis in database (is_valid=1)"

    def test_database_mcn_matches_json(self, results):
        conn = sqlite3.connect('/app/analysis.db')
        row = conn.execute(
            "SELECT mcn FROM clique_analysis WHERE grid_id=1 AND is_valid=1"
        ).fetchone()
        conn.close()
        assert row is not None, "No valid clique analysis in database"
        assert row[0] == results["mcn"], \
            f"Database MCN {row[0]} != results.json MCN {results['mcn']}"
