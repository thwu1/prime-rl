"""
Multi-Swarm PSO with Exclusion + Gradient Refinement for Dynamic Optimization.
Uses a compiled C shared library (libdopt.so) via ctypes for vectorized
peak evaluation and distance computation.

Adaptive approach:
- dim <= 7: Multi-population PSO with constriction coefficient, exclusion-based
  diversity, quantum particles, gradient-based local refinement, and peak archive
- dim > 7: Multi-start gradient ascent with finite differences, peak archive
  for cross-environment memory, and budget-adaptive exploration/exploitation

C kernel (libdopt.so) provides:
- cone_fitness: surrogate evaluation against archived peaks
- batch_distances: fast nearest-neighbor queries for archive management
"""


import ctypes
import os
import subprocess

import numpy as np


class DynamicOptimizer:
    """Adaptive dynamic optimizer with native C kernel for internal model evaluations."""

    def __init__(self, dim, bounds, seed=0):
        self.dim = dim
        if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
            self.lo, self.hi = float(bounds[0]), float(bounds[1])
        else:
            self.lo, self.hi = -50.0, 50.0
        self.rng = np.random.RandomState(seed)
        span = self.hi - self.lo

        # Build and load C kernel
        self._build_and_load_kernel()

        # Peak memory across environments
        self.archive = []
        self.archive_fit = []
        self.max_archive = 30

        # PSO parameters (constriction coefficient)
        phi = 4.1
        self.chi = 2.0 / abs(2.0 - phi - np.sqrt(phi * phi - 4.0 * phi))
        self.c1 = self.chi * 2.05
        self.c2 = self.chi * 2.05

        if dim <= 7:
            self.mode = 'pso'
            self.n_swarms = max(12, 20 - dim)
            self.swarm_size = 3
            self.n_quantum = 1
            self.v_max = span * 0.3
            self.r_excl = span / (3.0 * max(1.0,
                                  self.n_swarms ** (1.0 / max(1, dim))))
            self.swarms = [self._new_swarm() for _ in range(self.n_swarms)]
        else:
            self.mode = 'gradient'
            self.n_searchers = max(3, 15 - dim)
            self.grad_eps = 1.0
            self.r_excl = span / (3.0 * max(1.0,
                                  10 ** (1.0 / max(1, dim))))

    # ---- C kernel loading ----

    def _build_and_load_kernel(self):
        """Build libdopt.so if absent, then load via ctypes."""
        app_dir = os.path.dirname(os.path.abspath(__file__))
        lib_path = os.path.join(app_dir, 'libdopt.so')
        if not os.path.exists(lib_path):
            subprocess.run(['make', '-C', app_dir], check=True,
                           capture_output=True, timeout=60)
        self._lib = ctypes.CDLL(lib_path)
        self._setup_ctypes()

    def _setup_ctypes(self):
        """Declare function signatures for the C kernel."""
        DPtr = ctypes.POINTER(ctypes.c_double)
        self._lib.cone_fitness.restype = ctypes.c_double
        self._lib.cone_fitness.argtypes = [
            DPtr, DPtr, DPtr, DPtr, ctypes.c_int, ctypes.c_int
        ]
        self._lib.batch_distances.restype = None
        self._lib.batch_distances.argtypes = [
            DPtr, DPtr, ctypes.c_int, ctypes.c_int, DPtr
        ]

    def _c_batch_distances(self, x, positions_list):
        """Compute distances from x to each position using C kernel."""
        x_arr = np.ascontiguousarray(x, dtype=np.float64)
        pos_arr = np.ascontiguousarray(
            np.array(positions_list, dtype=np.float64)
        ).ravel()
        n = len(positions_list)
        out = np.empty(n, dtype=np.float64)
        DPtr = ctypes.POINTER(ctypes.c_double)
        self._lib.batch_distances(
            x_arr.ctypes.data_as(DPtr),
            pos_arr.ctypes.data_as(DPtr),
            n, self.dim,
            out.ctypes.data_as(DPtr)
        )
        return out

    def _c_surrogate_eval(self, x, positions_list, fitnesses):
        """Evaluate x against archived peaks using C cone_fitness kernel."""
        if not positions_list:
            return -np.inf
        x_arr = np.ascontiguousarray(x, dtype=np.float64)
        pos_arr = np.ascontiguousarray(
            np.array(positions_list, dtype=np.float64)
        ).ravel()
        h_arr = np.ascontiguousarray(
            np.array(fitnesses, dtype=np.float64)
        )
        # Use uniform width=5.0 for surrogate cone model
        w_arr = np.full(len(positions_list), 5.0, dtype=np.float64)
        DPtr = ctypes.POINTER(ctypes.c_double)
        return self._lib.cone_fitness(
            x_arr.ctypes.data_as(DPtr),
            pos_arr.ctypes.data_as(DPtr),
            h_arr.ctypes.data_as(DPtr),
            w_arr.ctypes.data_as(DPtr),
            len(positions_list), self.dim
        )

    # ---- Swarm management ----

    def _new_swarm(self, center=None):
        s, d = self.swarm_size, self.dim
        span = self.hi - self.lo
        pos = np.empty((s, d))
        vel = np.empty((s, d))

        # Use surrogate to pick best random start if archive exists
        if center is None and self.archive and len(self.archive) >= 3:
            candidates = [self.rng.uniform(self.lo, self.hi, d)
                          for _ in range(5)]
            scores = [self._c_surrogate_eval(c, self.archive,
                                             self.archive_fit)
                      for c in candidates]
            center = candidates[int(np.argmax(scores))]

        for i in range(s):
            if center is not None and i < s - self.n_quantum:
                pos[i] = np.clip(
                    center + self.rng.randn(d) * self.r_excl * 0.3,
                    self.lo, self.hi)
            else:
                pos[i] = self.rng.uniform(self.lo, self.hi, d)
            vel[i] = self.rng.uniform(-span / 20, span / 20, d)
        return {
            'pos': pos, 'vel': vel, 'pb_pos': pos.copy(),
            'pb_fit': np.full(s, -np.inf),
            'gb_pos': None, 'gb_fit': -np.inf, 'stag': 0,
        }

    def _reinit_swarm(self, sw):
        s, d = self.swarm_size, self.dim
        span = self.hi - self.lo
        for i in range(s):
            sw['pos'][i] = self.rng.uniform(self.lo, self.hi, d)
            sw['vel'][i] = self.rng.uniform(-span / 20, span / 20, d)
        sw['pb_pos'] = sw['pos'].copy()
        sw['pb_fit'] = np.full(s, -np.inf)
        sw['gb_pos'] = None
        sw['gb_fit'] = -np.inf
        sw['stag'] = 0

    def _exclusion(self):
        for i in range(self.n_swarms):
            si = self.swarms[i]
            if si['gb_pos'] is None:
                continue
            for j in range(i + 1, self.n_swarms):
                sj = self.swarms[j]
                if sj['gb_pos'] is None:
                    continue
                if np.linalg.norm(si['gb_pos'] - sj['gb_pos']) < self.r_excl:
                    if si['gb_fit'] < sj['gb_fit']:
                        self._reinit_swarm(si)
                        break
                    else:
                        self._reinit_swarm(sj)

    # ---- PSO optimization ----

    def _pso_optimize(self, eval_fn, budget):
        remaining = budget
        refine_budget = min(budget // 8, (2 * self.dim + 1) * 40)

        # Phase 1: Re-evaluate archive and seed swarms from best positions
        if self.archive:
            for i in range(len(self.archive)):
                if remaining <= refine_budget:
                    break
                self.archive_fit[i] = eval_fn(self.archive[i])
                remaining -= 1
            sorted_idx = sorted(range(len(self.archive)),
                                key=lambda i: self.archive_fit[i],
                                reverse=True)
            for s_i, a_i in enumerate(sorted_idx[:self.n_swarms]):
                p = self.archive[a_i].copy()
                self.swarms[s_i]['pos'][0] = p
                self.swarms[s_i]['pb_pos'][0] = p.copy()

        # Phase 2: evaluate all particles at current positions
        for sw in self.swarms:
            for i in range(self.swarm_size):
                if remaining <= refine_budget:
                    break
                f = eval_fn(sw['pos'][i])
                remaining -= 1
                if f > sw['pb_fit'][i]:
                    sw['pb_fit'][i] = f
                    sw['pb_pos'][i] = sw['pos'][i].copy()
                if f > sw['gb_fit']:
                    sw['gb_fit'] = f
                    sw['gb_pos'] = sw['pos'][i].copy()
            else:
                continue
            break

        # Phase 3: PSO iterations
        gen = 0
        while remaining > refine_budget:
            stop = False
            for sw in self.swarms:
                gb = sw['gb_pos']
                for i in range(self.swarm_size):
                    if remaining <= refine_budget:
                        stop = True
                        break

                    if i >= self.swarm_size - self.n_quantum:
                        # Quantum particle: explore near swarm best
                        if gb is not None:
                            sw['pos'][i] = (
                                gb + self.rng.randn(self.dim) *
                                self.r_excl * 0.3
                            )
                        else:
                            sw['pos'][i] = self.rng.uniform(
                                self.lo, self.hi, self.dim)
                    else:
                        # Standard constriction PSO update
                        if gb is not None:
                            r1 = self.rng.random(self.dim)
                            r2 = self.rng.random(self.dim)
                            sw['vel'][i] = (
                                self.chi * sw['vel'][i] +
                                self.c1 * r1 * (sw['pb_pos'][i] -
                                                sw['pos'][i]) +
                                self.c2 * r2 * (gb - sw['pos'][i]))
                        else:
                            r1 = self.rng.random(self.dim)
                            sw['vel'][i] = (
                                self.chi * sw['vel'][i] +
                                self.c1 * r1 * (sw['pb_pos'][i] -
                                                sw['pos'][i]))
                        sw['vel'][i] = np.clip(sw['vel'][i],
                                               -self.v_max, self.v_max)
                        sw['pos'][i] += sw['vel'][i]

                    sw['pos'][i] = np.clip(sw['pos'][i], self.lo, self.hi)
                    f = eval_fn(sw['pos'][i])
                    remaining -= 1

                    if f > sw['pb_fit'][i]:
                        sw['pb_fit'][i] = f
                        sw['pb_pos'][i] = sw['pos'][i].copy()
                    if f > sw['gb_fit']:
                        sw['gb_fit'] = f
                        sw['gb_pos'] = sw['pos'][i].copy()

                if stop:
                    break
            if stop:
                break

            if gen % 2 == 0:
                self._exclusion()

            # Anti-convergence: diversify stagnant swarms
            if gen % 8 == 0 and gen > 0:
                for sw in self.swarms:
                    if sw['gb_pos'] is None:
                        continue
                    spread = max(
                        np.linalg.norm(sw['pos'][k] - sw['gb_pos'])
                        for k in range(self.swarm_size))
                    if spread < 0.1:
                        sw['stag'] += 1
                        if sw['stag'] > 2:
                            for k in range(1, self.swarm_size):
                                sw['pos'][k] = np.clip(
                                    sw['gb_pos'] +
                                    self.rng.randn(self.dim) *
                                    self.r_excl * 0.5,
                                    self.lo, self.hi)
                                sw['vel'][k] = self.rng.uniform(
                                    -(self.hi - self.lo) / 20,
                                    (self.hi - self.lo) / 20, self.dim)
                                sw['pb_pos'][k] = sw['pos'][k].copy()
                                sw['pb_fit'][k] = -np.inf
                            sw['stag'] = 0
                    else:
                        sw['stag'] = 0
            gen += 1

        # Save discovered peaks to archive
        for sw in self.swarms:
            if sw['gb_pos'] is not None:
                self._add_to_archive(sw['gb_pos'].copy(), sw['gb_fit'])

        # Phase 4: Gradient refinement on best found position
        gb_pos = None
        gb_fit = -np.inf
        for sw in self.swarms:
            if sw['gb_fit'] > gb_fit and sw['gb_pos'] is not None:
                gb_fit = sw['gb_fit']
                gb_pos = sw['gb_pos'].copy()

        if gb_pos is not None and remaining >= 2 * self.dim + 1:
            pos = gb_pos
            fit = gb_fit
            step = 2.0
            eps = 1.0
            while remaining >= 2 * self.dim + 1:
                grad = np.zeros(self.dim)
                for d in range(self.dim):
                    xp = pos.copy()
                    xp[d] = min(self.hi, pos[d] + eps)
                    xm = pos.copy()
                    xm[d] = max(self.lo, pos[d] - eps)
                    fp = eval_fn(xp)
                    fm = eval_fn(xm)
                    remaining -= 2
                    delta = xp[d] - xm[d]
                    if abs(delta) > 1e-10:
                        grad[d] = (fp - fm) / delta
                gn = np.linalg.norm(grad)
                if gn > 1e-8:
                    new_pos = np.clip(pos + step * grad / gn,
                                     self.lo, self.hi)
                else:
                    break
                new_fit = eval_fn(new_pos)
                remaining -= 1
                if new_fit > fit:
                    pos = new_pos
                    fit = new_fit
                    step = min(step * 1.5, 5.0)
                else:
                    step *= 0.5
                    eps *= 0.7
                    if step < 0.01:
                        break
            self._add_to_archive(pos.copy(), fit)
            gb_pos = pos

        # Use remaining budget near best
        while remaining > 0:
            if gb_pos is not None:
                x = np.clip(
                    gb_pos + self.rng.randn(self.dim) * 0.1,
                    self.lo, self.hi)
            else:
                x = self.rng.uniform(self.lo, self.hi, self.dim)
            eval_fn(x)
            remaining -= 1

    # ---- Gradient-based optimization ----

    def _gradient_step(self, eval_fn, x, step, eps):
        grad = np.zeros(self.dim)
        evals = 0
        for d in range(self.dim):
            xp = x.copy()
            xp[d] = min(self.hi, x[d] + eps)
            xm = x.copy()
            xm[d] = max(self.lo, x[d] - eps)
            fp = eval_fn(xp)
            fm = eval_fn(xm)
            evals += 2
            delta = xp[d] - xm[d]
            if abs(delta) > 1e-10:
                grad[d] = (fp - fm) / delta
        gn = np.linalg.norm(grad)
        if gn > 1e-8:
            x_new = np.clip(x + step * grad / gn, self.lo, self.hi)
        else:
            x_new = x.copy()
        f_new = eval_fn(x_new)
        evals += 1
        return x_new, f_new, evals

    def _gradient_optimize(self, eval_fn, budget):
        remaining = budget
        eps_step = 2 * self.dim + 1

        # Re-evaluate archive
        for i in range(len(self.archive)):
            if remaining <= 0:
                break
            self.archive_fit[i] = eval_fn(self.archive[i])
            remaining -= 1

        # Refine best archive positions
        if self.archive:
            sorted_idx = sorted(range(len(self.archive)),
                                key=lambda i: self.archive_fit[i],
                                reverse=True)
            n_ref = min(3, len(sorted_idx))
            per_ref = min(remaining // max(1, n_ref + self.n_searchers),
                          eps_step * 40)
            for k in range(n_ref):
                if remaining < eps_step:
                    break
                x = self.archive[sorted_idx[k]].copy()
                f = self.archive_fit[sorted_idx[k]]
                step = 2.0
                used = 0
                while (used + eps_step <= per_ref and
                       remaining >= eps_step):
                    xn, fn, ev = self._gradient_step(
                        eval_fn, x, step, self.grad_eps)
                    remaining -= ev
                    used += ev
                    if fn > f:
                        x = xn
                        f = fn
                    else:
                        step *= 0.5
                        if step < 0.01:
                            break
                self._add_to_archive(x, f)

        # Explore from random starting points
        n_explore = max(1, remaining // (eps_step * 20))
        per_explore = remaining // max(1, n_explore)
        for k in range(n_explore):
            if remaining < eps_step:
                break
            x = self.rng.uniform(self.lo, self.hi, self.dim)
            f = eval_fn(x)
            remaining -= 1
            step = 8.0
            used = 1
            while (used + eps_step <= per_explore and
                   remaining >= eps_step):
                xn, fn, ev = self._gradient_step(
                    eval_fn, x, step, self.grad_eps)
                remaining -= ev
                used += ev
                if fn > f:
                    x = xn
                    f = fn
                else:
                    step *= 0.6
                    if step < 0.05:
                        break
            self._add_to_archive(x, f)

        # Use remaining budget searching near best known position
        while remaining > 0:
            if self.archive:
                bi = max(range(len(self.archive_fit)),
                         key=lambda i: self.archive_fit[i])
                x = np.clip(
                    self.archive[bi] + self.rng.randn(self.dim) * 2.0,
                    self.lo, self.hi)
            else:
                x = self.rng.uniform(self.lo, self.hi, self.dim)
            eval_fn(x)
            remaining -= 1

    # ---- Archive management (uses C kernel) ----

    def _add_to_archive(self, pos, fit):
        if self.archive:
            dists = self._c_batch_distances(pos, self.archive)
            closest = int(np.argmin(dists))
            if dists[closest] < self.r_excl:
                if fit > self.archive_fit[closest]:
                    self.archive[closest] = pos.copy()
                    self.archive_fit[closest] = fit
                return
        self.archive.append(pos.copy())
        self.archive_fit.append(fit)
        if len(self.archive) > self.max_archive:
            worst = min(range(len(self.archive_fit)),
                        key=lambda i: self.archive_fit[i])
            del self.archive[worst]
            del self.archive_fit[worst]

    # ---- Public interface ----

    def optimize_environment(self, eval_fn, budget):
        if self.mode == 'pso':
            self._pso_optimize(eval_fn, budget)
        else:
            self._gradient_optimize(eval_fn, budget)

    def on_change(self):
        if self.mode == 'pso':
            # Save swarm bests to archive before resetting
            for sw in self.swarms:
                if sw['gb_pos'] is not None:
                    self._add_to_archive(sw['gb_pos'].copy(), sw['gb_fit'])
            # Sort archive by fitness (best first) for better seeding
            if self.archive and any(f > -np.inf for f in self.archive_fit):
                pairs = list(zip(self.archive, self.archive_fit))
                pairs.sort(key=lambda p: p[1], reverse=True)
                self.archive = [p[0] for p in pairs]
            # Reset fitness (positions retained as memory)
            for sw in self.swarms:
                sw['pb_fit'] = np.full(self.swarm_size, -np.inf)
                sw['gb_fit'] = -np.inf
                sw['gb_pos'] = None
                sw['stag'] = 0
            # Reinitialize 2 swarms for exploration diversity
            n_reinit = min(2, self.n_swarms)
            indices = self.rng.choice(self.n_swarms, n_reinit, replace=False)
            for idx in indices:
                self._reinit_swarm(self.swarms[idx])
        # Archive positions retained but fitness invalidated
        self.archive_fit = [-np.inf] * len(self.archive)
