
"""
Tests for FDS heat conduction verification framework.

Verifies:
1. verify.py exists and runs successfully
2. verification_report.json is well-formed
3. Eigenvalues are computed correctly
4. Analytical solution values match reference
5. PASS/FAIL classification is correct
6. Gnuplot verification plots are generated
"""

import json
import math
import os
import subprocess
import pytest


# ---------------------------------------------------------------------------
# Reference eigenvalue computation (independent implementation)
# ---------------------------------------------------------------------------

def _solve_eigenvalues_reference(Bi, N=100):
    """Solve beta*tan(beta) = Bi via bisection (reference implementation)."""
    roots = []
    for n in range(1, N + 1):
        if n == 1:
            a, b = 1e-12, math.pi / 2 - 1e-12
        else:
            a = (n - 1) * math.pi + 1e-12
            b = (n - 1) * math.pi + math.pi / 2 - 1e-12

        def f(beta):
            return beta * math.tan(beta) - Bi

        fa = f(a)
        for _ in range(300):
            mid = (a + b) / 2
            fm = f(mid)
            if abs(fm) < 1e-15 or (b - a) < 1e-15:
                break
            if fa * fm < 0:
                b = mid
            else:
                a = mid
                fa = f(a)
        roots.append((a + b) / 2)
    return roots


def _analytical_temperature(x, t, T_inf, T_i, L, alpha, eigenvalues):
    """Compute analytical temperature at (x, t)."""
    if t <= 0:
        return T_i
    Fo = alpha * t / (L * L)
    s = 0.0
    for bn in eigenvalues:
        Cn = 4 * math.sin(bn) / (2 * bn + math.sin(2 * bn))
        s += Cn * math.cos(bn * x / L) * math.exp(-(bn ** 2) * Fo)
    return T_inf + (T_i - T_inf) * s


# ---------------------------------------------------------------------------
# Known reference values
# ---------------------------------------------------------------------------

CASES = {
    "case_a": {"Bi": 100.0, "k": 0.1, "rho": 100, "cp": 1000.0, "h": 100.0},
    "case_b": {"Bi": 10.0, "k": 0.1, "rho": 100, "cp": 1000.0, "h": 10.0},
    "case_c": {"Bi": 1.0, "k": 1.0, "rho": 1000, "cp": 1000.0, "h": 10.0},
    "case_d": {"Bi": 0.1, "k": 10.0, "rho": 10000, "cp": 1000.0, "h": 10.0},
}

T_INF = 120.0
T_I = 20.0
L = 0.1

EXPECTED_STATUS = {
    "case_a": "PASS",
    "case_b": "PASS",
    "case_c": "FAIL",
    "case_d": "FAIL",
}

