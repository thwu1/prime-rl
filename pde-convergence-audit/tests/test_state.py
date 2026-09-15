
import ctypes
import json
import math
import os
import subprocess

import pytest

EXPECTED = {
    "poisson_5pt": {"order": 2.0, "tol": 0.35, "max_err": 5e-3},
    "poisson_compact": {"order": 4.0, "tol": 0.8, "max_err": 1e-4},
    "heat_cn": {"order": 2.0, "tol": 0.35, "max_err": 5e-3},
    "advection_lw": {"order": 2.0, "tol": 0.35, "max_err": 5e-2},
}


# -- C kernel library tests ---------------------------------------------------


class TestCKernels:
    def test_shared_library_exists(self):
        assert os.path.exists("/app/libpde_kernels.so"), (
            "C kernel shared library libpde_kernels.so not found in /app/"
        )

    def test_shared_library_loadable(self):
        lib = ctypes.CDLL("/app/libpde_kernels.so")
        assert lib is not None, "Failed to load libpde_kernels.so"

    def test_thomas_solve_symbol(self):
        lib = ctypes.CDLL("/app/libpde_kernels.so")
        fn = getattr(lib, "thomas_solve", None)
        assert fn is not None, "thomas_solve symbol not found in shared library"

    def test_lax_wendroff_step_symbol(self):
        lib = ctypes.CDLL("/app/libpde_kernels.so")
        fn = getattr(lib, "lax_wendroff_step", None)
        assert fn is not None, "lax_wendroff_step symbol not found in shared library"

    def test_compute_rms_error_symbol(self):
        lib = ctypes.CDLL("/app/libpde_kernels.so")
        fn = getattr(lib, "compute_rms_error", None)
        assert fn is not None, "compute_rms_error symbol not found in shared library"


# -- Benchmark results --------------------------------------------------------


@pytest.fixture(scope="module")
def results():
    """Run the benchmark driver and load results."""
    result = subprocess.run(
        ["python3", "/app/run_benchmark.py"],
        capture_output=True,
        text=True,
        timeout=600,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"run_benchmark.py failed (exit {result.returncode}):\n"
        f"STDOUT:\n{result.stdout[:2000]}\n"
        f"STDERR:\n{result.stderr[:2000]}"
    )
    assert os.path.exists("/app/results.json"), "results.json was not created"
    with open("/app/results.json") as f:
        data = json.load(f)
    return data


# -- Structure tests ----------------------------------------------------------


class TestStructure:
    def test_all_problem_keys_present(self, results):
        for key in EXPECTED:
            assert key in results, f"Missing problem key '{key}' in results.json"

    def test_resolutions_field(self, results):
        for key in EXPECTED:
            d = results[key]
            assert "resolutions" in d, f"{key}: missing 'resolutions'"
            assert isinstance(d["resolutions"], list)
            assert len(d["resolutions"]) >= 4, f"{key}: need >= 4 resolutions"

    def test_l2_errors_field(self, results):
        for key in EXPECTED:
            d = results[key]
            assert "l2_errors" in d, f"{key}: missing 'l2_errors'"
            assert isinstance(d["l2_errors"], list)
            assert len(d["l2_errors"]) == len(d["resolutions"]), (
                f"{key}: l2_errors length mismatch"
            )

    def test_errors_are_positive_floats(self, results):
        for key in EXPECTED:
            for i, e in enumerate(results[key]["l2_errors"]):
                assert isinstance(e, (int, float)), (
                    f"{key}: l2_errors[{i}] is not numeric"
                )
                assert e > 0, f"{key}: l2_errors[{i}] = {e} <= 0"


# -- Convergence tests --------------------------------------------------------


def _compute_orders(errors):
    """Compute observed convergence orders from consecutive error pairs."""
    orders = []
    for i in range(len(errors) - 1):
        if errors[i] > 0 and errors[i + 1] > 0:
            orders.append(math.log(errors[i] / errors[i + 1]) / math.log(2))
    return orders


class TestConvergence:
    def test_errors_monotone_decreasing(self, results):
        for key in EXPECTED:
            errors = results[key]["l2_errors"]
            for i in range(len(errors) - 1):
                assert errors[i] > errors[i + 1], (
                    f"{key}: errors not decreasing at index {i}: "
                    f"{errors[i]:.3e} vs {errors[i+1]:.3e}"
                )

    def test_convergence_order_poisson_5pt(self, results):
        errors = results["poisson_5pt"]["l2_errors"]
        orders = _compute_orders(errors)
        assert len(orders) >= 2
        avg = sum(orders[-2:]) / 2.0
        exp = EXPECTED["poisson_5pt"]
        assert abs(avg - exp["order"]) < exp["tol"], (
            f"poisson_5pt: observed order {avg:.2f}, "
            f"expected {exp['order']}+/-{exp['tol']}"
        )

    def test_convergence_order_poisson_compact(self, results):
        errors = results["poisson_compact"]["l2_errors"]
        orders = _compute_orders(errors)
        assert len(orders) >= 2
        avg = sum(orders[-2:]) / 2.0
        exp = EXPECTED["poisson_compact"]
        assert abs(avg - exp["order"]) < exp["tol"], (
            f"poisson_compact: observed order {avg:.2f}, "
            f"expected {exp['order']}+/-{exp['tol']}"
        )

    def test_convergence_order_heat_cn(self, results):
        errors = results["heat_cn"]["l2_errors"]
        orders = _compute_orders(errors)
        assert len(orders) >= 2
        avg = sum(orders[-2:]) / 2.0
        exp = EXPECTED["heat_cn"]
        assert abs(avg - exp["order"]) < exp["tol"], (
            f"heat_cn: observed order {avg:.2f}, "
            f"expected {exp['order']}+/-{exp['tol']}"
        )

    def test_convergence_order_advection_lw(self, results):
        errors = results["advection_lw"]["l2_errors"]
        orders = _compute_orders(errors)
        assert len(orders) >= 2
        avg = sum(orders[-2:]) / 2.0
        exp = EXPECTED["advection_lw"]
        assert abs(avg - exp["order"]) < exp["tol"], (
            f"advection_lw: observed order {avg:.2f}, "
            f"expected {exp['order']}+/-{exp['tol']}"
        )

    def test_finest_error_poisson_5pt(self, results):
        e = results["poisson_5pt"]["l2_errors"][-1]
        assert e < EXPECTED["poisson_5pt"]["max_err"], (
            f"poisson_5pt finest error {e:.2e} too large"
        )

    def test_finest_error_poisson_compact(self, results):
        e = results["poisson_compact"]["l2_errors"][-1]
        assert e < EXPECTED["poisson_compact"]["max_err"], (
            f"poisson_compact finest error {e:.2e} too large"
        )

    def test_finest_error_heat_cn(self, results):
        e = results["heat_cn"]["l2_errors"][-1]
        assert e < EXPECTED["heat_cn"]["max_err"], (
            f"heat_cn finest error {e:.2e} too large"
        )

    def test_finest_error_advection_lw(self, results):
        e = results["advection_lw"]["l2_errors"][-1]
        assert e < EXPECTED["advection_lw"]["max_err"], (
            f"advection_lw finest error {e:.2e} too large"
        )

    def test_compact_much_better_than_5pt(self, results):
        """4th-order scheme must be significantly more accurate at finest grid."""
        e5 = results["poisson_5pt"]["l2_errors"][-1]
        e9 = results["poisson_compact"]["l2_errors"][-1]
        assert e9 < e5 / 10.0, (
            f"Compact error ({e9:.2e}) should be << 5-point error ({e5:.2e})"
        )
