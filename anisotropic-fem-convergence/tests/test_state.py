"""
Verify finite element convergence results for anisotropic Helmholtz equation.

"""
import json
import os
import pytest
import numpy as np


RESULTS_PATH = "/app/results.json"


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), \
        f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestResultsStructure:
    """Verify results.json has the required structure."""

    def test_has_p1(self, results):
        assert "p1" in results, "Missing 'p1' key in results"

    def test_has_p2(self, results):
        assert "p2" in results, "Missing 'p2' key in results"

    def test_p1_fields(self, results):
        for field in ["mesh_sizes", "errors", "convergence_rate"]:
            assert field in results["p1"], f"p1 missing '{field}'"

    def test_p2_fields(self, results):
        for field in ["mesh_sizes", "errors", "convergence_rate"]:
            assert field in results["p2"], f"p2 missing '{field}'"

    def test_mesh_sizes_p1(self, results):
        assert results["p1"]["mesh_sizes"] == [4, 8, 16, 32]

    def test_mesh_sizes_p2(self, results):
        assert results["p2"]["mesh_sizes"] == [4, 8, 16, 32]

    def test_p1_error_count(self, results):
        assert len(results["p1"]["errors"]) == 4

    def test_p2_error_count(self, results):
        assert len(results["p2"]["errors"]) == 4


class TestErrorValues:
    """Verify error values are physically reasonable."""

    def test_p1_errors_positive(self, results):
        for i, e in enumerate(results["p1"]["errors"]):
            assert e > 0, f"P1 error[{i}] must be positive, got {e}"

    def test_p2_errors_positive(self, results):
        for i, e in enumerate(results["p2"]["errors"]):
            assert e > 0, f"P2 error[{i}] must be positive, got {e}"

    def test_p1_errors_decreasing(self, results):
        errors = results["p1"]["errors"]
        for i in range(len(errors) - 1):
            assert errors[i] > errors[i + 1], \
                f"P1 errors not decreasing: e[{i}]={errors[i]} >= e[{i+1}]={errors[i+1]}"

    def test_p2_errors_decreasing(self, results):
        errors = results["p2"]["errors"]
        for i in range(len(errors) - 1):
            assert errors[i] > errors[i + 1], \
                f"P2 errors not decreasing: e[{i}]={errors[i]} >= e[{i+1}]={errors[i+1]}"

    def test_p1_coarsest_error_reasonable(self, results):
        e = results["p1"]["errors"][0]
        assert e < 1.0, f"P1 coarsest error implausibly large: {e}"

    def test_p2_coarsest_error_reasonable(self, results):
        e = results["p2"]["errors"][0]
        assert e < 0.5, f"P2 coarsest error implausibly large: {e}"

    def test_p1_finest_error_small(self, results):
        e = results["p1"]["errors"][-1]
        assert e < 0.01, f"P1 finest mesh error too large: {e}"

    def test_p2_finest_error_small(self, results):
        e = results["p2"]["errors"][-1]
        assert e < 0.001, f"P2 finest mesh error too large: {e}"

    def test_p2_more_accurate_than_p1(self, results):
        p1_fine = results["p1"]["errors"][-1]
        p2_fine = results["p2"]["errors"][-1]
        assert p2_fine < p1_fine, \
            f"P2 should be more accurate than P1 on finest mesh: {p2_fine} >= {p1_fine}"


class TestConvergenceRates:
    """Verify convergence rates match finite element theory."""

    def test_p1_convergence_rate(self, results):
        rate = results["p1"]["convergence_rate"]
        assert 1.7 <= rate <= 2.5, \
            f"P1 convergence rate should be ~2.0 (O(h^2)), got {rate:.4f}"

    def test_p2_convergence_rate(self, results):
        rate = results["p2"]["convergence_rate"]
        assert 2.5 <= rate <= 3.8, \
            f"P2 convergence rate should be ~3.0 (O(h^3)), got {rate:.4f}"

    def test_p1_individual_rates(self, results):
        errors = results["p1"]["errors"]
        for i in range(len(errors) - 1):
            rate = np.log(errors[i] / errors[i + 1]) / np.log(2)
            assert rate > 1.5, \
                f"P1 rate between n={4 * 2**i} and n={4 * 2**(i+1)} too low: {rate:.4f}"

    def test_p2_individual_rates(self, results):
        errors = results["p2"]["errors"]
        for i in range(len(errors) - 1):
            rate = np.log(errors[i] / errors[i + 1]) / np.log(2)
            assert rate > 2.0, \
                f"P2 rate between n={4 * 2**i} and n={4 * 2**(i+1)} too low: {rate:.4f}"

    def test_p1_rate_consistency(self, results):
        """Individual rates should not vary wildly for a smooth solution."""
        errors = results["p1"]["errors"]
        rates = [np.log(errors[i] / errors[i + 1]) / np.log(2)
                 for i in range(len(errors) - 1)]
        assert max(rates) - min(rates) < 1.0, \
            f"P1 rates too inconsistent: {rates}"

    def test_p2_rate_consistency(self, results):
        """Individual rates should not vary wildly for a smooth solution."""
        errors = results["p2"]["errors"]
        rates = [np.log(errors[i] / errors[i + 1]) / np.log(2)
                 for i in range(len(errors) - 1)]
        assert max(rates) - min(rates) < 1.5, \
            f"P2 rates too inconsistent: {rates}"


