#!/usr/bin/env python3
"""
Solver for linear blending reachability.

For each target x in [1, m], find the minimum blending time t in [0, 1]
such that value x appears in the sequence after linearly averaging some
contiguous window of k elements toward its arithmetic mean.

Key insight: at time t, element a_j becomes a_j*(1-t) + mu*t.
Solving for t: t = (x - a_j) / (mu - a_j).

For x > mu, the minimum t comes from the smallest a_j > x (monotonicity).
For x < mu, the minimum t comes from the largest a_j < x.

Algorithm: sort each window, binary-search for the optimal element.
Complexity: O((n-k+1)*k*log(k) + m*(n-k+1)*log(k))
"""
import bisect


def solve():
    with open('/app/input.txt') as f:
        parts = f.readline().split()
        n, m, k = int(parts[0]), int(parts[1]), int(parts[2])
        a = list(map(int, f.readline().split()))

    present = set(a)
    num_w = n - k + 1

    # Precompute: for each window, store sorted elements and integer sum
    window_data = []
    for i in range(num_w):
        w = a[i:i + k]
        s = sum(w)
        sw = sorted(w)
        window_data.append((sw, s, sw[0], sw[-1]))

    results = []
    for x in range(1, m + 1):
        if x in present:
            results.append('0.000000000000')
            continue

        best = float('inf')
        for sw, s, wmin, wmax in window_data:
            # Quick range filter: x must lie within [min, max] of window
            if x < wmin or x > wmax:
                continue

            mu = s / k

            # Exact rational check for x == mu (avoids float comparison):
            # x == sum/k iff k*x == sum
            if k * x == s:
                if 1.0 < best:
                    best = 1.0
                continue

            if x > mu:
                # Need element a_j > x that moves DOWN toward mu, passing x.
                # Smallest such a_j minimizes t = (a_j - x) / (a_j - mu).
                idx = bisect.bisect_right(sw, x)
                if idx < k:
                    aj = sw[idx]
                    t = (aj - x) / (aj - mu)
                    if t < best:
                        best = t
            else:
                # Need element a_j < x that moves UP toward mu, passing x.
                # Largest such a_j minimizes t = (x - a_j) / (mu - a_j).
                idx = bisect.bisect_left(sw, x) - 1
                if idx >= 0:
                    aj = sw[idx]
                    t = (x - aj) / (mu - aj)
                    if t < best:
                        best = t

        if best == float('inf'):
            results.append('-1')
        else:
            results.append(f'{best:.12f}')

    with open('/app/output.txt', 'w') as f:
        f.write('\n'.join(results) + '\n')


if __name__ == '__main__':
    solve()
