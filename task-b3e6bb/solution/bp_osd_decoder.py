"""BP+OSD decoder for quantum LDPC codes.


Implements min-sum belief propagation with OSD-0 (Ordered Statistics
Decoding, order 0) post-processing.  BP provides soft reliability
information via iterative message passing on the Tanner graph.  When BP
fails to converge or produces a suboptimal solution, OSD-0 uses either
BP soft output or syndrome-weight heuristics to find a low-weight
correction.

Key insight for quantum codes: short cycles in the Tanner graph cause
standard BP to converge to high-weight degenerate solutions.  A
syndrome-weight-based column ordering for OSD avoids this pathology by
directly prioritizing variables involved in unsatisfied checks.
"""

import numpy as np


class Decoder:
    """Min-sum BP + OSD-0 syndrome decoder with syndrome-weight fallback."""

    def __init__(self, pcm: np.ndarray, error_rate: float, max_iter: int = 50):
        self.H = pcm.astype(int) % 2
        self.m, self.n = self.H.shape
        self.max_iter = max_iter

        # Channel log-likelihood ratio
        p = max(min(float(error_rate), 1 - 1e-15), 1e-15)
        self.channel_llr = np.log((1 - p) / p)

        # Min-sum normalization factor
        self.ms_scale = 0.625

        # Build Tanner graph edge lists
        self.edges = []
        self.check_adj = [[] for _ in range(self.m)]
        self.var_adj = [[] for _ in range(self.n)]

        for i in range(self.m):
            for j in range(self.n):
                if self.H[i, j]:
                    eidx = len(self.edges)
                    self.edges.append((i, j))
                    self.check_adj[i].append((eidx, j))
                    self.var_adj[j].append((eidx, i))

        self.num_edges = len(self.edges)

        # Pre-compute weight-1 syndrome lookup table:
        # Maps syndrome (as tuple) -> column index for O(1) single-error decoding
        self._wt1_lookup = {}
        for j in range(self.n):
            col = tuple(self.H[:, j].tolist())
            if col not in self._wt1_lookup and any(self.H[:, j]):
                self._wt1_lookup[col] = j

    def decode(self, syndrome: np.ndarray) -> np.ndarray:
        syndrome = np.asarray(syndrome, dtype=int) % 2

        if not np.any(syndrome):
            return np.zeros(self.n, dtype=int)

        # --- Strategy 0: Weight-1 lookup (handles single-qubit errors) ---
        syn_key = tuple(syndrome.tolist())
        if syn_key in self._wt1_lookup:
            c = np.zeros(self.n, dtype=int)
            c[self._wt1_lookup[syn_key]] = 1
            return c

        # --- Strategy 1: BP ---
        soft, hard, converged = self._bp(syndrome)

        candidates = []
        if converged:
            candidates.append(hard)

        # --- Strategy 2: OSD-0 with BP soft output ---
        candidates.append(self._osd0(syndrome, soft))

        # --- Strategy 3: OSD-0 with syndrome-weight ordering ---
        # Variables in many unsatisfied checks get low |soft| -> pivoted first
        syn_weight = (self.H.T @ syndrome).astype(float)
        max_sw = max(syn_weight.max(), 1.0)
        sw_soft = (max_sw + 1.0 - syn_weight) * self.channel_llr
        sw_soft += np.arange(self.n, dtype=float) * 1e-10  # tiebreaker
        candidates.append(self._osd0(syndrome, sw_soft))

        # Return lowest-weight valid correction
        return min(candidates, key=lambda c: int(c.sum()))

    # ------------------------------------------------------------------ #
    #  Min-sum Belief Propagation                                          #
    # ------------------------------------------------------------------ #

    def _bp(self, syndrome):
        """Run min-sum BP.  Returns (soft_output, hard_decision, converged)."""
        c2v = np.zeros(self.num_edges)
        v2c = np.full(self.num_edges, self.channel_llr)

        soft = np.full(self.n, self.channel_llr)
        hard = np.zeros(self.n, dtype=int)

        for _it in range(self.max_iter):
            # Check-to-variable update
            for i in range(self.m):
                adj = self.check_adj[i]
                n_adj = len(adj)
                if n_adj == 0:
                    continue
                for k in range(n_adj):
                    eidx = adj[k][0]
                    sign = 1 - 2 * syndrome[i]
                    min_abs = 1e15
                    for k2 in range(n_adj):
                        if k2 == k:
                            continue
                        msg = v2c[adj[k2][0]]
                        if msg < 0:
                            sign = -sign
                        a = abs(msg)
                        if a < min_abs:
                            min_abs = a
                    c2v[eidx] = sign * min_abs * self.ms_scale

            # Variable-to-check update + posterior LLR
            soft[:] = self.channel_llr
            for j in range(self.n):
                for eidx, _i in self.var_adj[j]:
                    soft[j] += c2v[eidx]

            for j in range(self.n):
                for eidx, _i in self.var_adj[j]:
                    v2c[eidx] = soft[j] - c2v[eidx]

            # Hard decision + convergence check
            hard = (soft < 0).astype(int)
            if np.all((self.H @ hard) % 2 == syndrome):
                return soft, hard, True

        return soft, hard, False

    # ------------------------------------------------------------------ #
    #  OSD-0 (Ordered Statistics Decoding, order 0)                        #
    # ------------------------------------------------------------------ #

    def _osd0(self, syndrome, soft):
        """OSD-0: solve H x = s (mod 2) by pivoting on least-reliable
        columns first (smallest |soft|), then setting free columns to 0."""
        order = np.argsort(np.abs(soft))

        H_ord = self.H[:, order].copy()
        s = syndrome.copy()

        # Gaussian elimination (full RREF)
        pivots = []
        row_idx = 0
        for col in range(self.n):
            if row_idx >= self.m:
                break
            piv = -1
            for r in range(row_idx, self.m):
                if H_ord[r, col]:
                    piv = r
                    break
            if piv < 0:
                continue
            if piv != row_idx:
                H_ord[[row_idx, piv]] = H_ord[[piv, row_idx]]
                s[[row_idx, piv]] = s[[piv, row_idx]]
            for r in range(self.m):
                if r != row_idx and H_ord[r, col]:
                    H_ord[r] = (H_ord[r] + H_ord[row_idx]) % 2
                    s[r] = (s[r] + s[row_idx]) % 2
            pivots.append(col)
            row_idx += 1

        # Pivot variables from syndrome, free variables = 0
        x_ord = np.zeros(self.n, dtype=int)
        for i, pc in enumerate(pivots):
            x_ord[pc] = s[i]

        # Map back to original ordering
        correction = np.zeros(self.n, dtype=int)
        for idx, orig in enumerate(order):
            correction[orig] = x_ord[idx]

        return correction % 2
