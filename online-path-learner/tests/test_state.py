"""
Tests for Online Shortest Path solver.
Uses an independent judge implementation for tamper-proof verification.
"""

import os
import subprocess
import heapq
import pytest

SEEDS = [42, 137, 256]
SCORE_THRESHOLD = 650_000_000

NR, NC = 30, 30
NV = NR * NC
NQ = 1000


class _SM64:
    """SplitMix64 PRNG matching the compiled judge binary."""

    def __init__(self, seed):
        self._s = seed & 0xFFFFFFFFFFFFFFFF

    def _next(self):
        self._s = (self._s + 0x9e3779b97f4a7c15) & 0xFFFFFFFFFFFFFFFF
        z = self._s
        z = ((z ^ (z >> 30)) * 0xbf58476d1ce4e5b9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94d049bb133111eb) & 0xFFFFFFFFFFFFFFFF
        return z ^ (z >> 31)

    def randint(self, lo, hi):
        return lo + int(self._next() % (hi - lo + 1))

    def uniform01(self):
        return (self._next() >> 11) / float(1 << 53)


def _neighbors(ui, uj, hw, vw):
    u = ui * NC + uj
    n = []
    if uj < NC - 1:
        n.append((u + 1, hw[ui][uj]))
    if uj > 0:
        n.append((u - 1, hw[ui][uj - 1]))
    if ui < NR - 1:
        n.append((u + NC, vw[ui][uj]))
    if ui > 0:
        n.append((u - NC, vw[ui - 1][uj]))
    return n


def _dijkstra_dist(hw, vw, si, sj, ti, tj):
    src = si * NC + sj
    dst = ti * NC + tj
    dist = [float('inf')] * NV
    dist[src] = 0
    pq = [(0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        if u == dst:
            break
        ui, uj = u // NC, u % NC
        for nxt, w in _neighbors(ui, uj, hw, vw):
            nd = d + w
            if nd < dist[nxt]:
                dist[nxt] = nd
                heapq.heappush(pq, (nd, nxt))
    return dist[dst]


def _generate(seed):
    r = _SM64(seed)
    D = r.randint(100, 2000)
    M = r.randint(1, 2)

    hw = [[0] * (NC - 1) for _ in range(NR)]
    for i in range(NR):
        bases = [r.randint(1000 + D, 9000 - D) for _ in range(M)]
        if M == 1:
            for j in range(NC - 1):
                hw[i][j] = bases[0] + r.randint(-D, D)
        else:
            x = r.randint(1, 28)
            for j in range(NC - 1):
                hw[i][j] = bases[0 if j < x else 1] + r.randint(-D, D)

    vw = [[0] * NC for _ in range(NR - 1)]
    for j in range(NC):
        bases = [r.randint(1000 + D, 9000 - D) for _ in range(M)]
        if M == 1:
            for i in range(NR - 1):
                vw[i][j] = bases[0] + r.randint(-D, D)
        else:
            y = r.randint(1, 28)
            for i in range(NR - 1):
                vw[i][j] = bases[0 if i < y else 1] + r.randint(-D, D)

    queries = []
    for _ in range(NQ):
        while True:
            si, sj = r.randint(0, 29), r.randint(0, 29)
            ti, tj = r.randint(0, 29), r.randint(0, 29)
            if abs(si - ti) + abs(sj - tj) >= 10:
                break
        a = _dijkstra_dist(hw, vw, si, sj, ti, tj)
        e = 0.9 + 0.2 * r.uniform01()
        queries.append((si, sj, ti, tj, a, e))

    return hw, vw, queries


def _path_cost(hw, vw, path, si, sj, ti, tj):
    ci, cj = si, sj
    total = 0
    for ch in path:
        if ch == 'U':
            if ci <= 0:
                return -1
            ci -= 1
            total += vw[ci][cj]
        elif ch == 'D':
            if ci >= NR - 1:
                return -1
            total += vw[ci][cj]
            ci += 1
        elif ch == 'L':
            if cj <= 0:
                return -1
            cj -= 1
            total += hw[ci][cj]
        elif ch == 'R':
            if cj >= NC - 1:
                return -1
            total += hw[ci][cj]
            cj += 1
        else:
            return -1
    if (ci, cj) != (ti, tj):
        return -1
    return total


def _run_judge(seed, solver_cmd):
    """Run an independent judge against the solver, return score."""
    hw, vw, queries = _generate(seed)

    proc = subprocess.Popen(
        solver_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    score = 0.0
    try:
        for k, (si, sj, ti, tj, a, e) in enumerate(queries):
            proc.stdin.write(f'{si} {sj} {ti} {tj}\n')
            proc.stdin.flush()

            line = proc.stdout.readline()
            if not line:
                proc.kill()
                return 0

            path = line.strip()
            b = _path_cost(hw, vw, path, si, sj, ti, tj)
            if b <= 0:
                proc.kill()
                return 0

            fb = int(b * e + 0.5)
            proc.stdin.write(f'{fb}\n')
            proc.stdin.flush()

            score = score * 0.998 + a / b

        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    except BrokenPipeError:
        try:
            proc.kill()
        except Exception:
            pass
        return 0
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        return 0

    return int(2312311.0 * score + 0.5)


def test_solver_exists():
    """Solver file must exist at /app/solver."""
    assert os.path.exists('/app/solver'), \
        "Solver not found at /app/solver"


def test_solver_executable():
    """Solver must be executable."""
    assert os.access('/app/solver', os.X_OK), \
        "/app/solver is not executable (chmod +x /app/solver)"


def test_solver_scores():
    """Run solver against independent judge on all seeds, check average."""
    scores = []
    for seed in SEEDS:
        s = _run_judge(seed, ['/app/solver'])
        assert s > 0, (
            f"Score is 0 for seed {seed}. "
            f"Solver likely produced invalid paths or crashed."
        )
        scores.append(s)

    avg = sum(scores) / len(scores)
    assert avg >= SCORE_THRESHOLD, (
        f"Average score {avg:.0f} < {SCORE_THRESHOLD}. "
        f"Per-seed scores: {dict(zip(SEEDS, scores))}"
    )
