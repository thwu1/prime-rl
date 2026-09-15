
import os
import subprocess
import pytest
import numpy as np

N = 100
NTOTAL = N * N * N
H = 1.0 / (N + 1)


def parse_results():
    results = {}
    with open("/app/results.txt") as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                key, val = line.split("=", 1)
                results[key.strip()] = val.strip()
    return results


def parse_profile_report():
    metrics = {}
    with open("/app/profile_report.txt") as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                key, val = line.split("=", 1)
                metrics[key.strip()] = val.strip()
    return metrics


class TestBuildSystem:
    def test_cmakelists_exists(self):
        assert os.path.exists("/app/CMakeLists.txt"), \
            "CMakeLists.txt not found at /app/"

    def test_cmake_out_of_source_build(self):
        assert os.path.exists("/app/build/CMakeCache.txt"), \
            "Out-of-source CMake build not found at /app/build/"

    def test_cmake_configured_openmp(self):
        """CMakeCache.txt must show OpenMP was discovered and configured."""
        content = open("/app/build/CMakeCache.txt").read()
        lower = content.lower()
        assert "openmp" in lower or "fopenmp" in lower, \
            "CMake cache does not reference OpenMP configuration"

    def test_binary_links_libgomp(self):
        """fast_poisson must dynamically link against libgomp (GCC OpenMP runtime)."""
        binary = "/app/build/fast_poisson"
        assert os.path.exists(binary), f"Binary not found at {binary}"
        result = subprocess.run(["ldd", binary], capture_output=True, text=True)
        assert "libgomp" in result.stdout, \
            "fast_poisson does not link against libgomp (OpenMP runtime). " \
            "ldd output:\n" + result.stdout


class TestProfileReport:
    def test_profile_report_exists(self):
        assert os.path.exists("/app/profile_report.txt"), \
            "profile_report.txt not found at /app/"

    def test_d1_miss_rate(self):
        metrics = parse_profile_report()
        assert "D1_miss_rate" in metrics, \
            "Missing D1_miss_rate in profile_report.txt"
        d1 = float(metrics["D1_miss_rate"])
        assert 0.0 <= d1 <= 100.0, \
            f"D1_miss_rate={d1} out of valid percentage range [0, 100]"

    def test_dl_miss_rate(self):
        metrics = parse_profile_report()
        assert "DLmiss_rate" in metrics, \
            "Missing DLmiss_rate in profile_report.txt"
        dl = float(metrics["DLmiss_rate"])
        assert 0.0 <= dl <= 100.0, \
            f"DLmiss_rate={dl} out of valid percentage range [0, 100]"

    def test_total_instructions(self):
        metrics = parse_profile_report()
        assert "total_instructions" in metrics, \
            "Missing total_instructions in profile_report.txt"
        total = int(metrics["total_instructions"])
        assert total > 0, \
            f"total_instructions={total} must be positive"


class TestOutputFiles:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.txt"), "results.txt was not created"

    def test_solution_file_exists(self):
        assert os.path.exists("/app/solution.bin"), "solution.bin was not created"

    def test_solution_file_size(self):
        size = os.path.getsize("/app/solution.bin")
        expected = NTOTAL * 8
        assert size == expected, \
            f"solution.bin size {size} != expected {expected} bytes"


class TestConvergenceCriteria:
    def test_iteration_count(self):
        results = parse_results()
        iters = int(results["iterations"])
        assert 0 < iters <= 200, f"iterations={iters}, must be in (0, 200]"

    def test_relative_residual(self):
        results = parse_results()
        res = float(results["relative_residual"])
        assert res < 1e-10, f"relative_residual={res:.2e}, must be < 1e-10"

    def test_reported_max_error(self):
        results = parse_results()
        err = float(results["max_error"])
        assert err < 5e-3, f"max_error={err:.6e}, must be < 5e-3"

    def test_grid_size(self):
        results = parse_results()
        grid_n = int(results["grid_n"])
        assert grid_n == N, f"grid_n={grid_n}, expected {N}"


class TestSolutionAccuracy:
    def test_independent_error_check(self):
        """Verify solution accuracy against the exact manufactured solution
        u(x,y,z) = x(1-x)*y(1-y)*z(1-z)."""
        solution = np.fromfile("/app/solution.bin", dtype=np.float64)
        assert solution.size == NTOTAL, \
            f"Wrong solution vector length: {solution.size}"

        coords = np.arange(1, N + 1) * H
        t = coords * (1.0 - coords)
        exact = (
            t[:, None, None] * t[None, :, None] * t[None, None, :]
        ).ravel(order="F")

        max_err = np.max(np.abs(solution - exact))
        assert max_err < 5e-3, (
            f"Independent error check failed: max_err={max_err:.6e} >= 5e-3"
        )

    def test_solution_satisfies_linear_system(self):
        """Verify the solution satisfies Au ~ b (catches hardcoded exact solutions)."""
        solution = np.fromfile("/app/solution.bin", dtype=np.float64)
        u = solution.reshape((N, N, N), order="F")

        h2inv = float((N + 1) ** 2)

        Au = 6.0 * h2inv * u.copy()
        Au[1:, :, :] -= h2inv * u[:-1, :, :]
        Au[:-1, :, :] -= h2inv * u[1:, :, :]
        Au[:, 1:, :] -= h2inv * u[:, :-1, :]
        Au[:, :-1, :] -= h2inv * u[:, 1:, :]
        Au[:, :, 1:] -= h2inv * u[:, :, :-1]
        Au[:, :, :-1] -= h2inv * u[:, :, 1:]

        coords = np.arange(1, N + 1) * H
        t = coords * (1.0 - coords)
        b = 2.0 * (
            t[None, :, None] * t[None, None, :]
            + t[:, None, None] * t[None, None, :]
            + t[:, None, None] * t[None, :, None]
        )

        rel_residual = np.linalg.norm(
            Au.ravel(order="F") - b.ravel(order="F")
        ) / np.linalg.norm(b.ravel(order="F"))
        assert rel_residual < 1e-6, (
            f"Solution does not satisfy the linear system: "
            f"||Au - b|| / ||b|| = {rel_residual:.2e} >= 1e-6"
        )
