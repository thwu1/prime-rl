
"""
Verification tests for the planar double-pendulum constrained-dynamics
simulation.  Tests build the C++ project from source, run the binary with
various configurations, invoke a Python ODE reference, and check physical
correctness of the results.
"""

import os
import shutil
import subprocess
import numpy as np
import pytest

BUILD_DIR = "/app/sim/build"
REF_SCRIPT = "/app/reference/pendulum_ref.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sim_binary():
    """Configure, build the C++ project, and return the path to the binary."""
    if os.path.exists(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
    os.makedirs(BUILD_DIR)

    cmake = subprocess.run(
        ["cmake", ".."],
        cwd=BUILD_DIR, capture_output=True, text=True, timeout=60,
    )
    assert cmake.returncode == 0, (
        f"CMake configuration failed:\n{cmake.stdout}\n{cmake.stderr}"
    )

    make = subprocess.run(
        ["make", "-j2"],
        cwd=BUILD_DIR, capture_output=True, text=True, timeout=120,
    )
    assert make.returncode == 0, (
        f"Build failed:\n{make.stdout}\n{make.stderr}"
    )

    binary = os.path.join(BUILD_DIR, "sim")
    assert os.path.isfile(binary), "sim binary not found after build"
    return binary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_sim(binary, theta1, theta2, omega1, omega2,
             rho_inf, h, t_end, out_path):
    """Run the C++ simulation and return the CSV data as a numpy array."""
    r = subprocess.run(
        [binary,
         str(theta1), str(theta2), str(omega1), str(omega2),
         str(rho_inf), str(h), str(t_end), out_path],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"Simulation crashed:\n{r.stderr}"
    return np.loadtxt(out_path, delimiter=",", skiprows=1)


def _run_ref(theta1, theta2, omega1, omega2, t_end, out_path):
    """Run the Python ODE reference and return CSV data."""
    r = subprocess.run(
        ["python3", REF_SCRIPT,
         str(theta1), str(theta2), str(omega1), str(omega2),
         str(t_end), out_path],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"Reference solver failed:\n{r.stderr}"
    return np.loadtxt(out_path, delimiter=",", skiprows=1)


# Column indices in the C++ output CSV
COL_TIME = 0
COL_THETA1 = 3
COL_THETA2 = 6
COL_CVIOL = 13
COL_ENERGY = 14

# Column indices in the reference CSV
REF_TIME = 0
REF_THETA1 = 1
REF_THETA2 = 2


# ---------------------------------------------------------------------------
# Tests: Build
# ---------------------------------------------------------------------------

class TestBuild:
    def test_binary_exists(self, sim_binary):
        assert os.path.isfile(sim_binary)


# ---------------------------------------------------------------------------
# Tests: Constraint Satisfaction
# ---------------------------------------------------------------------------

class TestConstraintSatisfaction:

    def test_from_rest(self, sim_binary, tmp_path):
        data = _run_sim(sim_binary,
                        -np.pi / 3, -np.pi / 4, 0, 0,
                        0.9, 0.001, 1.0, str(tmp_path / "out.csv"))
        assert np.max(data[:, COL_CVIOL]) < 1e-6, (
            f"Max constraint violation {np.max(data[:, COL_CVIOL]):.2e}"
        )

    def test_with_initial_velocity(self, sim_binary, tmp_path):
        data = _run_sim(sim_binary,
                        -np.pi / 4, -np.pi / 3, 1.0, -0.5,
                        0.9, 0.001, 0.5, str(tmp_path / "out.csv"))
        assert np.max(data[:, COL_CVIOL]) < 1e-6, (
            f"Max constraint violation {np.max(data[:, COL_CVIOL]):.2e}"
        )


# ---------------------------------------------------------------------------
# Tests: Energy Behavior
# ---------------------------------------------------------------------------

class TestEnergyBehavior:

    def test_conservation_rho1(self, sim_binary, tmp_path):
        """rho_inf = 1  =>  near-zero energy drift."""
        data = _run_sim(sim_binary,
                        -np.pi / 2 + 0.3, -np.pi / 2 + 0.2, 0, 0,
                        1.0, 0.001, 2.0, str(tmp_path / "out.csv"))
        E = data[:, COL_ENERGY]
        drift = np.max(np.abs(E - E[0])) / abs(E[0])
        assert drift < 0.01, f"Energy drift {drift:.4e} exceeds 1%"

    def test_dissipation_rho05(self, sim_binary, tmp_path):
        """rho_inf < 1  =>  energy must decrease."""
        data = _run_sim(sim_binary,
                        -np.pi / 3, -np.pi / 4, 0, 0,
                        0.5, 0.001, 1.0, str(tmp_path / "out.csv"))
        E = data[:, COL_ENERGY]
        assert E[-1] < E[0], (
            f"Energy did not decrease: start={E[0]:.6f} end={E[-1]:.6f}"
        )


# ---------------------------------------------------------------------------
# Tests: Trajectory Accuracy vs Reference
# ---------------------------------------------------------------------------

class TestTrajectoryAccuracy:

    def test_against_reference(self, sim_binary, tmp_path):
        th1, th2 = -np.pi / 2 + 0.3, -np.pi / 2 + 0.2
        t_end = 1.0

        sim = _run_sim(sim_binary, th1, th2, 0, 0,
                       0.9, 0.001, t_end, str(tmp_path / "sim.csv"))
        ref = _run_ref(th1, th2, 0, 0, t_end,
                       str(tmp_path / "ref.csv"))

        err1 = abs(sim[-1, COL_THETA1] - ref[-1, REF_THETA1])
        err2 = abs(sim[-1, COL_THETA2] - ref[-1, REF_THETA2])
        assert err1 < 0.01, f"theta1 error {err1:.2e}"
        assert err2 < 0.01, f"theta2 error {err2:.2e}"


# ---------------------------------------------------------------------------
# Tests: Second-Order Convergence
# ---------------------------------------------------------------------------

class TestConvergenceOrder:

    def test_second_order(self, sim_binary, tmp_path):
        th1 = -np.pi / 2 + 0.2
        th2 = -np.pi / 2 + 0.1
        t_end = 0.5

        ref = _run_ref(th1, th2, 0, 0, t_end,
                       str(tmp_path / "ref.csv"))
        theta1_ref = ref[-1, REF_THETA1]

        coarse = _run_sim(sim_binary, th1, th2, 0, 0,
                          0.9, 0.01, t_end,
                          str(tmp_path / "coarse.csv"))
        fine = _run_sim(sim_binary, th1, th2, 0, 0,
                        0.9, 0.005, t_end,
                        str(tmp_path / "fine.csv"))

        err_c = abs(coarse[-1, COL_THETA1] - theta1_ref)
        err_f = abs(fine[-1, COL_THETA1] - theta1_ref)

        assert err_f > 1e-14, "Fine error too small for ratio test"
        ratio = err_c / err_f
        assert 2.5 < ratio < 6.0, (
            f"Convergence ratio {ratio:.2f} outside [2.5, 6.0] "
            f"(err_coarse={err_c:.2e}, err_fine={err_f:.2e})"
        )


# ---------------------------------------------------------------------------
# Tests: Full rho_inf Range
# ---------------------------------------------------------------------------

class TestSpectralRadiusRange:

    @pytest.mark.parametrize("rho", [0.0, 0.3, 0.5, 0.8, 0.9, 1.0])
    def test_rho(self, sim_binary, rho, tmp_path):
        data = _run_sim(sim_binary,
                        -np.pi / 2 + 0.2, -np.pi / 2 + 0.1, 0, 0,
                        rho, 0.001, 0.2,
                        str(tmp_path / f"rho{rho}.csv"))
        assert np.max(data[:, COL_CVIOL]) < 1e-5, (
            f"rho_inf={rho}: violation {np.max(data[:, COL_CVIOL]):.2e}"
        )
