#!/usr/bin/env python3
"""
Sudoku Unavoidable Set Analysis — Reference Solution

Finds all minimal unavoidable sets of size <= 12, computes MCN, counts cliques.
Based on the theory from McGuire, Tugemann, Civario (2014).

Writes results to /app/results.json and updates /app/analysis.db.

"""

import json
import sqlite3
from itertools import combinations


def parse_grid(filepath):
    grid = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and len(line) >= 9:
                grid.append([int(c) for c in line[:9]])
    assert len(grid) == 9
    return grid


def ci(r, c):
    return r * 9 + c


def rc(idx):
    return idx // 9, idx % 9


def box_of(r, c):
    return (r // 3) * 3 + c // 3


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


def find_2digit_sets(grid, max_size=12):
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
            col_cycles = []
            for start in range(9):
                if start in visited:
                    continue
                cycle_cols = []
                c_val = start
                while c_val not in visited:
                    visited.add(c_val)
                    cycle_cols.append(c_val)
                    c_val = col_perm[c_val]
                if len(cycle_cols) >= 2:
                    col_cycles.append(frozenset(row_of_col_a[cc] for cc in cycle_cols))

            for num in range(1, len(col_cycles) + 1):
                for combo in combinations(col_cycles, num):
                    rows = frozenset()
                    for cyc in combo:
                        rows = rows | cyc
                    if len(rows) * 2 > max_size or len(rows) < 2:
                        continue
                    ba_counts = {}
                    bb_counts = {}
                    for r in rows:
                        ba = box_of(r, pos_a[r])
                        bb = box_of(r, pos_b[r])
                        ba_counts[ba] = ba_counts.get(ba, 0) + 1
                        bb_counts[bb] = bb_counts.get(bb, 0) + 1
                    if ba_counts == bb_counts:
                        cells = tuple(sorted(
                            [ci(r, pos_a[r]) for r in rows] +
                            [ci(r, pos_b[r]) for r in rows]
                        ))
                        results.add(cells)
    return results


def find_3digit_size6(grid):
    results = set()

    for band in range(3):
        brows = [band * 3 + i for i in range(3)]
        for r1, r2 in combinations(brows, 2):
            for c1, c2, c3 in combinations(range(9), 3):
                v1 = [grid[r1][c] for c in [c1, c2, c3]]
                v2 = [grid[r2][c] for c in [c1, c2, c3]]
                if len(set(v1)) != 3 or set(v1) != set(v2):
                    continue
                if any(v1[i] == v2[i] for i in range(3)):
                    continue
                cells_list = [ci(r1, c) for c in [c1, c2, c3]] + \
                             [ci(r2, c) for c in [c1, c2, c3]]
                bx_counts = {}
                for idx in cells_list:
                    rr, cc = rc(idx)
                    bx = box_of(rr, cc)
                    bx_counts[bx] = bx_counts.get(bx, 0) + 1
                if any(cnt == 1 for cnt in bx_counts.values()):
                    continue
                results.add(tuple(sorted(cells_list)))

    for stack in range(3):
        scols = [stack * 3 + i for i in range(3)]
        for c1, c2 in combinations(scols, 2):
            for r1, r2, r3 in combinations(range(9), 3):
                v1 = [grid[r][c1] for r in [r1, r2, r3]]
                v2 = [grid[r][c2] for r in [r1, r2, r3]]
                if len(set(v1)) != 3 or set(v1) != set(v2):
                    continue
                if any(v1[i] == v2[i] for i in range(3)):
                    continue
                cells_list = [ci(r, c1) for r in [r1, r2, r3]] + \
                             [ci(r, c2) for r in [r1, r2, r3]]
                bx_counts = {}
                for idx in cells_list:
                    rr, cc = rc(idx)
                    bx = box_of(rr, cc)
                    bx_counts[bx] = bx_counts.get(bx, 0) + 1
                if any(cnt == 1 for cnt in bx_counts.values()):
                    continue
                results.add(tuple(sorted(cells_list)))

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
                ok = True
                for i in range(3):
                    row_vals = set()
                    for j in range(3):
                        if j != perm[i]:
                            row_vals.add(grid[rows_t[i]][cols_t[j]])
                    if row_vals != vals and len(row_vals) != 2:
                        ok = False
                        break
                if not ok:
                    continue
                for j in range(3):
                    col_vals = set()
                    for i in range(3):
                        if j != perm[i]:
                            col_vals.add(grid[rows_t[i]][cols_t[j]])
                    if len(col_vals) < 2:
                        ok = False
                        break
                if not ok:
                    continue
                bx_counts = {}
                for idx in cells_list:
                    rr, cc = rc(idx)
                    bx = box_of(rr, cc)
                    bx_counts[bx] = bx_counts.get(bx, 0) + 1
                if any(cnt == 1 for cnt in bx_counts.values()):
                    continue
                results.add(tuple(sorted(cells_list)))

    return results


def find_larger_multidigit(grid, existing, max_size=12):
    results = set()
    for rows_t in combinations(range(9), 3):
        for cols_t in combinations(range(9), 3):
            cells_list = [ci(rows_t[i], cols_t[j]) for i in range(3) for j in range(3)]
            vals = set(grid[rows_t[i]][cols_t[j]] for i in range(3) for j in range(3))
            if len(vals) != 3:
                continue
            ok = True
            for i in range(3):
                rv = set(grid[rows_t[i]][cols_t[j]] for j in range(3))
                if rv != vals:
                    ok = False
                    break
            if not ok:
                continue
            for j in range(3):
                cv = set(grid[rows_t[i]][cols_t[j]] for i in range(3))
                if cv != vals:
                    ok = False
                    break
            if not ok:
                continue
            bx_counts = {}
            for idx in cells_list:
                rr, cc = rc(idx)
                bx = box_of(rr, cc)
                bx_counts[bx] = bx_counts.get(bx, 0) + 1
            if any(cnt == 1 for cnt in bx_counts.values()):
                continue
            cells = tuple(sorted(cells_list))
            has_smaller = any(set(e) < set(cells) for e in existing)
            if not has_smaller and is_unavoidable(grid, list(cells)):
                results.add(cells)
    return results


def find_all_unavoidable_sets(grid, max_size=12):
    print("Finding 2-digit unavoidable sets...", flush=True)
    two_digit = find_2digit_sets(grid, max_size)
    print(f"  Found {len(two_digit)} candidates", flush=True)

    print("Finding 3-digit size-6 sets...", flush=True)
    three_digit_6 = find_3digit_size6(grid)
    print(f"  Found {len(three_digit_6)} candidates", flush=True)

    all_cands = two_digit | three_digit_6

    print("Finding larger multi-digit sets...", flush=True)
    larger = find_larger_multidigit(grid, all_cands, max_size)
    print(f"  Found {len(larger)} candidates", flush=True)
    all_cands |= larger

    all_sorted = sorted(all_cands, key=len)

    print(f"Verifying {len(all_sorted)} candidates...", flush=True)
    minimal = []
    minimal_sets = []
    for s in all_sorted:
        if len(s) > max_size:
            continue
        s_set = set(s)
        if any(ms <= s_set for ms in minimal_sets):
            continue
        if not is_unavoidable(grid, list(s)):
            continue
        is_min = True
        for i in range(len(s)):
            subset = list(s[:i]) + list(s[i + 1:])
            if is_unavoidable(grid, subset):
                is_min = False
                break
        if is_min:
            minimal.append(list(s))
            minimal_sets.append(s_set)

    print(f"  Verified {len(minimal)} minimal sets", flush=True)
    return minimal


def build_adj(sets_list):
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


def update_database(results):
    conn = sqlite3.connect('/app/analysis.db')
    conn.execute(
        "INSERT INTO clique_analysis (grid_id, mcn, max_clique_indices, clique_counts, is_valid) "
        "VALUES (1, ?, ?, ?, 1)",
        (results['mcn'],
         json.dumps(results['max_clique_indices']),
         json.dumps(results['clique_counts']))
    )
    conn.commit()
    conn.close()
    print("Database updated with valid results", flush=True)


def main():
    grid = parse_grid('/app/grid.txt')
    unavoidable_sets = find_all_unavoidable_sets(grid, max_size=12)
    n = len(unavoidable_sets)
    print(f"\nTotal: {n} minimal unavoidable sets", flush=True)

    print("Building disjointness graph...", flush=True)
    adj = build_adj(unavoidable_sets)

    print("Finding maximum clique...", flush=True)
    mc = max_clique_bk(adj, n)
    mcn = len(mc)
    print(f"MCN = {mcn}", flush=True)

    clique_counts = {}
    for size in range(2, 6):
        print(f"Counting cliques of size {size}...", flush=True)
        cnt = count_cliques(adj, n, size)
        clique_counts[str(size)] = cnt
        print(f"  Size {size}: {cnt}", flush=True)

    results = {
        "unavoidable_sets": unavoidable_sets,
        "total_count": n,
        "mcn": mcn,
        "max_clique_indices": sorted(mc),
        "clique_counts": clique_counts,
    }
    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("Results written to /app/results.json", flush=True)

    update_database(results)


if __name__ == '__main__':
    main()
