"""
Noisy Polyomino Localization Simulator.

Provides the Simulator class for the Noisy Polyomino Localization problem.
Generates a hidden NxN grid with M placed polyominoes and exposes two query methods:
  - drill(i, j): exact point query at cell (i,j), cost = 1
  - divine(cells): noisy group query over a set of cells, cost = 1/sqrt(|cells|)

"""

import random
import math

# ---------------------------------------------------------------------------
# Polyomino shape library (relative coordinates, normalised so min row/col = 0)
# ---------------------------------------------------------------------------
_SHAPES = [
    # --- 3-cell ---
    [(0, 0), (0, 1), (1, 0)],
    [(0, 0), (0, 1), (0, 2)],
    [(0, 0), (1, 0), (1, 1)],
    # --- 4-cell ---
    [(0, 0), (0, 1), (0, 2), (0, 3)],
    [(0, 0), (0, 1), (1, 0), (1, 1)],
    [(0, 0), (0, 1), (0, 2), (1, 1)],
    [(0, 0), (1, 0), (1, 1), (2, 1)],
    [(0, 1), (1, 0), (1, 1), (2, 0)],
    [(0, 0), (0, 1), (0, 2), (1, 0)],
    [(0, 0), (0, 1), (0, 2), (1, 2)],
    # --- 5-cell ---
    [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)],
    [(0, 0), (0, 1), (0, 2), (1, 0), (2, 0)],
    [(0, 0), (0, 1), (1, 1), (1, 2), (2, 2)],
    [(0, 0), (1, 0), (1, 1), (1, 2), (2, 2)],
    [(0, 1), (1, 0), (1, 1), (1, 2), (2, 1)],
    # --- 6-cell ---
    [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)],
    [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1)],
]


def _rotate_shape(shape):
    """Rotate 90 degrees clockwise and normalise."""
    rot = [(c, -r) for r, c in shape]
    mr = min(r for r, _ in rot)
    mc = min(c for _, c in rot)
    return sorted((r - mr, c - mc) for r, c in rot)


def _get_rotations(shape):
    """Return all four rotations of *shape*."""
    result = []
    s = list(shape)
    for _ in range(4):
        result.append(sorted(s))
        s = _rotate_shape(s)
    return result


# ---------------------------------------------------------------------------
# Pre-defined test-case parameters
#   (gen_seed, N, M, epsilon, query_seed)
# ---------------------------------------------------------------------------
_CASES = [
    (7919,  20, 4, 0.08, 104729),
    (7927,  20, 5, 0.08, 104743),
    (7933,  20, 5, 0.10, 104759),
    (7937,  20, 4, 0.12, 104767),
    (7949,  20, 6, 0.08, 104773),
]

NUM_CASES = len(_CASES)


class Simulator:
    """Simulator for the Noisy Polyomino Localization problem.

    Public attributes (read-only for the solver):
        N              -- grid dimension  (N x N)
        M              -- number of polyominoes placed
        epsilon        -- noise parameter for divine()
        polyominoes    -- list[list[tuple[int,int]]]
                          shapes of the M polyominoes (relative coords,
                          rotation already applied).  Positions unknown.
        cost           -- cumulative query cost so far
        num_operations -- number of queries made so far
        max_operations -- hard limit on queries  (2 * N * N)

    Public methods:
        drill(i, j)   -> int   exact point query,  cost = 1
        divine(cells) -> int   noisy group query,   cost = 1 / sqrt(|cells|)
    """

    def __init__(self, case_id: int):
        if not (0 <= case_id < NUM_CASES):
            raise ValueError(f"case_id must be in [0, {NUM_CASES - 1}]")
        gen_seed, self.N, self.M, self.epsilon, qseed = _CASES[case_id]

        rng = random.Random(gen_seed)
        self._grid = [[0] * self.N for _ in range(self.N)]
        self.polyominoes = []
        self._positions = []

        placed = 0
        attempts = 0
        while placed < self.M and attempts < 10000:
            attempts += 1
            idx = rng.randint(0, len(_SHAPES) - 1)
            rots = _get_rotations(_SHAPES[idx])
            shape = rots[rng.randint(0, 3)]
            max_r = max(r for r, _ in shape)
            max_c = max(c for _, c in shape)
            if max_r >= self.N or max_c >= self.N:
                continue
            dr = rng.randint(0, self.N - 1 - max_r)
            dc = rng.randint(0, self.N - 1 - max_c)
            for r, c in shape:
                self._grid[r + dr][c + dc] += 1
            self.polyominoes.append(list(shape))
            self._positions.append((dr, dc))
            placed += 1

        self._qrng = random.Random(qseed)
        self.cost = 0.0
        self.num_operations = 0
        self.max_operations = 2 * self.N * self.N

    # ------------------------------------------------------------------ #
    #  Public query API                                                    #
    # ------------------------------------------------------------------ #

    def drill(self, i: int, j: int) -> int:
        """Exact point query. Returns v(i, j). Cost = 1."""
        if not (0 <= i < self.N and 0 <= j < self.N):
            raise ValueError(f"({i},{j}) out of bounds for {self.N}x{self.N} grid")
        if self.num_operations >= self.max_operations:
            raise RuntimeError("Exceeded maximum number of operations")
        self.cost += 1.0
        self.num_operations += 1
        return self._grid[i][j]

    def divine(self, cells) -> int:
        """Noisy group query.

        *cells* must be a sequence of (i, j) with length >= 2.

        Returns  max(0, round(Normal(mu, sigma)))  where
            mu    = (k - v(S)) * eps  +  v(S) * (1 - eps)
            sigma = sqrt(k * eps * (1 - eps))
            k     = len(cells),  v(S) = sum of v(i,j) for (i,j) in cells

        Cost = 1 / sqrt(k).
        """
        cells = list(cells)
        k = len(cells)
        if k < 2:
            raise ValueError("divine() requires at least 2 cells")
        if self.num_operations >= self.max_operations:
            raise RuntimeError("Exceeded maximum number of operations")
        for i, j in cells:
            if not (0 <= i < self.N and 0 <= j < self.N):
                raise ValueError(f"({i},{j}) out of bounds")

        v = sum(self._grid[i][j] for i, j in cells)
        eps = self.epsilon
        mu = (k - v) * eps + v * (1.0 - eps)
        sigma = math.sqrt(k * eps * (1.0 - eps))
        x = self._qrng.gauss(mu, sigma)
        self.cost += 1.0 / math.sqrt(k)
        self.num_operations += 1
        return max(0, round(x))

    # ------------------------------------------------------------------ #
    #  Verification helpers  (NOT for solver use)                          #
    # ------------------------------------------------------------------ #

    def _get_active(self):
        """Return ground-truth set of active cells.  For tests only."""
        return {
            (i, j)
            for i in range(self.N)
            for j in range(self.N)
            if self._grid[i][j] > 0
        }
