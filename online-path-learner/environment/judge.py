#!/usr/bin/env python3
"""
Judge for the Online Shortest Path problem.

Usage: python3 judge.py <seed> <solver_command...>

Generates a 30x30 grid instance from the given seed, runs the solver
interactively via stdin/stdout, and prints the final score to stdout.
Errors go to stderr.
"""

import sys
import subprocess
import random
import heapq


def dijkstra_dist(h, v, si, sj, ti, tj):
    """Compute shortest path distance from (si,sj) to (ti,tj)."""
    COLS = 30
    N = 900
    src = si * COLS + sj
    dst = ti * COLS + tj

    dist = [float('inf')] * N
    dist[src] = 0
    pq = [(0, src)]

    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        if u == dst:
            break
        ui, uj = u // COLS, u % COLS

        neighbors = []
        if uj < 29:
            neighbors.append((u + 1, h[ui][uj]))
        if uj > 0:
            neighbors.append((u - 1, h[ui][uj - 1]))
        if ui < 29:
            neighbors.append((u + COLS, v[ui][uj]))
        if ui > 0:
            neighbors.append((u - COLS, v[ui - 1][uj]))

        for nxt, w in neighbors:
            nd = d + w
            if nd < dist[nxt]:
                dist[nxt] = nd
                heapq.heappush(pq, (nd, nxt))

    return dist[dst]


def generate_instance(seed):
    """Generate a grid instance following the AHC003 specification."""
    rng = random.Random(seed)

    D = rng.randint(100, 2000)
    M = rng.randint(1, 2)

    # Horizontal edges: h[i][j] = weight of edge between (i,j) and (i,j+1)
    h = [[0] * 29 for _ in range(30)]
    for i in range(30):
        H_vals = [rng.randint(1000 + D, 9000 - D) for _ in range(M)]
        if M == 1:
            for j in range(29):
                delta = rng.randint(-D, D)
                h[i][j] = H_vals[0] + delta
        else:
            x = rng.randint(1, 28)
            for j in range(29):
                delta = rng.randint(-D, D)
                h[i][j] = H_vals[0 if j < x else 1] + delta

    # Vertical edges: v[i][j] = weight of edge between (i,j) and (i+1,j)
    v = [[0] * 30 for _ in range(29)]
    for j_col in range(30):
        V_vals = [rng.randint(1000 + D, 9000 - D) for _ in range(M)]
        if M == 1:
            for i in range(29):
                gamma = rng.randint(-D, D)
                v[i][j_col] = V_vals[0] + gamma
        else:
            y = rng.randint(1, 28)
            for i in range(29):
                gamma = rng.randint(-D, D)
                v[i][j_col] = V_vals[0 if i < y else 1] + gamma

    # Generate 1000 queries with precomputed shortest path lengths
    queries = []
    for _ in range(1000):
        while True:
            si = rng.randint(0, 29)
            sj = rng.randint(0, 29)
            ti = rng.randint(0, 29)
            tj = rng.randint(0, 29)
            if abs(si - ti) + abs(sj - tj) >= 10:
                break

        a = dijkstra_dist(h, v, si, sj, ti, tj)
        e = rng.uniform(0.9, 1.1)
        queries.append((si, sj, ti, tj, int(a), e))

    return h, v, queries, D, M


def compute_path_length(h, v, path_str, si, sj, ti, tj):
    """Validate path and compute its total edge weight.
    Returns (length, True) on success, (-1, False) on invalid path."""
    ci, cj = si, sj
    total = 0

    for ch in path_str:
        if ch == 'U':
            if ci <= 0:
                return -1, False
            ci -= 1
            total += v[ci][cj]
        elif ch == 'D':
            if ci >= 29:
                return -1, False
            total += v[ci][cj]
            ci += 1
        elif ch == 'L':
            if cj <= 0:
                return -1, False
            cj -= 1
            total += h[ci][cj]
        elif ch == 'R':
            if cj >= 29:
                return -1, False
            total += h[ci][cj]
            cj += 1
        else:
            return -1, False

    if (ci, cj) != (ti, tj):
        return -1, False

    return total, True


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 judge.py <seed> <solver_command...>", file=sys.stderr)
        sys.exit(1)

    seed = int(sys.argv[1])
    solver_cmd = sys.argv[2:]

    h, v, queries, D, M = generate_instance(seed)

    proc = subprocess.Popen(
        solver_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    score = 0.0

    try:
        for k, (si, sj, ti, tj, a, e) in enumerate(queries):
            # Send query to solver
            proc.stdin.write(f'{si} {sj} {ti} {tj}\n')
            proc.stdin.flush()

            # Read path from solver
            path_line = proc.stdout.readline()
            if not path_line:
                print(f"ERROR: Solver produced no output at query {k}", file=sys.stderr)
                proc.kill()
                print(0)
                return

            path_str = path_line.strip()
            b, valid = compute_path_length(h, v, path_str, si, sj, ti, tj)

            if not valid:
                print(f"ERROR: Invalid path at query {k}: "
                      f"from ({si},{sj}) to ({ti},{tj}), path='{path_str[:50]}...'",
                      file=sys.stderr)
                proc.kill()
                print(0)
                return

            # Compute noisy feedback
            feedback = round(b * e)

            # Send feedback to solver
            proc.stdin.write(f'{feedback}\n')
            proc.stdin.flush()

            # Accumulate score with exponential discount
            score = score * 0.998 + a / b

        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    except BrokenPipeError:
        print("ERROR: Solver process terminated unexpectedly", file=sys.stderr)
        try:
            proc.kill()
        except Exception:
            pass
        print(0)
        return
    except Exception as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        try:
            proc.kill()
        except Exception:
            pass
        print(0)
        return

    final_score = round(2312311 * score)
    print(final_score)


if __name__ == '__main__':
    main()