# Reference first-5 eigenvalues for each Biot number
REFERENCE_EIGENVALUES = {}
for cname, cp in CASES.items():
    REFERENCE_EIGENVALUES[cname] = _solve_eigenvalues_reference(cp["Bi"], 100)[:5]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def run_verify():
    """Run verify.py once and return the report."""
    result = subprocess.run(
        ["python3", "/app/verify.py"],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=120,
    )
    assert result.returncode == 0, (
        f"verify.py failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    report_path = "/app/verification_report.json"
    assert os.path.exists(report_path), "verification_report.json not found"
    with open(report_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVerifyScript:
    """verify.py exists and is executable."""

    def test_verify_exists(self):
        assert os.path.isfile("/app/verify.py"), "verify.py not found at /app/verify.py"


class TestReportStructure:
    """verification_report.json has the required structure."""

    def test_top_level_keys(self, run_verify):
        report = run_verify
        for key in ("cases", "tolerance", "overall_status", "pass_count", "fail_count"):
            assert key in report, f"Missing top-level key: {key}"

    def test_all_cases_present(self, run_verify):
        report = run_verify
        for case_name in CASES:
            assert case_name in report["cases"], f"Missing case: {case_name}"

    def test_case_keys(self, run_verify):
        report = run_verify
        for case_name in CASES:
            case = report["cases"][case_name]
            for key in ("biot_number", "eigenvalues", "max_absolute_error",
                        "max_relative_error", "status", "device_errors"):
                assert key in case, f"Missing key '{key}' in {case_name}"

    def test_eigenvalue_count(self, run_verify):
        report = run_verify
        for case_name in CASES:
            evs = report["cases"][case_name]["eigenvalues"]
            assert isinstance(evs, list), f"eigenvalues should be a list in {case_name}"
            assert len(evs) >= 5, f"Need at least 5 eigenvalues in {case_name}"


class TestBiotNumbers:
    """Biot numbers are correctly computed."""

    @pytest.mark.parametrize("case_name", list(CASES.keys()))
    def test_biot_number(self, run_verify, case_name):
        report = run_verify
        expected_bi = CASES[case_name]["Bi"]
        reported_bi = report["cases"][case_name]["biot_number"]
        assert abs(reported_bi - expected_bi) < 0.01, (
            f"{case_name}: Bi={reported_bi}, expected {expected_bi}"
        )


class TestEigenvalues:
    """Eigenvalues are computed accurately."""

    @pytest.mark.parametrize("case_name", list(CASES.keys()))
    def test_first_five_eigenvalues(self, run_verify, case_name):
        report = run_verify
        reported = report["cases"][case_name]["eigenvalues"][:5]
        reference = REFERENCE_EIGENVALUES[case_name]
        for i, (rep, ref) in enumerate(zip(reported, reference)):
            assert abs(rep - ref) < 1e-4, (
                f"{case_name} eigenvalue {i+1}: got {rep}, expected {ref}"
            )

    def test_eigenvalue_equation_satisfied(self, run_verify):
        """Each reported eigenvalue should satisfy beta*tan(beta)=Bi."""
        report = run_verify
        for case_name in CASES:
            Bi = CASES[case_name]["Bi"]
            evs = report["cases"][case_name]["eigenvalues"][:5]
            for i, beta in enumerate(evs):
                residual = abs(beta * math.tan(beta) - Bi)
                assert residual < 1e-3, (
                    f"{case_name} eigenvalue {i+1}: beta={beta}, "
                    f"beta*tan(beta)={beta * math.tan(beta):.6f}, Bi={Bi}, "
                    f"residual={residual}"
                )


class TestAnalyticalSolution:
    """The analytical solution matches independent reference values."""

    @pytest.mark.parametrize("case_name,t,x_frac,expected_T", [
        # Case A: high Bi, reference from Carslaw & Jaeger / FDS verification guide
        ("case_a", 1.0, 1.0, 77.24),     # front face at t=1
        ("case_a", 10.0, 1.0, 102.94),    # front face at t=10
        ("case_a", 1000.0, 0.0, 24.79),   # back wall at t=1000
        ("case_a", 2000.0, 1.0, 118.75),  # front face at t=2000
        # Case B: medium Bi
        ("case_b", 100.0, 1.0, 77.24),    # front face at t=100
        ("case_b", 2000.0, 0.0, 37.07),   # back wall at t=2000
        # Case D: low Bi
        ("case_d", 10000.0, 0.0, 27.76),  # back wall at t=10000
        ("case_d", 50000.0, 1.0, 60.37),  # front face at t=50000
    ])
    def test_analytical_reference_points(self, case_name, t, x_frac, expected_T):
        """Independent check of analytical solution at reference points."""
        params = CASES[case_name]
        alpha = params["k"] / (params["rho"] * params["cp"])
        evs = _solve_eigenvalues_reference(params["Bi"], 100)
        x = x_frac * L
        T_computed = _analytical_temperature(x, t, T_INF, T_I, L, alpha, evs)
        assert abs(T_computed - expected_T) < 0.1, (
            f"{case_name}: T(x={x}, t={t}) = {T_computed:.4f}, expected {expected_T}"
        )


class TestPassFailClassification:
    """Cases A,B should PASS; cases C,D should FAIL."""

    @pytest.mark.parametrize("case_name", list(CASES.keys()))
    def test_status(self, run_verify, case_name):
        report = run_verify
        status = report["cases"][case_name]["status"]
        expected = EXPECTED_STATUS[case_name]
        assert status == expected, (
            f"{case_name}: status={status}, expected {expected}"
        )

    def test_pass_count(self, run_verify):
        assert run_verify["pass_count"] == 2

    def test_fail_count(self, run_verify):
        assert run_verify["fail_count"] == 2

    def test_overall_fail(self, run_verify):
        assert run_verify["overall_status"] == "FAIL"


class TestErrorMetrics:
    """Error metrics are physically reasonable."""

    def test_passing_cases_low_error(self, run_verify):
        """Cases A and B should have very low max relative error."""
        for case_name in ("case_a", "case_b"):
            mre = run_verify["cases"][case_name]["max_relative_error"]
            assert mre < 0.02, (
                f"{case_name} max_relative_error={mre}, should be < 0.02 for passing"
            )

    def test_failing_cases_high_error(self, run_verify):
        """Cases C and D should have significant errors."""
        for case_name in ("case_c", "case_d"):
            mae = run_verify["cases"][case_name]["max_absolute_error"]
            assert mae > 2.0, (
                f"{case_name} max_absolute_error={mae}, should be > 2.0 for failing"
            )

    def test_device_errors_present(self, run_verify):
        """Each case should have per-device error breakdown."""
        for case_name in CASES:
            de = run_verify["cases"][case_name]["device_errors"]
            assert isinstance(de, dict), f"device_errors should be dict in {case_name}"
            assert len(de) >= 5, (
                f"Expected at least 5 device entries in {case_name}, got {len(de)}"
            )


class TestVerificationPlots:
    """Gnuplot verification plots are generated for each case."""

    @pytest.mark.parametrize("case_name", list(CASES.keys()))
    def test_plot_file_exists(self, run_verify, case_name):
        plot_path = f"/app/plots/{case_name}.png"
        assert os.path.isfile(plot_path), f"Plot not found: {plot_path}"

    @pytest.mark.parametrize("case_name", list(CASES.keys()))
    def test_plot_is_valid_png(self, run_verify, case_name):
        plot_path = f"/app/plots/{case_name}.png"
        size = os.path.getsize(plot_path)
        assert size > 1000, f"Plot file too small ({size} bytes): {plot_path}"
        with open(plot_path, 'rb') as f:
            magic = f.read(4)
        assert magic == b'\x89PNG', f"Not a valid PNG file: {plot_path}"

    @pytest.mark.parametrize("case_name", list(CASES.keys()))
    def test_plot_has_reasonable_size(self, run_verify, case_name):
        """A proper multi-series plot should be at least 10KB."""
        plot_path = f"/app/plots/{case_name}.png"
        size = os.path.getsize(plot_path)
        assert size > 10000, (
            f"Plot suspiciously small ({size} bytes), likely missing data series: {plot_path}"
        )
