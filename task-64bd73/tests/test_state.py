"""Tests for ZNE shot allocation optimizer.

Verifies mathematical properties, edge-case handling, end-to-end
performance, and the sqlite3+jq validation pipeline.
"""


import json
import os
import subprocess
import sys

sys.path.insert(0, "/app")

import numpy as np
import pytest

from hamiltonian import Hamiltonian
from optimizer import ZNEShotOptimizer
from simulator import (
    create_product_state,
    create_uniform_superposition,
    sample_commuting_group,
)


# ---------------------------------------------------------------------------
# Lagrange coefficients
# ---------------------------------------------------------------------------


class TestLagrangeCoefficients:
    def test_known_values_three_points(self):
        """For scale_factors=[1,2,3], gamma should be [3, -3, 1]."""
        ham = Hamiltonian(["ZI"], [1.0])
        opt = ZNEShotOptimizer(ham, [1.0, 2.0, 3.0], 0.01, 10)
        gamma = opt.lagrange_coefficients()
        np.testing.assert_allclose(gamma, [3.0, -3.0, 1.0], atol=1e-10)

    def test_mathematical_properties(self):
        """Sum-to-one and polynomial annihilation properties."""
        for factors in [
            [1.0, 2.0],
            [1.0, 3.0, 5.0],
            [1.0, 1.5, 2.0, 3.0],
            [1.0, 2.0, 4.0, 7.0, 11.0],
        ]:
            ham = Hamiltonian(["Z"], [1.0])
            opt = ZNEShotOptimizer(ham, factors, 0.01, 10)
            gamma = opt.lagrange_coefficients()
            x = np.array(factors)

            # Sum to 1
            assert abs(gamma.sum() - 1.0) < 1e-10, (
                f"Coefficients for {factors} sum to {gamma.sum()}"
            )

            # Polynomial annihilation: sum gamma_j * x_j^p = 0 for p=1..n-1
            for p in range(1, len(factors)):
                val = gamma @ (x**p)
                assert abs(val) < 1e-8, (
                    f"Polynomial annihilation failed for degree {p}: {val}"
                )


# ---------------------------------------------------------------------------
# Richardson extrapolation
# ---------------------------------------------------------------------------


class TestRichardsonExtrapolation:
    def test_exact_for_quadratic(self):
        """Three points should extrapolate a degree-2 polynomial exactly."""
        factors = [1.0, 2.0, 3.0]
        a, b, c = 2.718, -0.314, 0.159
        values = np.array([a + b * x + c * x**2 for x in factors])
        ham = Hamiltonian(["Z"], [1.0])
        opt = ZNEShotOptimizer(ham, factors, 0.01, 10)
        result = opt.richardson_extrapolate(values)
        assert abs(result - a) < 1e-10, f"Expected {a}, got {result}"

    def test_exact_for_cubic_with_four_points(self):
        """Four points should extrapolate a degree-3 polynomial exactly."""
        factors = [1.0, 2.0, 3.0, 5.0]
        a, b, c, d = 1.0, -0.5, 0.2, -0.03
        values = np.array([a + b * x + c * x**2 + d * x**3 for x in factors])
        ham = Hamiltonian(["Z"], [1.0])
        opt = ZNEShotOptimizer(ham, factors, 0.01, 10)
        result = opt.richardson_extrapolate(values)
        assert abs(result - a) < 1e-9, f"Expected {a}, got {result}"


# ---------------------------------------------------------------------------
# Group variance estimation
# ---------------------------------------------------------------------------


