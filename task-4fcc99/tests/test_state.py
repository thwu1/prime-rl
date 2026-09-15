
import numpy as np
import pytest
import os


# Problem parameters (must match config.json and generate_target.py)
N = 64
KAPPA_1 = 0.01
DT = 0.005
N_STEPS_1 = 10
N_STEPS_2 = 8
H = 1.0 / N
H_INV_SQ = 1.0 / (H * H)


def numpy_forward(ic, kappa, n_steps):
    """Run forward heat equation simulation using numpy (independent of Warp)."""
    u = ic.astype(np.float64).copy()
    for _ in range(n_steps):
        lap = (
            np.roll(u, -1, axis=0)
            + np.roll(u, 1, axis=0)
            + np.roll(u, -1, axis=1)
            + np.roll(u, 1, axis=1)
            - 4.0 * u
        ) * H_INV_SQ
        u = u + kappa * DT * lap
    return u


def numpy_two_phase(ic, kappa_1, kappa_2):
    """Run two-phase forward simulation using numpy."""
    mid = numpy_forward(ic, kappa_1, N_STEPS_1)
    return numpy_forward(mid, kappa_2, N_STEPS_2)


@pytest.fixture(scope="session")
def true_kappa2():
    """Derive the true kappa_2 from calibration data via grid search.

    This avoids storing the ground-truth value in any file accessible
    to the agent, preventing trivial extraction of the answer.
    """
    ic_b = np.load("/app/known_ic_b.npy").astype(np.float64)
    target_b = np.load("/app/target_b.npy").astype(np.float64)

    mid_b = numpy_forward(ic_b, KAPPA_1, N_STEPS_1)

    best_k2, best_mse = 0.0, float("inf")
    for k2 in np.linspace(0.001, 0.02, 500):
        result = numpy_forward(mid_b, k2, N_STEPS_2)
        mse = float(np.mean((result - target_b) ** 2))
        if mse < best_mse:
            best_mse = mse
            best_k2 = k2
    return best_k2


class TestOutputFilesExist:
    def test_optimized_ic_exists(self):
        assert os.path.isfile(
            "/app/results/optimized_ic_a.npy"
        ), "Missing /app/results/optimized_ic_a.npy"

    def test_estimated_kappa2_exists(self):
        assert os.path.isfile(
            "/app/results/estimated_kappa2.txt"
        ), "Missing /app/results/estimated_kappa2.txt"

    def test_final_mse_exists(self):
        assert os.path.isfile(
            "/app/results/final_mse.txt"
        ), "Missing /app/results/final_mse.txt"


class TestOptimizedICShape:
    def test_shape(self):
        ic = np.load("/app/results/optimized_ic_a.npy")
        assert ic.shape == (
            64,
            64,
        ), f"Expected shape (64, 64), got {ic.shape}"

    def test_finite_values(self):
        ic = np.load("/app/results/optimized_ic_a.npy")
        assert np.all(np.isfinite(ic)), "Optimized IC contains non-finite values"


class TestKappa2Estimation:
    def test_kappa2_close_to_true(self, true_kappa2):
        with open("/app/results/estimated_kappa2.txt") as f:
            estimated = float(f.read().strip())
        assert abs(estimated - true_kappa2) < 0.002, (
            f"Estimated kappa2={estimated:.6f} too far from derived true value "
            f"{true_kappa2:.6f} (tolerance 0.002)"
        )

    def test_kappa2_positive(self):
        with open("/app/results/estimated_kappa2.txt") as f:
            kappa2 = float(f.read().strip())
        assert kappa2 > 0.0, f"kappa_2 must be positive, got {kappa2}"


class TestForwardSimMatchesTarget:
    def test_mse_ic_a_recovery(self):
        """Forward sim from recovered IC with estimated kappa2 must match target A."""
        ic_a = np.load("/app/results/optimized_ic_a.npy")
        with open("/app/results/estimated_kappa2.txt") as f:
            kappa2 = float(f.read().strip())
        target_a = np.load("/app/target_a.npy")

        result = numpy_two_phase(ic_a, KAPPA_1, kappa2)
        mse = float(np.mean((result - target_a.astype(np.float64)) ** 2))
        assert mse < 1e-3, (
            f"MSE for IC_A recovery: {mse:.6e}, expected < 1e-3"
        )

    def test_calibration_consistency(self):
        """Estimated kappa2 must produce correct result with known IC_B."""
        with open("/app/results/estimated_kappa2.txt") as f:
            kappa2 = float(f.read().strip())
        ic_b = np.load("/app/known_ic_b.npy")
        target_b = np.load("/app/target_b.npy")

        result = numpy_two_phase(ic_b, KAPPA_1, kappa2)
        mse = float(np.mean((result - target_b.astype(np.float64)) ** 2))
        assert mse < 5e-4, (
            f"Calibration MSE with estimated kappa2: {mse:.6e}, expected < 5e-4"
        )


class TestFinalMSE:
    def test_reported_mse_below_threshold(self):
        with open("/app/results/final_mse.txt") as f:
            mse = float(f.read().strip())
        assert mse < 1e-3, (
            f"Reported final MSE is {mse:.6e}, expected < 1e-3"
        )

    def test_reported_mse_nonnegative(self):
        with open("/app/results/final_mse.txt") as f:
            mse = float(f.read().strip())
        assert mse >= 0.0, f"MSE should be non-negative, got {mse}"


class TestUsesWarp:
    def test_warp_kernel_in_code(self):
        """Verify that Python code under /app uses @wp.kernel."""
        found = False
        for root, dirs, files in os.walk("/app"):
            if "results" in root:
                continue
            for fn in files:
                if fn.endswith(".py"):
                    path = os.path.join(root, fn)
                    with open(path) as f:
                        content = f.read()
                    if "@wp.kernel" in content or "@warp.kernel" in content:
                        found = True
                        break
            if found:
                break
        assert found, "No @wp.kernel decorator found in any Python file under /app"

    def test_warp_tape_in_code(self):
        """Verify that Python code under /app uses wp.Tape."""
        found = False
        for root, dirs, files in os.walk("/app"):
            if "results" in root:
                continue
            for fn in files:
                if fn.endswith(".py"):
                    path = os.path.join(root, fn)
                    with open(path) as f:
                        content = f.read()
                    if "wp.Tape" in content or "warp.Tape" in content:
                        found = True
                        break
            if found:
                break
        assert found, "No wp.Tape usage found in any Python file under /app"
