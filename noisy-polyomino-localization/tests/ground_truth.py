"""
Ground truth computation for Polyomino Field Oracle.
Reimplements the SplitMix64 RNG and grid generation to compute
the true set of active cells for each case.

"""

import math

MASK64 = (1 << 64) - 1

# ============================================================
# SplitMix64 RNG (matches the C engine exactly)
# ============================================================

class SplitMix64:
    def __init__(self, seed):
        self.state = seed & MASK64

    def next(self):
        self.state = (self.state + 0x9e3779b97f4a7c15) & MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * 0xbf58476d1ce4e5b9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94d049bb133111eb) & MASK64
        return z ^ (z >> 31)

    def randint(self, lo, hi):
        val = self.next()
        return lo + int(val % (hi - lo + 1))

    def uniform(self):
        return ((self.next() >> 11) + 0.5) / (1 << 53)

    def gauss(self, mu, sigma):
        u1 = self.uniform()
        u2 = self.uniform()
        z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        return mu + sigma * z


# ============================================================
# Shape Library (identical to C engine)
# ============================================================

SHAPES = [
    # 3-cell
    [(0,0),(0,1),(1,0)],
    [(0,0),(0,1),(0,2)],
    [(0,0),(1,0),(1,1)],
    # 4-cell
    [(0,0),(0,1),(0,2),(0,3)],
    [(0,0),(0,1),(1,0),(1,1)],
    [(0,0),(0,1),(0,2),(1,1)],
    [(0,0),(1,0),(1,1),(2,1)],
    [(0,1),(1,0),(1,1),(2,0)],
    [(0,0),(0,1),(0,2),(1,0)],
    [(0,0),(0,1),(0,2),(1,2)],
    # 5-cell
    [(0,0),(0,1),(0,2),(0,3),(0,4)],
    [(0,0),(0,1),(0,2),(1,0),(2,0)],
    [(0,0),(0,1),(1,1),(1,2),(2,2)],
    [(0,0),(1,0),(1,1),(1,2),(2,2)],
    [(0,1),(1,0),(1,1),(1,2),(2,1)],
    # 6-cell
    [(0,0),(0,1),(0,2),(1,0),(1,1),(1,2)],
    [(0,0),(0,1),(0,2),(0,3),(1,0),(1,1)],
]

NUM_SHAPES = len(SHAPES)


def _rotate_shape(shape):
    """Rotate 90 degrees clockwise, normalize to origin."""
    rotated = [(c, -r) for r, c in shape]
    min_r = min(r for r, c in rotated)
    min_c = min(c for r, c in rotated)
    return [(r - min_r, c - min_c) for r, c in rotated]


# ============================================================
# Case Parameters (identical to C engine)
# ============================================================

CASES = [
    {"gen_seed": 314159, "N": 20, "M": 4, "epsilon": 0.08, "query_seed": 271828},
    {"gen_seed": 141421, "N": 20, "M": 5, "epsilon": 0.08, "query_seed": 173205},
    {"gen_seed": 223606, "N": 20, "M": 5, "epsilon": 0.10, "query_seed": 244949},
    {"gen_seed": 264575, "N": 20, "M": 4, "epsilon": 0.12, "query_seed": 316227},
    {"gen_seed": 346410, "N": 20, "M": 6, "epsilon": 0.08, "query_seed": 374165},
]

NUM_CASES = len(CASES)


# ============================================================
# Grid Generation (matches C engine init_session exactly)
# ============================================================

def generate_grid(case_id):
    """Generate the N x N grid for the given case.
    Returns (N, M, epsilon, grid) where grid[i][j] is the
    count of polyominoes covering cell (i,j)."""
    cp = CASES[case_id]
    N = cp["N"]
    M = cp["M"]
    epsilon = cp["epsilon"]

    gen = SplitMix64(cp["gen_seed"])
    grid = [[0] * N for _ in range(N)]

    placed = 0
    attempts = 0
    while placed < M and attempts < 10000:
        attempts += 1
        idx = gen.randint(0, NUM_SHAPES - 1)
        rot_count = gen.randint(0, 3)
        shape = list(SHAPES[idx])

        for _ in range(rot_count):
            shape = _rotate_shape(shape)

        max_r = max(r for r, c in shape)
        max_c = max(c for r, c in shape)

        if max_r >= N or max_c >= N:
            continue

        dr = gen.randint(0, N - 1 - max_r)
        dc = gen.randint(0, N - 1 - max_c)

        for r, c in shape:
            grid[r + dr][c + dc] += 1

        placed += 1

    return N, M, epsilon, grid


def compute_active_cells(case_id):
    """Return the set of (row, col) with v(row,col) > 0."""
    N, M, epsilon, grid = generate_grid(case_id)
    return {
        (i, j)
        for i in range(N)
        for j in range(N)
        if grid[i][j] > 0
    }
