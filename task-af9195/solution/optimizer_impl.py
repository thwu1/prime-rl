"""Multi-Quantum Swarm Optimization (mQSO) for dynamic environments.

Maintains multiple sub-swarms, each tracking a different peak.
Key mechanisms:
  - Constriction-coefficient PSO within each sub-swarm
  - Quantum particles for local exploration around each swarm's best
  - Exclusion: re-initialises the worse swarm when two converge together
  - Anti-convergence: re-initialises stagnant swarms
  - Change response: resets memorised fitness values after a detected change

Reference: Blackwell & Branke, "Multiswarms, exclusion, and anti-convergence
in dynamic environments," IEEE TEC, 2006.
"""


import numpy as np
from typing import List


class Optimizer:
    """mQSO-based dynamic optimizer."""

    def __init__(self, dimension: int, bounds: tuple,
                 num_peaks: int, seed: int = 42):
        self.dimension = dimension
        self.lb, self.ub = bounds
        self.num_peaks = num_peaks
        self.rng = np.random.RandomState(seed)

        # ── algorithm hyper-parameters ──────────────────────────────────
        self.num_swarms = num_peaks
        self.swarm_size = 5          # regular PSO particles per swarm
        self.num_quantum = 2         # quantum particles per swarm
        self.w = 0.729844            # constriction coefficient
        self.c1 = 1.49618            # cognitive acceleration
        self.c2 = 1.49618            # social acceleration
        self.quantum_radius = 15.0   # exploration radius around gbest
        self.exclusion_radius = 20.0 # min distance between swarm gbests
        self.stag_limit = 25         # generations before anti-convergence

        # ── initialise swarms ───────────────────────────────────────────
        self.swarms: List[dict] = [
            self._new_swarm() for _ in range(self.num_swarms)
        ]
        self.generation = 0

    # ── public interface ────────────────────────────────────────────────

    def ask(self) -> List[np.ndarray]:
        out: List[np.ndarray] = []
        for sw in self.swarms:
            for i in range(self.swarm_size):
                out.append(sw["pos"][i].copy())
            for i in range(self.num_quantum):
                out.append(sw["qpos"][i].copy())
        return out

    def tell(self, solutions: List[np.ndarray], values: List[float],
             environment_changed: bool) -> None:

        if environment_changed:
            self._on_change()

        idx = 0
        for sw in self.swarms:
            prev_gbest_val = sw["gbest_val"]

            # regular particles
            for i in range(self.swarm_size):
                v = values[idx]
                s = np.asarray(solutions[idx], dtype=float)
                if v > sw["pbest_val"][i]:
                    sw["pbest_val"][i] = v
                    sw["pbest_pos"][i] = s.copy()
                if v > sw["gbest_val"]:
                    sw["gbest_val"] = v
                    sw["gbest_pos"] = s.copy()
                idx += 1

            # quantum particles
            for i in range(self.num_quantum):
                v = values[idx]
                s = np.asarray(solutions[idx], dtype=float)
                if v > sw["gbest_val"]:
                    sw["gbest_val"] = v
                    sw["gbest_pos"] = s.copy()
                idx += 1

            # stagnation counter
            if sw["gbest_val"] <= prev_gbest_val + 1e-12:
                sw["stag"] += 1
            else:
                sw["stag"] = 0

        # ── PSO velocity/position update ────────────────────────────────
        self._update_particles()

        # ── quantum particle update ─────────────────────────────────────
        self._update_quantum()

        # ── exclusion ───────────────────────────────────────────────────
        self._exclusion()

        # ── anti-convergence ────────────────────────────────────────────
        self._anti_convergence()

        self.generation += 1

    # ── internals ───────────────────────────────────────────────────────

    def _new_swarm(self) -> dict:
        d = self.dimension
        pos = self.rng.uniform(self.lb, self.ub, (self.swarm_size, d))
        vel = self.rng.uniform(
            -(self.ub - self.lb) * 0.05,
             (self.ub - self.lb) * 0.05,
            (self.swarm_size, d),
        )
        qpos = self.rng.uniform(self.lb, self.ub, (self.num_quantum, d))
        return dict(
            pos=pos,
            vel=vel,
            pbest_pos=pos.copy(),
            pbest_val=np.full(self.swarm_size, -np.inf),
            gbest_pos=pos[0].copy(),
            gbest_val=-np.inf,
            qpos=qpos,
            stag=0,
        )

    def _on_change(self):
        """Reset memorised fitness after an environment change."""
        for sw in self.swarms:
            sw["pbest_val"][:] = -np.inf
            sw["gbest_val"] = -np.inf
            sw["stag"] = 0

    def _clip(self, x: np.ndarray) -> np.ndarray:
        return np.clip(x, self.lb, self.ub)

    def _update_particles(self):
        for sw in self.swarms:
            for i in range(self.swarm_size):
                r1 = self.rng.rand(self.dimension)
                r2 = self.rng.rand(self.dimension)
                sw["vel"][i] = (
                    self.w * sw["vel"][i]
                    + self.c1 * r1 * (sw["pbest_pos"][i] - sw["pos"][i])
                    + self.c2 * r2 * (sw["gbest_pos"] - sw["pos"][i])
                )
                sw["pos"][i] += sw["vel"][i]

                # boundary handling — absorb
                below = sw["pos"][i] < self.lb
                above = sw["pos"][i] > self.ub
                sw["vel"][i][below | above] *= -0.5
                sw["pos"][i] = self._clip(sw["pos"][i])

    def _update_quantum(self):
        for sw in self.swarms:
            for i in range(self.num_quantum):
                direction = self.rng.randn(self.dimension)
                norm = np.linalg.norm(direction)
                if norm > 1e-10:
                    direction /= norm
                dist = self.rng.uniform(0, self.quantum_radius)
                sw["qpos"][i] = self._clip(
                    sw["gbest_pos"] + dist * direction
                )

    def _exclusion(self):
        """If two swarms share a peak, re-initialise the worse one."""
        for i in range(self.num_swarms):
            for j in range(i + 1, self.num_swarms):
                d = np.linalg.norm(
                    self.swarms[i]["gbest_pos"] - self.swarms[j]["gbest_pos"]
                )
                if d < self.exclusion_radius:
                    if self.swarms[i]["gbest_val"] < self.swarms[j]["gbest_val"]:
                        self.swarms[i] = self._new_swarm()
                    else:
                        self.swarms[j] = self._new_swarm()

    def _anti_convergence(self):
        """Re-initialise long-stagnant swarms (except the overall best)."""
        if not self.swarms:
            return
        best_idx = max(range(self.num_swarms),
                       key=lambda k: self.swarms[k]["gbest_val"])
        for i in range(self.num_swarms):
            if i != best_idx and self.swarms[i]["stag"] >= self.stag_limit:
                self.swarms[i] = self._new_swarm()
