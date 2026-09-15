#!/usr/bin/env python3
"""
Reference solver for Oil Field Detection.
Uses a compiled C shared library (libscoring.so) for Gaussian log-likelihood
scoring in the beam search phase.

Strategy:
1. Multi-round row/column aggregate queries for noise-reduced marginal estimates
2. Heat-guided strategic drilling for zero-cell and positive-cell constraints
3. Beam search with drill constraint pruning, scored by C library
4. Targeted disambiguation drilling and iterative refinement
5. Answer guessing with greedy fallback
"""
import sys
import math
import ctypes
import os

# ---------- Load C scoring library ----------
_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libscoring.so")
_scoring_lib = ctypes.CDLL(_lib_path)

_scoring_lib.score_combo.restype = ctypes.c_double
_scoring_lib.score_combo.argtypes = [
    ctypes.c_int, ctypes.c_double, ctypes.c_int,
    ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
]

_scoring_lib.find_best_combo.restype = ctypes.c_int
_scoring_lib.find_best_combo.argtypes = [
    ctypes.c_int, ctypes.c_double, ctypes.c_int,
    ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
    ctypes.c_int,
]


# ---------- I/O helpers ----------

def flush_print(s):
    sys.stdout.write(s + "\n")
    sys.stdout.flush()


def read_problem():
    parts = input().split()
    N, M = int(parts[0]), int(parts[1])
    eps = float(parts[2])
    polys = []
    for _ in range(M):
        size = int(input().strip())
        cells = []
        for _ in range(size):
            row = input().split()
            cells.append((int(row[0]), int(row[1])))
        polys.append(cells)
    return N, M, eps, polys


def do_drill(i, j):
    flush_print(f"d {i} {j}")
    return int(input().strip())


def aggregate_query(cells):
    k = len(cells)
    parts = ["q", str(k)]
    for ci, cj in cells:
        parts.extend([str(ci), str(cj)])
    flush_print(" ".join(parts))
    return int(input().strip())


def do_answer(cells_set):
    cells = sorted(cells_set)
    k = len(cells)
    if k == 0:
        flush_print("a 0")
    else:
        parts = ["a", str(k)]
        for ci, cj in cells:
            parts.extend([str(ci), str(cj)])
        flush_print(" ".join(parts))
    return int(input().strip())


# ---------- C-backed scoring ----------

def _make_scorer(N, eps, num_rounds, row_avg, col_avg):
    """Create a closure that calls the C scoring library."""
    _ra = (ctypes.c_double * N)(*row_avg)
    _ca = (ctypes.c_double * N)(*col_avg)
    _cr = (ctypes.c_int * N)()
    _cc = (ctypes.c_int * N)()

    def score_combo(combo_rc, combo_cc):
        for i in range(N):
            _cr[i] = combo_rc[i]
            _cc[i] = combo_cc[i]
        return _scoring_lib.score_combo(N, eps, num_rounds, _ra, _ca, _cr, _cc)

    return score_combo


# ---------- Main solver ----------

