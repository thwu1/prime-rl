"""
Tests for the Lotka-Volterra Bayesian ODE inference pipeline.

"""

import json
import os
import sys
import csv

import numpy as np
import pytest

RESULTS_DIR = "/app/results"
GROUND_TRUTH_FILE = "/app/ground_truth.json"


@pytest.fixture
def ground_truth():
    with open(GROUND_TRUTH_FILE) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# ODE function correctness (deterministic)
# ---------------------------------------------------------------------------

class TestODEFunction:
    """Verify the ODE right-hand side computes correct derivatives."""

    def _import_dz_dt(self):
        sys.path.insert(0, "/app")
        from model import dz_dt
        return dz_dt

    def test_ode_specific_values(self):
        """Check exact derivative values at a known state."""
        import jax.numpy as jnp
        dz_dt = self._import_dz_dt()

        z = jnp.array([30.0, 5.0])
        theta = jnp.array([1.0, 0.1, 1.5, 0.075])
        derivs = dz_dt(z, 0.0, theta)

        # du/dt = (1.0 - 0.1*5) * 30 = 0.5 * 30 = 15.0
        # dv/dt = (-1.5 + 0.075*30) * 5 = 0.75 * 5 = 3.75
        assert abs(float(derivs[0]) - 15.0) < 0.01, (
            f"du/dt should be 15.0, got {float(derivs[0])}"
        )
        assert abs(float(derivs[1]) - 3.75) < 0.01, (
            f"dv/dt should be 3.75, got {float(derivs[1])}"
        )

    def test_ode_correct_at_equilibrium(self):
        """At the interior equilibrium, both derivatives must be ~0."""
        import jax.numpy as jnp
        dz_dt = self._import_dz_dt()

        alpha, beta, gamma, delta = 1.0, 0.1, 1.5, 0.075
        u_star = gamma / delta   # 20.0
        v_star = alpha / beta    # 10.0

        z_eq = jnp.array([u_star, v_star])
        theta = jnp.array([alpha, beta, gamma, delta])
        derivs = dz_dt(z_eq, 0.0, theta)

        assert abs(float(derivs[0])) < 1e-4, (
            f"du/dt at equilibrium should be ~0, got {float(derivs[0])}"
        )
        assert abs(float(derivs[1])) < 1e-4, (
            f"dv/dt at equilibrium should be ~0, got {float(derivs[1])}"
        )

    def test_ode_derivatives_sign(self):
        """Prey must decline when predators are very abundant."""
        import jax.numpy as jnp
        dz_dt = self._import_dz_dt()

        theta = jnp.array([1.0, 0.1, 1.5, 0.075])

        # Many predators, few prey -> prey should decline
        z = jnp.array([10.0, 15.0])
        derivs = dz_dt(z, 0.0, theta)
        assert float(derivs[0]) < 0, (
            f"Prey should decline when predators are abundant, got du/dt={float(derivs[0])}"
        )

        # Few predators, abundant prey -> prey should grow
        z2 = jnp.array([30.0, 2.0])
        derivs2 = dz_dt(z2, 0.0, theta)
        assert float(derivs2[0]) > 0, (
            f"Prey should grow when predators are scarce, got du/dt={float(derivs2[0])}"
        )


# ---------------------------------------------------------------------------
# ODE integration behaviour (deterministic)
# ---------------------------------------------------------------------------

class TestODEIntegration:
    """Verify that the corrected ODE produces physically valid trajectories."""

    def _import_dz_dt(self):
        sys.path.insert(0, "/app")
        from model import dz_dt
        return dz_dt

    def test_trajectory_bounded(self):
        """Integrated trajectory must stay positive and bounded."""
        import jax.numpy as jnp
        from jax.experimental.ode import odeint
        dz_dt = self._import_dz_dt()

        z0 = jnp.array([25.0, 8.0])
        theta = jnp.array([1.0, 0.1, 1.5, 0.075])
        ts = jnp.linspace(0, 10, 11)

        z = odeint(dz_dt, z0, ts, theta, rtol=1e-6, atol=1e-6, mxstep=1000)

        assert jnp.all(z > 0), "Populations must remain positive"
        assert jnp.all(z < 500), "Populations should not explode"
        assert not jnp.any(jnp.isnan(z)), "Trajectory must not contain NaN"

    def test_trajectory_oscillates(self):
        """Lotka-Volterra dynamics should produce oscillations."""
        import jax.numpy as jnp
        from jax.experimental.ode import odeint
        dz_dt = self._import_dz_dt()

        z0 = jnp.array([25.0, 8.0])
        theta = jnp.array([1.0, 0.1, 1.5, 0.075])
        ts = jnp.linspace(0, 10, 101)

        z = odeint(dz_dt, z0, ts, theta, rtol=1e-6, atol=1e-6, mxstep=1000)

        u = z[:, 0]
        du = jnp.diff(u)
        sign_changes = int(jnp.sum(jnp.diff(jnp.sign(du)) != 0))
        assert sign_changes >= 2, (
            f"Prey population should oscillate (sign changes={sign_changes})"
        )


# ---------------------------------------------------------------------------
# Output file existence & structure
# ---------------------------------------------------------------------------