class TestGroupVariance:
    def test_zero_variance_for_eigenstate(self):
        """XX on |++> has zero variance (eigenstate with eigenvalue +1)."""
        state = create_uniform_superposition(2)
        ham = Hamiltonian(["XX"], [10.0])
        opt = ZNEShotOptimizer(ham, [1.0], noise_rate=0.0, depth=0)
        rng = np.random.default_rng(42)
        measurements = sample_commuting_group(
            state, ["XX"], 0.0, 0, 1.0, 10000, rng
        )
        var = opt.estimate_group_variance(measurements, 0)
        assert var < 0.05, f"Expected near-zero variance, got {var}"

    def test_maximum_variance_single_term(self):
        """Z on |+> has maximum per-shot variance = 1."""
        state = create_uniform_superposition(1)
        ham = Hamiltonian(["Z"], [1.0])
        opt = ZNEShotOptimizer(ham, [1.0], noise_rate=0.0, depth=0)
        rng = np.random.default_rng(42)
        measurements = sample_commuting_group(
            state, ["Z"], 0.0, 0, 1.0, 50000, rng
        )
        var = opt.estimate_group_variance(measurements, 0)
        # V = c^2 * (1 - <Z>^2) = 1 * (1 - 0) = 1
        assert abs(var - 1.0) < 0.05, f"Expected ~1.0, got {var}"

    def test_covariance_accounting(self):
        """Covariance between co-measured ZI and IZ on GHZ state.

        For (|00>+|11>)/sqrt(2):
          <ZI>=0, <IZ>=0, <ZI*IZ>=<ZZ>=1
          Cov(ZI,IZ)=1

        H = ZI + IZ measured together:
          V = Var(ZI + IZ) = Var(ZI) + Var(IZ) + 2*Cov(ZI,IZ)
            = 1 + 1 + 2 = 4

        Without covariance accounting, one would get V=2 (wrong).
        """
        state = np.zeros(4, dtype=complex)
        state[0] = 1 / np.sqrt(2)
        state[3] = 1 / np.sqrt(2)

        ham = Hamiltonian(["ZI", "IZ"], [1.0, 1.0])
        opt = ZNEShotOptimizer(ham, [1.0], noise_rate=0.0, depth=0)
        rng = np.random.default_rng(42)
        measurements = sample_commuting_group(
            state, ["ZI", "IZ"], 0.0, 0, 1.0, 100000, rng
        )
        var = opt.estimate_group_variance(measurements, 0)
        assert abs(var - 4.0) < 0.1, (
            f"Expected ~4.0 (covariance-aware), got {var}"
        )


# ---------------------------------------------------------------------------
# Optimal allocation
# ---------------------------------------------------------------------------


class TestOptimalAllocation:
    def _make_optimizer(self, n_groups=3, n_levels=3):
        terms = ["ZI", "IZ", "XX"][:n_groups]
        coeffs = [1.0, 1.0, 10.0][:n_groups]
        factors = [1.0, 2.0, 3.0][:n_levels]
        ham = Hamiltonian(terms, coeffs)
        return ZNEShotOptimizer(ham, factors, 0.01, 10)

    def test_budget_preserved(self):
        """Total allocated shots must equal the budget."""
        opt = self._make_optimizer()
        V = np.array(
            [[1.0, 0.5, 0.8], [0.9, 0.4, 0.7], [0.8, 0.3, 0.6]]
        )
        for budget in [100, 1000, 5000, 12345]:
            alloc = opt.optimal_allocation(V, budget)
            assert alloc.sum() == budget, (
                f"Budget {budget}, got {alloc.sum()}"
            )

    def test_minimum_one_shot(self):
        """Every cell must receive at least 1 shot."""
        opt = self._make_optimizer()
        V = np.array(
            [
                [1.0, 0.001, 0.001],
                [0.001, 0.001, 0.001],
                [0.001, 0.001, 0.001],
            ]
        )
        alloc = opt.optimal_allocation(V, 100)
        assert alloc.min() >= 1, f"Minimum allocation is {alloc.min()}"

    def test_zero_variance_gets_minimum(self):
        """Zero-variance cells get minimum allocation (1 shot)."""
        ham = Hamiltonian(["ZI", "XX"], [1.0, 10.0])
        opt = ZNEShotOptimizer(ham, [1.0, 2.0], 0.01, 10)
        V = np.array([[1.0, 0.0], [0.9, 0.0]])
        alloc = opt.optimal_allocation(V, 1000)
        assert alloc[0, 1] == 1 and alloc[1, 1] == 1, (
            f"Zero-variance cells got {alloc[:, 1]}"
        )

    def test_proportional_to_analytical_formula(self):
        """Large-budget allocation should match the continuous optimum."""
        ham = Hamiltonian(["ZI", "IZ"], [1.0, 1.0])
        opt = ZNEShotOptimizer(ham, [1.0, 2.0, 3.0], 0.01, 10)
        gamma = opt.lagrange_coefficients()
        V = np.array([[0.8, 0.6], [0.7, 0.5], [0.6, 0.4]])
        budget = 100000
        alloc = opt.optimal_allocation(V, budget)

        weights = np.abs(gamma)[:, None] * np.sqrt(V)
        expected = budget * weights / weights.sum()

        np.testing.assert_allclose(alloc, expected, atol=2)


