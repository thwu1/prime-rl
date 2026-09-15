
import numpy as np
import json
import os


def load_config():
    with open('/app/data/config.json') as f:
        return json.load(f)


def compute_kernel_matvec(X, v, sigma, chunk_size=1000):
    """Compute K @ v without forming the full kernel matrix.

    Uses the identity ||a-b||^2 = ||a||^2 + ||b||^2 - 2 a^T b
    to avoid allocating (chunk, n, d) intermediates.
    """
    n = X.shape[0]
    result = np.zeros(n)
    sq_norms = np.sum(X ** 2, axis=1)

    for i in range(0, n, chunk_size):
        end = min(i + chunk_size, n)
        cross = X[i:end] @ X.T
        dists_sq = sq_norms[i:end, None] + sq_norms[None, :] - 2.0 * cross
        np.maximum(dists_sq, 0.0, out=dists_sq)
        K_chunk = np.exp(-dists_sq / (2.0 * sigma ** 2))
        result[i:end] = K_chunk @ v
    return result


class TestNystromPCG:
    """Verify the Nystrom-preconditioned CG solution for kernel ridge regression."""

    def setup_method(self):
        self.config = load_config()
        self.X = np.load('/app/data/X.npy')
        self.y = np.load('/app/data/y.npy')

    # ---- existence and shape checks ----

    def test_output_files_exist(self):
        for fname in ['alpha.npy', 'landmarks.npy',
                       'residual_history.npy', 'num_iterations.txt']:
            path = os.path.join('/app/output', fname)
            assert os.path.exists(path), f"{fname} missing from /app/output/"

    def test_solution_shape(self):
        alpha = np.load('/app/output/alpha.npy')
        n = self.config['n']
        assert alpha.shape == (n,), \
            f"Expected alpha shape ({n},), got {alpha.shape}"

    def test_solution_finite(self):
        alpha = np.load('/app/output/alpha.npy')
        assert np.all(np.isfinite(alpha)), "Solution contains NaN or Inf"

    # ---- accuracy check (independent kernel matvec) ----

    def test_solution_accuracy(self):
        alpha = np.load('/app/output/alpha.npy')
        sigma = self.config['sigma']
        lam = self.config['lambda']
        tol = self.config['residual_tolerance']

        Kalpha = compute_kernel_matvec(self.X, alpha, sigma)
        residual = Kalpha + lam * alpha - self.y
        rel_residual = np.linalg.norm(residual) / np.linalg.norm(self.y)

        assert rel_residual < tol, \
            f"Relative residual {rel_residual:.2e} exceeds tolerance {tol}"

    # ---- landmark validity ----

    def test_landmarks_valid_indices(self):
        landmarks = np.load('/app/output/landmarks.npy')
        n = self.config['n']
        assert np.issubdtype(landmarks.dtype, np.integer), \
            f"Landmarks must be integer type, got {landmarks.dtype}"
        assert np.all(landmarks >= 0), "Negative landmark index found"
        assert np.all(landmarks < n), f"Landmark index >= {n} found"

    def test_landmarks_unique(self):
        landmarks = np.load('/app/output/landmarks.npy')
        assert len(np.unique(landmarks)) == len(landmarks), \
            "Duplicate landmark indices found"

    def test_landmarks_count(self):
        landmarks = np.load('/app/output/landmarks.npy')
        s_min = self.config['min_landmarks']
        s_max = self.config['max_landmarks']
        s = len(landmarks)
        assert s_min <= s <= s_max, \
            f"Landmark count {s} outside [{s_min}, {s_max}]"

    # ---- convergence checks ----

    def test_convergence_iterations(self):
        with open('/app/output/num_iterations.txt') as f:
            num_iter = int(f.read().strip())
        max_iter = self.config['max_cg_iterations']
        assert 0 < num_iter < max_iter, \
            f"Iterations {num_iter} not in (0, {max_iter})"

    def test_residual_history_consistency(self):
        residual_history = np.load('/app/output/residual_history.npy')
        tol = self.config['residual_tolerance']

        assert len(residual_history) >= 2, \
            "Residual history must have at least 2 entries (initial + final)"
        assert np.all(np.isfinite(residual_history)), \
            "Residual history contains NaN or Inf"
        assert residual_history[-1] < tol, \
            f"Final residual {residual_history[-1]:.2e} >= tolerance {tol}"
        assert residual_history[0] > residual_history[-1], \
            "No convergence: initial residual not larger than final"