class TestResultsExist:
    """All required output files must exist with the correct schema."""

    def test_parameters_json_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "parameters.json")), (
            "parameters.json not found in results directory"
        )

    def test_predictions_csv_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "predictions.csv")), (
            "predictions.csv not found in results directory"
        )

    def test_diagnostics_json_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "diagnostics.json")), (
            "diagnostics.json not found in results directory"
        )

    def test_parameters_json_structure(self):
        with open(os.path.join(RESULTS_DIR, "parameters.json")) as f:
            params = json.load(f)

        for p in ["alpha", "beta", "gamma", "delta"]:
            assert p in params, f"Parameter '{p}' missing from parameters.json"
            for key in ("mean", "q5", "q95"):
                assert key in params[p], f"'{p}' missing key '{key}'"

    def test_predictions_csv_structure(self):
        with open(os.path.join(RESULTS_DIR, "predictions.csv")) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) > 0, "predictions.csv is empty"
        required = [
            "time", "u_mean", "u_lower", "u_upper",
            "v_mean", "v_lower", "v_upper",
        ]
        for col in required:
            assert col in rows[0], f"Column '{col}' missing from predictions.csv"

    def test_diagnostics_json_structure(self):
        with open(os.path.join(RESULTS_DIR, "diagnostics.json")) as f:
            diag = json.load(f)

        for p in ["alpha", "beta", "gamma", "delta"]:
            assert p in diag, f"Parameter '{p}' missing from diagnostics.json"
            assert "r_hat" in diag[p], f"'{p}' missing 'r_hat'"
            assert "n_eff" in diag[p], f"'{p}' missing 'n_eff'"


# ---------------------------------------------------------------------------
# Parameter recovery
# ---------------------------------------------------------------------------

class TestParameterRecovery:
    """Ground truth values must fall inside the posterior 90% CI."""

    def _load_params(self):
        with open(os.path.join(RESULTS_DIR, "parameters.json")) as f:
            return json.load(f)

    def test_alpha_recovery(self, ground_truth):
        params = self._load_params()
        true_val = ground_truth["alpha"]
        q5, q95 = params["alpha"]["q5"], params["alpha"]["q95"]
        assert q5 <= true_val <= q95, (
            f"True alpha={true_val} outside 90% CI [{q5:.4f}, {q95:.4f}]"
        )

    def test_beta_recovery(self, ground_truth):
        params = self._load_params()
        true_val = ground_truth["beta"]
        q5, q95 = params["beta"]["q5"], params["beta"]["q95"]
        assert q5 <= true_val <= q95, (
            f"True beta={true_val} outside 90% CI [{q5:.4f}, {q95:.4f}]"
        )

    def test_gamma_recovery(self, ground_truth):
        params = self._load_params()
        true_val = ground_truth["gamma"]
        q5, q95 = params["gamma"]["q5"], params["gamma"]["q95"]
        assert q5 <= true_val <= q95, (
            f"True gamma={true_val} outside 90% CI [{q5:.4f}, {q95:.4f}]"
        )

    def test_delta_recovery(self, ground_truth):
        params = self._load_params()
        true_val = ground_truth["delta"]
        q5, q95 = params["delta"]["q5"], params["delta"]["q95"]
        assert q5 <= true_val <= q95, (
            f"True delta={true_val} outside 90% CI [{q5:.4f}, {q95:.4f}]"
        )


# ---------------------------------------------------------------------------
# MCMC diagnostics
# ---------------------------------------------------------------------------

class TestMCMCDiagnostics:
    """MCMC chains should show no signs of non-convergence."""

    def _load_diag(self):
        with open(os.path.join(RESULTS_DIR, "diagnostics.json")) as f:
            return json.load(f)

    def test_rhat_convergence(self):
        diag = self._load_diag()
        for name, d in diag.items():
            if "r_hat" in d:
                assert d["r_hat"] < 1.1, (
                    f"r_hat for {name} = {d['r_hat']:.3f}, indicating non-convergence"
                )

    def test_effective_sample_size(self):
        diag = self._load_diag()
        for name, d in diag.items():
            if "n_eff" in d:
                assert d["n_eff"] > 50, (
                    f"n_eff for {name} = {d['n_eff']:.0f}, too low"
                )


# ---------------------------------------------------------------------------
# Posterior predictive quality
# ---------------------------------------------------------------------------

class TestPredictions:
    """Posterior predictive distributions must be physically sensible."""

    def _load_preds(self):
        with open(os.path.join(RESULTS_DIR, "predictions.csv")) as f:
            return list(csv.DictReader(f))

    def test_predictions_positive(self):
        for row in self._load_preds():
            for col in ("u_mean", "v_mean"):
                assert float(row[col]) > 0, (
                    f"{col} should be positive at t={row['time']}"
                )

    def test_credible_interval_ordering(self):
        for row in self._load_preds():
            assert float(row["u_lower"]) <= float(row["u_upper"]), (
                f"u_lower > u_upper at t={row['time']}"
            )
            assert float(row["v_lower"]) <= float(row["v_upper"]), (
                f"v_lower > v_upper at t={row['time']}"
            )

    def test_predictions_cover_data(self):
        """90% predictive CI should cover a majority of observations."""
        data = np.genfromtxt("/app/data.csv", delimiter=",", names=True)
        preds = self._load_preds()
        n = min(len(data), len(preds))

        u_covered = sum(
            1 for i in range(n)
            if float(preds[i]["u_lower"]) <= data["u"][i] <= float(preds[i]["u_upper"])
        )
        v_covered = sum(
            1 for i in range(n)
            if float(preds[i]["v_lower"]) <= data["v"][i] <= float(preds[i]["v_upper"])
        )

        u_rate = u_covered / n
        v_rate = v_covered / n
        assert u_rate >= 0.6, f"Prey coverage {u_rate:.2f} < 0.60"
        assert v_rate >= 0.6, f"Predator coverage {v_rate:.2f} < 0.60"
