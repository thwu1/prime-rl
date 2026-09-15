import numpy as np


class DynamicOptimizer:
    """Multi-swarm Particle Swarm Optimization for dynamic environments.

    Features:
    - Multiple sub-swarms with independent personal/global bests
    - Constriction-coefficient velocity update
    - Change response: reset bests, re-initialise a fraction of swarms
    - Exclusion: re-initialise swarms whose leaders converge to the same peak
    - Anti-convergence: re-randomise swarms whose spread collapses
    """

    def __init__(self, benchmark, seed=0):
        self.b = benchmark
        self.dim = benchmark.dim
        self.rng = np.random.default_rng(seed)
        self.lo, self.hi = -100.0, 100.0

        # --- adaptive sizing ---
        budget = benchmark.change_frequency
        raw_swarms = min(benchmark.num_peaks, 10)
        self.num_swarms = max(3, raw_swarms)
        target_gens = 20
        evals_per_gen = max(1, budget // target_gens)
        sw = max(3, evals_per_gen // self.num_swarms)
        self.swarm_size = min(sw, 20)

        # PSO constriction coefficients
        self.w = 0.729
        self.c1 = 1.49445
        self.c2 = 1.49445

        # Exclusion radius — scales with search volume and number of swarms
        vol = (self.hi - self.lo) ** self.dim
        self.exclusion_radius = (
            (vol / self.num_swarms) ** (1.0 / self.dim) * 0.25
        )

        # Anti-convergence threshold
        self.convergence_threshold = 1e-3

    # ------------------------------------------------------------------ run
    def run(self):
        self._init_swarms()

        # Initial evaluation
        for s in range(self.num_swarms):
            for i in range(self.swarm_size):
                if self.b.has_terminated():
                    return {"offline_error": self.b.get_offline_error()}
                val = self.b.evaluate(self.pos[s][i])
                self._update_best(s, i, val)
                if self.b.has_changed():
                    self._handle_change()

        # Main loop
        while not self.b.has_terminated():
            for s in range(self.num_swarms):
                for i in range(self.swarm_size):
                    if self.b.has_terminated():
                        return {"offline_error": self.b.get_offline_error()}

                    r1 = self.rng.random(self.dim)
                    r2 = self.rng.random(self.dim)
                    self.vel[s][i] = (
                        self.w * self.vel[s][i]
                        + self.c1 * r1 * (self.pb_pos[s][i] - self.pos[s][i])
                        + self.c2 * r2 * (self.gb_pos[s] - self.pos[s][i])
                    )
                    self.pos[s][i] = np.clip(
                        self.pos[s][i] + self.vel[s][i], self.lo, self.hi
                    )
                    val = self.b.evaluate(self.pos[s][i])
                    self._update_best(s, i, val)

                    if self.b.has_changed():
                        self._handle_change()

            self._exclusion()
            self._anti_convergence()

        return {"offline_error": self.b.get_offline_error()}

    # --------------------------------------------------------- initialisation
    def _init_swarms(self):
        ns, ss, d = self.num_swarms, self.swarm_size, self.dim
        self.pos = [self.rng.uniform(self.lo, self.hi, (ss, d))
                    for _ in range(ns)]
        self.vel = [self.rng.uniform(-10, 10, (ss, d))
                    for _ in range(ns)]
        self.pb_pos = [p.copy() for p in self.pos]
        self.pb_val = [np.full(ss, -np.inf) for _ in range(ns)]
        self.gb_pos = [self.pos[s][0].copy() for s in range(ns)]
        self.gb_val = np.full(ns, -np.inf)

    # ----------------------------------------------------- personal/global best
    def _update_best(self, s, i, val):
        if val > self.pb_val[s][i]:
            self.pb_val[s][i] = val
            self.pb_pos[s][i] = self.pos[s][i].copy()
        if val > self.gb_val[s]:
            self.gb_val[s] = val
            self.gb_pos[s] = self.pos[s][i].copy()

    # -------------------------------------------------------- change response
    def _handle_change(self):
        for s in range(self.num_swarms):
            self.pb_val[s][:] = -np.inf
            self.gb_val[s] = -np.inf

        # Re-initialise the latter half of swarms for diversity
        n_reinit = max(1, self.num_swarms // 2)
        for s in range(self.num_swarms - n_reinit, self.num_swarms):
            self.pos[s] = self.rng.uniform(
                self.lo, self.hi, (self.swarm_size, self.dim))
            self.vel[s] = self.rng.uniform(
                -10, 10, (self.swarm_size, self.dim))
            self.pb_pos[s] = self.pos[s].copy()

    # -------------------------------------------------------------- exclusion
    def _exclusion(self):
        for i in range(self.num_swarms):
            for j in range(i + 1, self.num_swarms):
                if self.gb_val[i] <= 0 or self.gb_val[j] <= 0:
                    continue
                dist = np.linalg.norm(self.gb_pos[i] - self.gb_pos[j])
                if dist < self.exclusion_radius:
                    worse = i if self.gb_val[i] < self.gb_val[j] else j
                    self._reinit_swarm(worse)

    # -------------------------------------------------------- anti-convergence
    def _anti_convergence(self):
        for s in range(self.num_swarms):
            spread = np.max(np.std(self.pos[s], axis=0))
            if spread < self.convergence_threshold and self.gb_val[s] > 0:
                # Keep the leader, scatter the rest
                for i in range(1, self.swarm_size):
                    self.pos[s][i] = self.rng.uniform(
                        self.lo, self.hi, self.dim)
                    self.vel[s][i] = self.rng.uniform(-10, 10, self.dim)
                    self.pb_val[s][i] = -np.inf
                    self.pb_pos[s][i] = self.pos[s][i].copy()

    # --------------------------------------------------------- helper
    def _reinit_swarm(self, s):
        self.pos[s] = self.rng.uniform(
            self.lo, self.hi, (self.swarm_size, self.dim))
        self.vel[s] = self.rng.uniform(
            -10, 10, (self.swarm_size, self.dim))
        self.pb_pos[s] = self.pos[s].copy()
        self.pb_val[s][:] = -np.inf
        self.gb_val[s] = -np.inf