# ---------------------------------------------------------------------------
# ZNE variance
# ---------------------------------------------------------------------------


class TestZNEVariance:
    def test_formula_correctness(self):
        """Variance matches sum_j gamma_j^2 * sum_k V[j,k] / N[j,k]."""
        ham = Hamiltonian(["ZI", "IZ"], [1.0, 1.0])
        opt = ZNEShotOptimizer(ham, [1.0, 2.0, 3.0], 0.01, 10)
        gamma = opt.lagrange_coefficients()
        V = np.array([[0.8, 0.6], [0.7, 0.5], [0.6, 0.4]])
        N = np.array([[100, 80], [60, 40], [30, 20]])

        var = opt.zne_variance(V, N)
        expected = sum(
            gamma[j] ** 2 * sum(V[j, k] / N[j, k] for k in range(2))
            for j in range(3)
        )
        assert abs(var - expected) < 1e-10

    def test_optimal_not_worse_than_uniform(self):
        """Optimal allocation variance <= uniform allocation variance."""
        ham = Hamiltonian(["ZI", "IZ", "XX"], [1.0, 1.0, 10.0])
        opt = ZNEShotOptimizer(ham, [1.0, 2.0, 3.0], 0.01, 10)
        V = np.array(
            [[1.0, 0.5, 0.01], [0.9, 0.4, 0.01], [0.8, 0.3, 0.01]]
        )
        budget = 1000

        opt_alloc = opt.optimal_allocation(V, budget)

        n_cells = 3 * 3
        uniform_alloc = np.full((3, 3), budget // n_cells, dtype=int)
        remaining = budget - uniform_alloc.sum()
        for i in range(remaining):
            uniform_alloc.flat[i] += 1

        var_opt = opt.zne_variance(V, opt_alloc)
        var_uni = opt.zne_variance(V, uniform_alloc)

        assert var_opt <= var_uni + 1e-10, (
            f"Optimal {var_opt:.6f} > uniform {var_uni:.6f}"
        )


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_adaptive_output_structure(self):
        """run_adaptive returns dict with expected keys, shapes, budget."""
        state = create_product_state([0.5, 1.2])
        ham = Hamiltonian(["ZI", "IZ", "XX"], [1.0, 1.0, 5.0])
        opt = ZNEShotOptimizer(ham, [1.0, 2.0, 3.0], 0.02, 5)
        rng = np.random.default_rng(42)
        result = opt.run_adaptive(state, total_budget=3000, num_rounds=3, rng=rng)

        assert "energy" in result
        assert "variance" in result
        assert "energy_per_level" in result
        assert "allocation" in result
        assert isinstance(result["energy"], (float, np.floating))
        assert isinstance(result["variance"], (float, np.floating))
        assert result["energy_per_level"].shape == (3,)
        assert result["allocation"].shape == (3, opt.n_groups)
        assert result["allocation"].sum() == 3000
        assert result["allocation"].min() >= 1

    def test_zne_improves_over_noisy(self):
        """ZNE-extrapolated energy is closer to ideal than raw noisy."""
        from simulator import noisy_expectation

        state = create_product_state([0.3, 0.7, 1.1, 2.0])
        terms = ["ZZII", "IZZI", "IIZZ", "XIII", "IXII", "IIXI", "IIIX"]
        coeffs = [0.5, 0.5, 0.5, -0.3, -0.3, -0.3, -0.3]
        ham = Hamiltonian(terms, coeffs)
        ideal_energy = ham.exact_energy(state)

        noise_rate = 0.05
        depth = 10
        opt = ZNEShotOptimizer(
            ham, [1.0, 2.0, 3.0], noise_rate=noise_rate, depth=depth
        )

        # Analytical noisy energy (no shot noise, just systematic bias)
        noisy_energy = sum(
            c * noisy_expectation(state, t, noise_rate, depth, 1.0)
            for t, c in zip(terms, coeffs)
        )
        noisy_error = abs(noisy_energy - ideal_energy)

        rng = np.random.default_rng(12345)
        zne_errors = []
        for _ in range(50):
            result = opt.run_adaptive(
                state, total_budget=15000, num_rounds=5, rng=rng
            )
            zne_errors.append(abs(result["energy"] - ideal_energy))

        mean_zne = np.mean(zne_errors)

        # ZNE should substantially reduce the systematic bias
        assert mean_zne < 0.8 * noisy_error, (
            f"ZNE error {mean_zne:.4f} not sufficiently better than "
            f"noisy systematic error {noisy_error:.4f}"
        )

    def test_adaptive_outperforms_uniform(self):
        """Adaptive allocation has lower MSE than uniform allocation."""
        state = create_product_state([0.5, 1.2])
        ham = Hamiltonian(["ZI", "IZ", "XX"], [1.0, 1.0, 10.0])
        opt = ZNEShotOptimizer(
            ham, [1.0, 2.0, 3.0], noise_rate=0.02, depth=5
        )
        ideal_energy = ham.exact_energy(state)

        rng = np.random.default_rng(999)
        adaptive_sq_errors = []
        uniform_sq_errors = []

        n_cells = opt.n_levels * opt.n_groups
        budget = 5000

        for _ in range(100):
            # Adaptive
            result = opt.run_adaptive(
                state, total_budget=budget, num_rounds=5, rng=rng
            )
            adaptive_sq_errors.append(
                (result["energy"] - ideal_energy) ** 2
            )

            # Uniform baseline
            shots_per_cell = budget // n_cells
            uniform_alloc = np.full(
                (opt.n_levels, opt.n_groups), shots_per_cell, dtype=int
            )
            remaining = budget - uniform_alloc.sum()
            for i in range(remaining):
                uniform_alloc.flat[i] += 1

            energies_u, _ = opt.measure_and_estimate(
                state, uniform_alloc, rng
            )
            e_uniform = opt.richardson_extrapolate(energies_u)
            uniform_sq_errors.append((e_uniform - ideal_energy) ** 2)

        adaptive_mse = np.mean(adaptive_sq_errors)
        uniform_mse = np.mean(uniform_sq_errors)

        assert adaptive_mse < 0.9 * uniform_mse, (
            f"Adaptive MSE {adaptive_mse:.6f} not better than "
            f"uniform MSE {uniform_mse:.6f}"
        )


# ---------------------------------------------------------------------------
# Validation pipeline (sqlite3 + jq + python3)
# ---------------------------------------------------------------------------


class TestValidationPipeline:
    """Tests for the sqlite3+jq+python3 validation pipeline."""

    def test_validation_script_exists(self):
        """/app/extract_and_validate.sh must exist and be executable."""
        path = "/app/extract_and_validate.sh"
        assert os.path.isfile(path), f"{path} does not exist"
        assert os.access(path, os.X_OK), f"{path} is not executable"

    def test_validation_script_uses_required_tools(self):
        """Script must invoke sqlite3 for DB queries and jq for JSON processing."""
        with open("/app/extract_and_validate.sh") as f:
            content = f.read()
        assert "sqlite3" in content and "reference_data.db" in content, (
            "Script must use sqlite3 to query reference_data.db"
        )
        assert "jq" in content, (
            "Script must use jq for JSON processing"
        )

    def test_validation_pipeline_produces_correct_report(self):
        """Running the pipeline produces validation_report.json with all passing."""
        report_path = "/app/validation_report.json"
        if os.path.exists(report_path):
            os.remove(report_path)

        result = subprocess.run(
            ["bash", "/app/extract_and_validate.sh"],
            capture_output=True, text=True, timeout=120,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"Validation script failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout[-500:]}\nstderr: {result.stderr[-500:]}"
        )
        assert os.path.isfile(report_path), "validation_report.json not generated"

        with open(report_path) as f:
            report = json.load(f)

        required = [
            "coefficient_examples",
            "extrapolation_examples",
            "variance_formula_examples",
            "group_variance_examples",
            "allocation_examples",
        ]
        for key in required:
            assert key in report, f"Report missing '{key}'"
            entry = report[key]
            assert isinstance(entry.get("total"), int) and entry["total"] > 0, (
                f"{key}: 'total' must be a positive int"
            )
            assert isinstance(entry.get("passed"), int), (
                f"{key}: 'passed' must be an int"
            )
            assert entry.get("status") in ("pass", "fail"), (
                f"{key}: 'status' must be 'pass' or 'fail'"
            )

        assert report.get("all_passed") is True, (
            "Not all validations passed: "
            + ", ".join(
                f"{k}: {v['passed']}/{v['total']}"
                for k, v in report.items()
                if isinstance(v, dict)
            )
        )
