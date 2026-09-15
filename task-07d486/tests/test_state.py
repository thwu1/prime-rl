
"""
Tests for Ewald summation pipeline output.
Validates energy and force computations against known physical constraints,
verifies finite-difference force-energy consistency, and checks convergence
evaluation of the reciprocal-space cutoff.
"""

import json
import math
import pytest
from pathlib import Path


@pytest.fixture
def result():
    path = Path("/app/result.json")
    assert path.exists(), "result.json not found at /app/result.json"
    with open(path) as f:
        data = json.load(f)
    return data


class TestMadelungConstant:
    """Validate the Madelung constant against the known analytical value."""

    def test_nacl_madelung_value(self, result):
        """NaCl Madelung constant should be approximately 1.7475645946."""
        expected = 1.7475645946
        actual = result["nacl_madelung"]
        assert isinstance(actual, (int, float)), (
            f"nacl_madelung should be a number, got {type(actual)}"
        )
        assert abs(actual - expected) < 1e-3, (
            f"Madelung constant {actual:.8f} differs from expected {expected:.10f} "
            f"by {abs(actual - expected):.2e} (tolerance: 1e-3)"
        )

    def test_crystal_forces_vanish(self, result):
        """Forces on perfect NaCl crystal should be small by cubic symmetry."""
        max_force = result["nacl_max_force"]
        assert isinstance(max_force, (int, float)), (
            f"nacl_max_force should be a number, got {type(max_force)}"
        )
        assert max_force < 5e-3, (
            f"Max force on perfect crystal is {max_force:.6e}, "
            f"should be ~0 by symmetry (tolerance: 5e-3)"
        )


class TestForceConservation:
    """Total force must vanish by Newton's third law."""

    def test_total_force_x(self, result):
        """Sum of x-forces should vanish."""
        fx = result["perturbed_force_sum"][0]
        assert abs(fx) < 1e-3, f"Force sum x = {fx:.6e}, should be ~0"

    def test_total_force_y(self, result):
        """Sum of y-forces should vanish."""
        fy = result["perturbed_force_sum"][1]
        assert abs(fy) < 1e-3, f"Force sum y = {fy:.6e}, should be ~0"

    def test_total_force_z(self, result):
        """Sum of z-forces should vanish."""
        fz = result["perturbed_force_sum"][2]
        assert abs(fz) < 1e-3, f"Force sum z = {fz:.6e}, should be ~0"


class TestEnergyDecomposition:
    """The three Ewald energy components must sum to the total."""

    def test_energy_sum_equals_total(self, result):
        """E_real + E_recip + E_self must equal E_total."""
        comps = result["perturbed_energy_components"]
        E_sum = comps["real"] + comps["recip"] + comps["self"]
        E_total = result["perturbed_energy"]
        assert abs(E_sum - E_total) < 1e-6, (
            f"Energy decomposition mismatch: "
            f"real({comps['real']:.8f}) + recip({comps['recip']:.8f}) + "
            f"self({comps['self']:.8f}) = {E_sum:.8f}, but total = {E_total:.8f}"
        )

    def test_self_energy_negative(self, result):
        """Self-energy correction must be negative."""
        E_self = result["perturbed_energy_components"]["self"]
        assert E_self < 0, f"Self-energy should be negative, got {E_self}"

    def test_total_energy_negative(self, result):
        """Total energy of a charge-neutral crystal should be negative."""
        E_total = result["perturbed_energy"]
        assert E_total < 0, f"Total energy should be negative, got {E_total}"


class TestForceEnergyConsistency:
    """Analytical forces must agree with centered finite differences of energy."""

    def test_fd_numerical_force_computation(self, result):
        """Verify that numerical_force_x is correctly computed from energies."""
        fd = result["fd_check"]
        dx = fd["dx"]
        expected = -(fd["energy_plus"] - fd["energy_minus"]) / (2 * dx)
        actual = fd["numerical_force_x"]
        assert abs(expected - actual) < 1e-8, (
            f"numerical_force_x ({actual}) inconsistent with energies: "
            f"expected -(({fd['energy_plus']}) - ({fd['energy_minus']}))/(2*{dx}) = {expected}"
        )

    def test_force_energy_consistency(self, result):
        """Analytical force_x on particle 0 must match finite-difference gradient."""
        fd = result["fd_check"]
        numerical_fx = fd["numerical_force_x"]
        analytical_fx = result["perturbed_forces"][0][0]

        if abs(analytical_fx) > 1e-6:
            rel_error = abs(numerical_fx - analytical_fx) / abs(analytical_fx)
            assert rel_error < 0.01, (
                f"Force-energy consistency failed: "
                f"analytical={analytical_fx:.10f}, numerical={numerical_fx:.10f}, "
                f"relative error={rel_error:.4e} (tolerance: 1%)"
            )
        else:
            assert abs(numerical_fx - analytical_fx) < 1e-4, (
                f"Force-energy consistency failed for near-zero force: "
                f"analytical={analytical_fx:.2e}, numerical={numerical_fx:.2e}"
            )


