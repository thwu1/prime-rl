import ctypes
import numpy as np
import os

# Load C shared library for peak evaluation
_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libpeaks.so")
_lib = ctypes.CDLL(_lib_path)
_lib.evaluate_peaks.restype = ctypes.c_double
_lib.evaluate_peaks.argtypes = [
    ctypes.POINTER(ctypes.c_double),
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double),
    ctypes.c_int,
]


class GMPB:
    """Generalized Moving Peaks Benchmark with C-accelerated peak evaluation."""

    def __init__(self, dim, num_peaks, shift_severity, change_frequency,
                 num_environments, seed):
        self.dim = dim
        self.num_peaks = num_peaks
        self.shift_severity = shift_severity
        self.change_frequency = change_frequency
        self.num_environments = num_environments

        self.rng = np.random.default_rng(seed)

        self.positions = []
        self.heights = []
        self.widths = []
        self.velocities = []

        for _ in range(num_peaks):
            self.positions.append(self.rng.uniform(-50, 50, dim).copy())
            self.heights.append(float(self.rng.uniform(30.0, 70.0)))
            self.widths.append(float(self.rng.uniform(5.0, 20.0)))
            v = self.rng.standard_normal(dim)
            nrm = np.linalg.norm(v)
            if nrm < 1e-15:
                v = np.ones(dim) / np.sqrt(dim)
            else:
                v = v / nrm
            self.velocities.append((shift_severity * v).copy())

        self._update_c_arrays()

        self.current_env = 1
        self.eval_count = 0
        self.total_eval_count = 0
        self._changed = False

        self.best_found_value = -np.inf
        self.cumulative_error = 0.0

        # Per-environment stats
        self._env_stats = []
        self._cur_env_error_sum = 0.0
        self._cur_env_eval_count = 0
        self._cur_env_best_found = -np.inf
        self._cur_env_optimum = max(self.heights)

    def _update_c_arrays(self):
        self._positions_flat = np.ascontiguousarray(
            np.concatenate(self.positions), dtype=np.float64)
        self._heights_arr = np.ascontiguousarray(
            self.heights, dtype=np.float64)
        self._widths_arr = np.ascontiguousarray(
            self.widths, dtype=np.float64)

    def evaluate(self, x):
        if self.has_terminated():
            raise RuntimeError("Benchmark has terminated")

        x = np.ascontiguousarray(x, dtype=np.float64)
        self._changed = False

        val = _lib.evaluate_peaks(
            x.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            self.dim,
            self._positions_flat.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            self._heights_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            self._widths_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            self.num_peaks,
        )

        if val > self.best_found_value:
            self.best_found_value = val
        if val > self._cur_env_best_found:
            self._cur_env_best_found = val

        opt_val = max(self.heights)
        error = opt_val - self.best_found_value
        self.cumulative_error += error
        self._cur_env_error_sum += error
        self._cur_env_eval_count += 1

        self.eval_count += 1
        self.total_eval_count += 1

        if (self.eval_count >= self.change_frequency
                and self.current_env < self.num_environments):
            self._save_current_env_stats()
            self._change_environment()
            self.current_env += 1
            self.eval_count = 0
            self.best_found_value = -np.inf
            self._changed = True
            self._cur_env_error_sum = 0.0
            self._cur_env_eval_count = 0
            self._cur_env_best_found = -np.inf
            self._cur_env_optimum = max(self.heights)

        if self.has_terminated() and self._cur_env_eval_count > 0:
            self._save_current_env_stats()

        return val

    def _save_current_env_stats(self):
        if self._cur_env_eval_count > 0:
            self._env_stats.append({
                "env_index": self.current_env,
                "avg_error": self._cur_env_error_sum / self._cur_env_eval_count,
                "best_found": self._cur_env_best_found,
                "optimum_value": self._cur_env_optimum,
            })

    def _change_environment(self):
        lam = 0.5
        sigma_h = 1.0
        sigma_w = 0.5

        for k in range(self.num_peaks):
            r = self.rng.standard_normal(self.dim)
            nrm_r = np.linalg.norm(r)
            if nrm_r < 1e-15:
                r = np.ones(self.dim) / np.sqrt(self.dim)
            else:
                r = r / nrm_r

            nrm_v = np.linalg.norm(self.velocities[k])
            if nrm_v < 1e-15:
                v_dir = np.ones(self.dim) / np.sqrt(self.dim)
            else:
                v_dir = self.velocities[k] / nrm_v

            u = lam * v_dir + (1 - lam) * r
            nrm_u = np.linalg.norm(u)
            if nrm_u < 1e-15:
                u = r
                nrm_u = 1.0
            self.velocities[k] = (self.shift_severity * u / nrm_u).copy()

            self.positions[k] = np.clip(
                self.positions[k] + self.velocities[k], -100.0, 100.0
            )
            self.heights[k] = float(np.clip(
                self.heights[k] + sigma_h * self.rng.standard_normal(),
                30.0, 70.0
            ))
            self.widths[k] = float(np.clip(
                self.widths[k] + sigma_w * self.rng.standard_normal(),
                5.0, 20.0
            ))

        self._update_c_arrays()

    def get_current_environment(self):
        return self.current_env

    def get_global_optimum(self):
        k_best = int(np.argmax(self.heights))
        return self.positions[k_best].copy(), self.heights[k_best]

    def get_offline_error(self):
        if self.total_eval_count == 0:
            return 0.0
        return self.cumulative_error / self.total_eval_count

    def has_terminated(self):
        return self.total_eval_count >= self.num_environments * self.change_frequency

    def has_changed(self):
        return self._changed

    def get_env_stats(self):
        stats = list(self._env_stats)
        if self._cur_env_eval_count > 0:
            saved_envs = {s["env_index"] for s in stats}
            if self.current_env not in saved_envs:
                stats.append({
                    "env_index": self.current_env,
                    "avg_error": self._cur_env_error_sum / self._cur_env_eval_count,
                    "best_found": self._cur_env_best_found,
                    "optimum_value": self._cur_env_optimum,
                })
        return stats
