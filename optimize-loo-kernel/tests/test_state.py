"""
"""
import json
import os
import subprocess
import time

import numpy as np
import pytest

# ── Constants (must match the C++ program) ──────────────────────────────────
SEED = 42
N = 100_000
P = 5
LAMBDA_VAL = 0.01
ALPHA_VAL = 0.5
BETA_TRUE = np.array([1.5, -2.0, 0.5, 3.0, -1.0])
NOISE_STD = 0.5
TIME_LIMIT = 60.0
REL_TOL = 1e-4


# ── Helpers ─────────────────────────────────────────────────────────────────
def generate_dataset():
    """Create a deterministic synthetic dataset and write it to CSV."""
    rng = np.random.default_rng(SEED)
    X = rng.standard_normal((N, P))
    noise = rng.standard_normal(N) * NOISE_STD
    y = X @ BETA_TRUE + noise
    timestamps = np.sort(rng.uniform(0.0, 10.0, N))
    weights = np.abs(rng.standard_normal(N)) + 0.1

    os.makedirs("/app/data", exist_ok=True)
    with open("/app/data/input.csv", "w") as f:
        f.write("f0,f1,f2,f3,f4,timestamp,weight,target\n")
        for i in range(N):
            vals = [f"{X[i, j]:.17g}" for j in range(P)]
            vals.append(f"{timestamps[i]:.17g}")
            vals.append(f"{weights[i]:.17g}")
            vals.append(f"{y[i]:.17g}")
            f.write(",".join(vals) + "\n")

    return X, y, timestamps, weights


def compute_reference_loo(X, y):
    """LOO RMSE and MAE via the PRESS / hat-matrix formula (O(N P^2))."""
    A = X.T @ X + LAMBDA_VAL * np.eye(P)
    Ainv = np.linalg.inv(A)
    beta = Ainv @ (X.T @ y)

    residuals = y - X @ beta
    XAinv = X @ Ainv                          # N x P
    H_diag = np.sum(XAinv * X, axis=1)        # hat-matrix diagonal
    loo_residuals = residuals / (1.0 - H_diag)

    rmse = float(np.sqrt(np.mean(loo_residuals ** 2)))
    mae = float(np.mean(np.abs(loo_residuals)))
    return rmse, mae


def compute_reference_kernel(timestamps, weights):
    """Pairwise kernel sum via O(N) suffix-sum reduction."""
    n = len(timestamps)
    cumrev = np.cumsum(weights[::-1])[::-1]
    suffix_after = np.empty(n)
    suffix_after[:-1] = cumrev[1:]
    suffix_after[-1] = 0.0

    g = np.exp(-ALPHA_VAL * timestamps)
    S = float(np.sum(g * weights * (2.0 * suffix_after + weights)))
    return S


# ── Fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def reference_values():
    """Generate dataset and compute reference answers."""
    X, y, timestamps, weights = generate_dataset()
    ref_rmse, ref_mae = compute_reference_loo(X, y)
    ref_kernel = compute_reference_kernel(timestamps, weights)
    return ref_rmse, ref_mae, ref_kernel


@pytest.fixture(scope="session")
def program_output(reference_values):
    """Run the analytics program (assuming it was already built by the agent)."""
    binary = "/app/analytics"
    assert os.path.exists(binary), (
        f"Binary not found at {binary}. "
        "The CMake build must produce an executable named 'analytics' at /app/analytics."
    )

    os.makedirs("/app/output", exist_ok=True)

    start = time.monotonic()
    try:
        result = subprocess.run(
            [binary],
            capture_output=True, text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Program exceeded the 120-second hard timeout")

    elapsed = time.monotonic() - start

    assert result.returncode == 0, (
        f"Program exited with code {result.returncode}:\n{result.stderr}"
    )

    output_path = "/app/output/results.json"
    assert os.path.exists(output_path), "Output file /app/output/results.json not found"

    with open(output_path) as f:
        results = json.load(f)

    results["_wall_time"] = elapsed
    return results


# ── Tests: Correctness ─────────────────────────────────────────────────────
class TestCorrectness:
    """Verify that program output matches reference values."""

    def test_loo_rmse(self, reference_values, program_output):
        ref = reference_values[0]
        got = program_output["loo_rmse"]
        rel_err = abs(got - ref) / abs(ref)
        assert rel_err < REL_TOL, (
            f"LOO RMSE relative error {rel_err:.2e} >= {REL_TOL}: "
            f"got {got:.10g}, expected {ref:.10g}"
        )

    def test_loo_mae(self, reference_values, program_output):
        ref = reference_values[1]
        got = program_output["loo_mae"]
        rel_err = abs(got - ref) / abs(ref)
        assert rel_err < REL_TOL, (
            f"LOO MAE relative error {rel_err:.2e} >= {REL_TOL}: "
            f"got {got:.10g}, expected {ref:.10g}"
        )

    def test_kernel_sum(self, reference_values, program_output):
        ref = reference_values[2]
        got = program_output["kernel_sum"]
        rel_err = abs(got - ref) / abs(ref)
        assert rel_err < REL_TOL, (
            f"Kernel sum relative error {rel_err:.2e} >= {REL_TOL}: "
            f"got {got:.10g}, expected {ref:.10g}"
        )


# ── Tests: Performance ─────────────────────────────────────────────────────
class TestPerformance:
    """Verify the program meets the wall-clock time budget."""

    def test_time_limit(self, program_output):
        elapsed = program_output["_wall_time"]
        assert elapsed < TIME_LIMIT, (
            f"Program took {elapsed:.1f}s, limit is {TIME_LIMIT}s"
        )


# ── Tests: Profiling Report ────────────────────────────────────────────────
class TestProfilingReport:
    """Verify the cachegrind profiling comparison report."""

    REPORT_PATH = "/app/output/profile_report.json"
    REQUIRED_KEYS = ["I_refs", "D_refs", "D1_misses", "LLd_misses"]

    def test_report_exists(self):
        assert os.path.exists(self.REPORT_PATH), (
            f"Profiling report not found at {self.REPORT_PATH}. "
            "Must profile both naive and optimized implementations with "
            "valgrind --tool=cachegrind and generate a structured JSON report."
        )

    def test_report_structure(self):
        with open(self.REPORT_PATH) as f:
            report = json.load(f)

        assert "naive" in report, "Report missing 'naive' section"
        assert "optimized" in report, "Report missing 'optimized' section"

        for section_name in ["naive", "optimized"]:
            section = report[section_name]
            for key in self.REQUIRED_KEYS:
                assert key in section, (
                    f"Report section '{section_name}' missing key '{key}'"
                )
                val = section[key]
                assert isinstance(val, (int, float)), (
                    f"Report['{section_name}']['{key}'] must be numeric, "
                    f"got {type(val).__name__}: {val}"
                )
                assert val > 0, (
                    f"Report['{section_name}']['{key}'] must be positive, got {val}"
                )

    def test_optimization_improves_metrics(self):
        with open(self.REPORT_PATH) as f:
            report = json.load(f)

        naive_irefs = report["naive"]["I_refs"]
        opt_irefs = report["optimized"]["I_refs"]
        assert opt_irefs < naive_irefs, (
            f"Optimized I_refs ({opt_irefs:,}) should be less than naive ({naive_irefs:,}). "
            "The O(N^2)->O(N) algorithmic improvement must show in cachegrind instruction counts."
        )