class TestResultStructure:
    """Verify the result JSON has the correct structure."""

    def test_has_all_required_keys(self, result):
        """Result must contain all required top-level keys."""
        required = [
            "nacl_madelung", "nacl_max_force", "perturbed_energy",
            "perturbed_energy_components", "perturbed_forces",
            "perturbed_force_sum", "fd_check",
            "convergence_study", "min_converged_k_max"
        ]
        for key in required:
            assert key in result, f"Missing required key: '{key}'"

    def test_forces_shape(self, result):
        """Forces should be 64 x 3 (one 3-vector per particle)."""
        forces = result["perturbed_forces"]
        assert len(forces) == 64, f"Expected 64 force vectors, got {len(forces)}"
        for i, f in enumerate(forces):
            assert len(f) == 3, f"Force vector {i} has {len(f)} components, expected 3"

    def test_force_sum_shape(self, result):
        """Force sum should be a 3-component vector."""
        fs = result["perturbed_force_sum"]
        assert len(fs) == 3, f"Force sum has {len(fs)} components, expected 3"

    def test_energy_components_keys(self, result):
        """Energy components dict must have real, recip, self."""
        comps = result["perturbed_energy_components"]
        for key in ["real", "recip", "self"]:
            assert key in comps, f"Missing energy component: '{key}'"

    def test_fd_check_keys(self, result):
        """Finite difference check must have all required keys."""
        fd = result["fd_check"]
        for key in ["dx", "energy_plus", "energy_minus", "numerical_force_x"]:
            assert key in fd, f"Missing fd_check key: '{key}'"
        assert fd["dx"] == pytest.approx(1e-5), f"dx should be 1e-5, got {fd['dx']}"


class TestConvergenceStudy:
    """Verify the reciprocal-space convergence evaluation."""

    def test_convergence_study_structure(self, result):
        """Must have 7 entries for k_max values [3, 4, 5, 6, 7, 8, 9]."""
        cs = result["convergence_study"]
        assert isinstance(cs, list), f"convergence_study should be a list, got {type(cs)}"
        assert len(cs) == 7, f"Expected 7 convergence entries, got {len(cs)}"
        k_maxes = [e["k_max"] for e in cs]
        assert k_maxes == [3, 4, 5, 6, 7, 8, 9], (
            f"k_max values should be [3,4,5,6,7,8,9], got {k_maxes}"
        )
        for e in cs:
            assert isinstance(e["madelung"], (int, float)), (
                f"madelung at k_max={e['k_max']} should be numeric"
            )

    def test_convergence_at_k7_matches_madelung(self, result):
        """Madelung at k_max=7 in convergence study must match nacl_madelung."""
        cs = result["convergence_study"]
        k7_entry = [e for e in cs if e["k_max"] == 7][0]
        diff = abs(k7_entry["madelung"] - result["nacl_madelung"])
        assert diff < 1e-8, (
            f"Convergence study k_max=7 madelung ({k7_entry['madelung']:.10f}) "
            f"differs from nacl_madelung ({result['nacl_madelung']:.10f}) by {diff:.2e}"
        )

    def test_convergence_values_vary(self, result):
        """Convergence study must show varying Madelung values across k_max."""
        cs = result["convergence_study"]
        mads = [e["madelung"] for e in cs]
        spread = max(mads) - min(mads)
        assert spread > 1e-10, (
            f"Convergence study values should vary with k_max "
            f"(spread = {spread:.2e}), not be constant"
        )

    def test_min_converged_k_max_type(self, result):
        """min_converged_k_max must be an integer in [3, 9]."""
        mkm = result["min_converged_k_max"]
        assert isinstance(mkm, int), (
            f"min_converged_k_max should be int, got {type(mkm)}"
        )
        assert 3 <= mkm <= 9, (
            f"min_converged_k_max should be in [3, 9], got {mkm}"
        )

    def test_min_converged_k_max_is_converged(self, result):
        """At min_converged_k_max, Madelung error must be < 1e-3."""
        mkm = result["min_converged_k_max"]
        cs = result["convergence_study"]
        entry = [e for e in cs if e["k_max"] == mkm][0]
        ref = 1.7475645946
        error = abs(entry["madelung"] - ref)
        assert error < 1e-3, (
            f"At min_converged_k_max={mkm}, Madelung error is {error:.2e} "
            f"(must be < 1e-3)"
        )

    def test_min_converged_k_max_is_minimum(self, result):
        """At k_max one below min_converged, error must be >= 1e-3 (if in range)."""
        mkm = result["min_converged_k_max"]
        if mkm > 3:
            cs = result["convergence_study"]
            prev = [e for e in cs if e["k_max"] == mkm - 1][0]
            ref = 1.7475645946
            error = abs(prev["madelung"] - ref)
            assert error >= 1e-3, (
                f"At k_max={mkm - 1} (one below min_converged), "
                f"Madelung error is {error:.2e} which is < 1e-3, "
                f"so min_converged_k_max should be {mkm - 1} not {mkm}"
            )

    def test_high_k_max_converged(self, result):
        """At k_max >= 7, Madelung must be within 1e-3 of reference."""
        cs = result["convergence_study"]
        ref = 1.7475645946
        for e in cs:
            if e["k_max"] >= 7:
                error = abs(e["madelung"] - ref)
                assert error < 1e-3, (
                    f"At k_max={e['k_max']}, Madelung error is {error:.2e} "
                    f"(should be < 1e-3 for well-converged sum)"
                )