def solve():
    N, M, eps, polys = read_problem()

    # ---- Phase 1: Adaptive multi-round row/column queries ----
    if N <= 8 and eps <= 0.12:
        num_rounds = 2
    elif eps >= 0.18:
        num_rounds = 5
    elif N >= 12:
        num_rounds = 4
    else:
        num_rounds = 3

    row_sums = [0.0] * N
    col_sums = [0.0] * N
    for _ in range(num_rounds):
        for i in range(N):
            row_sums[i] += aggregate_query([(i, j) for j in range(N)])
        for j in range(N):
            col_sums[j] += aggregate_query([(i, j) for i in range(N)])

    row_avg = [s / num_rounds for s in row_sums]
    col_avg = [s / num_rounds for s in col_sums]

    c_val = 1.0 - 2.0 * eps
    if abs(c_val) < 0.01:
        c_val = 0.01

    # Create C-backed scorer
    score_combo = _make_scorer(N, eps, num_rounds, row_avg, col_avg)

    est_row = [max(0.0, (r - N * eps) / c_val) for r in row_avg]
    est_col = [max(0.0, (v - N * eps) / c_val) for v in col_avg]

    # ---- Phase 2: Heat-guided strategic drilling ----
    query_cost = 2.0 * num_rounds * math.sqrt(N)
    total_drill_budget = max(5, int(0.42 * N * N - query_cost - 4))

    drill_frac = 0.12 if M >= 5 else 0.10
    initial_drill_count = max(3, min(int(drill_frac * N * N), total_drill_budget * 2 // 3))

    heat_list = []
    for i in range(N):
        for j in range(N):
            heat_list.append((est_row[i] * est_col[j], i, j))
    heat_list.sort(key=lambda x: -x[0])

    drilled = {}
    for _, ci, cj in heat_list[:initial_drill_count]:
        drilled[(ci, cj)] = do_drill(ci, cj)

    # ---- Phase 3: Enumerate placements with zero-cell filtering ----
    zero_cells = frozenset((ci, cj) for (ci, cj), v in drilled.items() if v == 0)
    pos_drills = {(ci, cj): v for (ci, cj), v in drilled.items() if v > 0}

    all_pl = []
    for k in range(M):
        pls = []
        for r in range(N):
            for cp in range(N):
                cells = []
                ok = True
                for di, dj in polys[k]:
                    ni, nj = r + di, cp + dj
                    if 0 <= ni < N and 0 <= nj < N:
                        cells.append((ni, nj))
                    else:
                        ok = False
                        break
                if not ok:
                    continue
                cs = frozenset(cells)
                if not cs.isdisjoint(zero_cells):
                    continue
                rc = [0] * N
                cc = [0] * N
                for ci, cj in cells:
                    rc[ci] += 1
                    cc[cj] += 1
                pls.append((cs, tuple(rc), tuple(cc)))
        all_pl.append(pls)

    if any(len(p) == 0 for p in all_pl):
        _fallback_drill_remaining(N, drilled)
        return

    # Precompute which positive drill cells each placement covers
    drill_in_pl = []
    for k in range(M):
        dip_k = []
        for idx, (cells, rc, cc) in enumerate(all_pl[k]):
            overlap = []
            for c in cells:
                if c in pos_drills:
                    overlap.append(c)
            dip_k.append(overlap)
        drill_in_pl.append(dip_k)

    # ---- Phase 4: Beam search with drill constraint pruning ----
    beam_w = 500 if M >= 5 else 300
    order = sorted(range(M), key=lambda k: len(all_pl[k]))

    # Initialize beam with first poly (fewest placements)
    k0 = order[0]
    beam = []
    for idx in range(len(all_pl[k0])):
        _, rc, cc = all_pl[k0][idx]
        asgn = [0] * M
        asgn[k0] = idx
        s = score_combo(list(rc), list(cc))
        dp = {}
        for c in drill_in_pl[k0][idx]:
            dp[c] = dp.get(c, 0) + 1
        beam.append((s, list(rc), list(cc), tuple(asgn), dp))
    beam.sort(key=lambda x: -x[0])
    beam = beam[:beam_w]

    # Extend beam one polyomino at a time
    for level in range(1, M):
        k = order[level]
        is_last = (level == M - 1)
        new_beam = []
        for _, rc_prev, cc_prev, asgn_prev, dp_prev in beam:
            for pidx in range(len(all_pl[k])):
                overlap = drill_in_pl[k][pidx]

                ok = True
                new_dp = dict(dp_prev)
                for c in overlap:
                    new_dp[c] = new_dp.get(c, 0) + 1
                    if new_dp[c] > pos_drills[c]:
                        ok = False
                        break
                if not ok:
                    continue

                if is_last:
                    for c, v in pos_drills.items():
                        if new_dp.get(c, 0) != v:
                            ok = False
                            break
                    if not ok:
                        continue

                _, rc_k, cc_k = all_pl[k][pidx]
                new_rc = [rc_prev[i] + rc_k[i] for i in range(N)]
                new_cc = [cc_prev[j] + cc_k[j] for j in range(N)]
                s = score_combo(new_rc, new_cc)
                new_asgn = list(asgn_prev)
                new_asgn[k] = pidx
                new_beam.append((s, new_rc, new_cc, tuple(new_asgn), new_dp))
        new_beam.sort(key=lambda x: -x[0])
        beam = new_beam[:beam_w]

    if not beam:
        beam = _beam_search_no_constraints(N, M, eps, all_pl, row_avg, col_avg,
                                            c_val, beam_w, order, num_rounds)
        if not beam:
            _fallback_drill_remaining(N, drilled)
            return

    # ---- Phase 5: Drill disagreement cells ----
    top_n = min(20, len(beam))
    combo_oils = []
    for s, rc, cc, asgn, dp in beam[:top_n]:
        oil = set()
        for k in range(M):
            oil.update(all_pl[k][asgn[k]][0])
        combo_oils.append(oil)

    all_cand_cells = set()
    for oil in combo_oils:
        all_cand_cells.update(oil)

    disagree = []
    for cell in sorted(all_cand_cells):
        if cell in drilled:
            continue
        cnt = sum(1 for oil in combo_oils if cell in oil)
        if 0 < cnt < top_n:
            info = min(cnt, top_n - cnt)
            disagree.append((-info, cell))
    disagree.sort()
    disagree = [cell for _, cell in disagree]

    remaining_budget = total_drill_budget - len(drilled)
    n_extra = min(len(disagree), max(0, remaining_budget))
    for ci, cj in disagree[:n_extra]:
        drilled[(ci, cj)] = do_drill(ci, cj)

    # Re-filter with all drill data
    def matches_all_drills(asgn):
        for (ci, cj), v in drilled.items():
            pred = 0
            for k in range(M):
                if (ci, cj) in all_pl[k][asgn[k]][0]:
                    pred += 1
            if pred != v:
                return False
        return True

    valid = [(s, rc, cc, a) for s, rc, cc, a, dp in beam if matches_all_drills(a)]
    if not valid:
        valid = [(s, rc, cc, a) for s, rc, cc, a, dp in beam]

    # ---- Phase 6: Guess top candidates ----
    tried = set()
    for s, rc, cc, asgn in valid[:30]:
        oil = frozenset()
        for k in range(M):
            oil = oil | all_pl[k][asgn[k]][0]
        if oil in tried:
            continue
        tried.add(oil)
        result = do_answer(set(oil))
        if result == 1:
            return
        if len(tried) >= 4:
            break

    # ---- Phase 7: Greedy fallback ----
    sigma_sq = max(N * eps * (1.0 - eps) / num_rounds, 1e-12)
    greedy_result = _greedy_solve(N, M, eps, all_pl, row_avg, col_avg,
                                   c_val, sigma_sq, drilled, pos_drills)
    if greedy_result is not None:
        for combo_oil in greedy_result:
            if frozenset(combo_oil) not in tried:
                tried.add(frozenset(combo_oil))
                result = do_answer(combo_oil)
                if result == 1:
                    return

    # ---- Phase 8: Extended drilling fallback ----
    extended_limit = int(0.45 * N * N)
    for _, ci, cj in heat_list:
        if len(drilled) >= extended_limit:
            break
        if (ci, cj) not in drilled:
            drilled[(ci, cj)] = do_drill(ci, cj)

    oil = {(ci, cj) for (ci, cj), v in drilled.items() if v > 0}
    result = do_answer(oil)
    if result == 1:
        return

    for ci, cj in list(oil):
        for di in range(-1, 2):
            for dj in range(-1, 2):
                ni, nj = ci + di, cj + dj
                if 0 <= ni < N and 0 <= nj < N and (ni, nj) not in drilled:
                    drilled[(ni, nj)] = do_drill(ni, nj)

    oil = {(ci, cj) for (ci, cj), v in drilled.items() if v > 0}
    result = do_answer(oil)
    if result == 1:
        return

    # ---- Phase 9: Final fallback ----
    _fallback_drill_remaining(N, drilled)


def _beam_search_no_constraints(N, M, eps, all_pl, row_avg, col_avg,
                                  c_val, beam_w, order, num_rounds):
    """Beam search without drill constraints (fallback)."""
    score_combo = _make_scorer(N, eps, num_rounds, row_avg, col_avg)

    k0 = order[0]
    beam = []
    for idx in range(len(all_pl[k0])):
        _, rc, cc = all_pl[k0][idx]
        asgn = [0] * M
        asgn[k0] = idx
        s = score_combo(list(rc), list(cc))
        beam.append((s, list(rc), list(cc), tuple(asgn), {}))
    beam.sort(key=lambda x: -x[0])
    beam = beam[:beam_w]

    for level in range(1, M):
        k = order[level]
        new_beam = []
        for _, rc_prev, cc_prev, asgn_prev, _ in beam:
            for pidx in range(len(all_pl[k])):
                _, rc_k, cc_k = all_pl[k][pidx]
                new_rc = [rc_prev[i] + rc_k[i] for i in range(N)]
                new_cc = [cc_prev[j] + cc_k[j] for j in range(N)]
                s = score_combo(new_rc, new_cc)
                new_asgn = list(asgn_prev)
                new_asgn[k] = pidx
                new_beam.append((s, new_rc, new_cc, tuple(new_asgn), {}))
        new_beam.sort(key=lambda x: -x[0])
        beam = new_beam[:beam_w]

    return beam


def _greedy_solve(N, M, eps, all_pl, row_avg, col_avg, c_val, sigma_sq,
                   drilled, pos_drills):
    """Greedy coordinate-descent approach: place one poly at a time.
    Uses Python scoring (not C) since it operates on changing residuals."""
    results = []

    for start_k in range(M):
        remaining_row = list(row_avg)
        remaining_col = list(col_avg)
        assignment = [-1] * M
        placed_drill_pred = {}

        poly_order = [start_k] + [k for k in range(M) if k != start_k]

        valid = True
        for k in poly_order:
            best_s = float('-inf')
            best_idx = -1

            for idx, (cells, rc, cc) in enumerate(all_pl[k]):
                ok = True
                for c in cells:
                    if c in pos_drills:
                        pred = placed_drill_pred.get(c, 0) + 1
                        if pred > pos_drills[c]:
                            ok = False
                            break
                if not ok:
                    continue

                s = 0.0
                for i in range(N):
                    if rc[i] > 0:
                        mu = N * eps + rc[i] * c_val
                        d = remaining_row[i] - mu
                        s -= d * d
                for j in range(N):
                    if cc[j] > 0:
                        mu = N * eps + cc[j] * c_val
                        d = remaining_col[j] - mu
                        s -= d * d
                s /= (2.0 * sigma_sq)

                if s > best_s:
                    best_s = s
                    best_idx = idx

            if best_idx < 0:
                valid = False
                break

            assignment[k] = best_idx
            _, rc_best, cc_best = all_pl[k][best_idx]

            for c in all_pl[k][best_idx][0]:
                if c in pos_drills:
                    placed_drill_pred[c] = placed_drill_pred.get(c, 0) + 1

            for i in range(N):
                remaining_row[i] -= rc_best[i] * c_val
            for j in range(N):
                remaining_col[j] -= cc_best[j] * c_val

        if not valid:
            continue

        oil = set()
        for k in range(M):
            oil.update(all_pl[k][assignment[k]][0])
        results.append(oil)

    return results if results else None


def _fallback_drill_remaining(N, drilled):
    for i in range(N):
        for j in range(N):
            if (i, j) not in drilled:
                drilled[(i, j)] = do_drill(i, j)
    oil = {(ci, cj) for (ci, cj), v in drilled.items() if v > 0}
    do_answer(oil)


if __name__ == "__main__":
    solve()