class TestCrossValidation:
    """Cross-validate reported results against independent checks."""

    def test_p1_error_n8(self, results):
        """P1 on n=8 should give L2 error roughly in [1e-4, 0.5]."""
        e = results["p1"]["errors"][1]
        assert 1e-4 < e < 0.5, \
            f"P1 error on n=8 mesh outside plausible range: {e}"

    def test_p2_error_n8(self, results):
        """P2 on n=8 should give L2 error roughly in [1e-6, 0.1]."""
        e = results["p2"]["errors"][1]
        assert 1e-6 < e < 0.1, \
            f"P2 error on n=8 mesh outside plausible range: {e}"

    def test_p1_error_n16(self, results):
        """P1 on n=16 should give L2 error in [5e-4, 0.02]."""
        e = results["p1"]["errors"][2]
        assert 5e-4 < e < 0.02, \
            f"P1 error on n=16 mesh outside plausible range: {e}"

    def test_p2_error_n16(self, results):
        """P2 on n=16 should give L2 error in [1e-6, 0.005]."""
        e = results["p2"]["errors"][2]
        assert 1e-6 < e < 0.005, \
            f"P2 error on n=16 mesh outside plausible range: {e}"

    def test_error_ratio_p1_to_p2(self, results):
        """On the finest mesh, P2 error should be much smaller than P1."""
        p1 = results["p1"]["errors"][-1]
        p2 = results["p2"]["errors"][-1]
        ratio = p1 / p2
        assert ratio > 5, \
            f"P1/P2 error ratio on finest mesh should be >> 1, got {ratio:.2f}"


class TestPDEConsistency:
    """Verify the PDE is self-consistent: -div(K grad u) + c*u = f.

    Uses numerical finite differences to check that the forcing function
    in problem_spec.py matches the PDE evaluated with the exact solution
    at several interior points. This catches analytical errors in the
    forcing derivation.
    """

    def test_pde_residual_at_interior_points(self):
        """Numerically verify -div(K grad u) + cu = f at non-symmetric points."""
        import sys
        sys.path.insert(0, '/app')
        from problem_spec import diffusion_tensor, reaction, exact_solution, forcing

        h = 1e-5
        # Points chosen where cos(pi*x) and cos(pi*y) are nonzero,
        # away from symmetric cancellation at (0.5, 0.5)
        test_points = [(0.25, 0.75), (0.3, 0.4), (0.7, 0.3)]

        for x0, y0 in test_points:
            u = exact_solution

            def kgrad_component(x, y, comp):
                """Compute component of K(x,y) @ grad u(x,y)."""
                K = diffusion_tensor(x, y)
                ux = (u(x + h, y) - u(x - h, y)) / (2 * h)
                uy = (u(x, y + h) - u(x, y - h)) / (2 * h)
                return K[comp, 0] * ux + K[comp, 1] * uy

            # div(K grad u) via centered differences
            dFx_dx = (kgrad_component(x0 + h, y0, 0) -
                       kgrad_component(x0 - h, y0, 0)) / (2 * h)
            dFy_dy = (kgrad_component(x0, y0 + h, 1) -
                       kgrad_component(x0, y0 - h, 1)) / (2 * h)

            neg_div_Kgu = -(dFx_dx + dFy_dy)
            cu = reaction(x0, y0) * u(x0, y0)
            numerical_f = neg_div_Kgu + cu
            analytical_f = forcing(x0, y0)

            rel_err = abs(numerical_f - analytical_f) / (abs(numerical_f) + 1e-15)
            assert rel_err < 0.01, \
                f"PDE not satisfied at ({x0}, {y0}): " \
                f"-div(K grad u)+cu = {numerical_f:.6f}, " \
                f"f() = {analytical_f:.6f}, rel_err = {rel_err:.4f}"

    def test_exact_solution_boundary_values(self):
        """Verify the exact solution vanishes on the boundary."""
        import sys
        sys.path.insert(0, '/app')
        from problem_spec import exact_solution

        # Check boundary points
        boundary_pts = [(0, 0.5), (1, 0.5), (0.5, 0), (0.5, 1),
                        (0, 0), (1, 1), (0.3, 0), (0.7, 1)]
        for x, y in boundary_pts:
            assert abs(exact_solution(x, y)) < 1e-14, \
                f"u({x}, {y}) = {exact_solution(x, y)}, should be 0"

    def test_diffusion_tensor_spd(self):
        """Verify K is symmetric positive definite at several points."""
        import sys
        sys.path.insert(0, '/app')
        from problem_spec import diffusion_tensor

        test_points = [(0.25, 0.75), (0.5, 0.5), (0.1, 0.9), (0.8, 0.3)]
        for x, y in test_points:
            K = diffusion_tensor(x, y)
            assert abs(K[0, 1] - K[1, 0]) < 1e-14, \
                f"K not symmetric at ({x}, {y})"
            eigvals = np.linalg.eigvalsh(K)
            assert all(e > 0 for e in eigvals), \
                f"K not positive definite at ({x}, {y}): eigvals={eigvals}"
