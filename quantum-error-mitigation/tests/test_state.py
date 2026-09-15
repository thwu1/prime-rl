"""
Tests for quantum error-mitigated molecular PES benchmark.

Verifies correctness of the results.json output:
structure, physical reasonableness, noise model behavior, and ZNE effectiveness.
"""

import json
import os

import numpy as np
import pytest

RESULTS_PATH = '/app/results.json'


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


# -- Structure tests --------------------------------------------------------

class TestStructure:
    """Verify that results.json has the required keys and shapes."""

    REQUIRED_KEYS = [
        'bond_lengths', 'exact_energies', 'noisy_energies', 'zne_energies',
        'trace_energies', 'equilibrium_bond_length', 'equilibrium_energy',
        'dissociation_energy', 'noise_parameters',
    ]

    def test_required_keys_present(self, results):
        for k in self.REQUIRED_KEYS:
            assert k in results, f"Missing required key: '{k}'"

    def test_noise_parameters_keys(self, results):
        np_d = results['noise_parameters']
        assert 'base_noise_rate' in np_d, "Missing noise_parameters.base_noise_rate"
        assert 'noise_scale_factors' in np_d, "Missing noise_parameters.noise_scale_factors"

    def test_noise_rate_positive(self, results):
        assert results['noise_parameters']['base_noise_rate'] > 0

    def test_scale_factors_valid(self, results):
        sf = results['noise_parameters']['noise_scale_factors']
        assert len(sf) >= 3, f"Need >= 3 noise scale factors, got {len(sf)}"
        assert sf[0] >= 1, "First scale factor must be >= 1"
        for i in range(1, len(sf)):
            assert sf[i] > sf[i - 1], "Scale factors must be strictly increasing"

    def test_25_bond_lengths(self, results):
        assert len(results['bond_lengths']) == 25

    def test_array_lengths_match(self, results):
        n = len(results['bond_lengths'])
        for key in ['exact_energies', 'noisy_energies', 'zne_energies', 'trace_energies']:
            assert len(results[key]) == n, f"'{key}' length {len(results[key])} != {n}"

    def test_bond_length_range(self, results):
        bl = results['bond_lengths']
        assert abs(bl[0] - 0.3) < 0.05, f"First bond length {bl[0]} not near 0.3"
        assert abs(bl[-1] - 2.5) < 0.05, f"Last bond length {bl[-1]} not near 2.5"

    def test_bond_lengths_monotonic(self, results):
        bl = results['bond_lengths']
        for i in range(1, len(bl)):
            assert bl[i] > bl[i - 1], f"Bond lengths not monotonic at index {i}"


# -- Physics tests ----------------------------------------------------------

class TestPhysics:
    """Verify physical correctness of exact energies and derived quantities."""

    def test_energies_all_finite(self, results):
        for key in ['exact_energies', 'noisy_energies', 'zne_energies', 'trace_energies']:
            for i, e in enumerate(results[key]):
                assert np.isfinite(e), f"Non-finite value in '{key}' at index {i}"

    def test_exact_minimum_energy_range(self, results):
        """Ground state of H2/STO-3G is ~-1.137 Ha."""
        min_e = min(results['exact_energies'])
        assert -1.25 < min_e < -1.05, f"Min exact energy {min_e:.4f} outside [-1.25, -1.05]"

    def test_dissociation_limit(self, results):
        """At large R, H2 dissociates to two H atoms: E -> ~-1.0 Ha in STO-3G."""
        e_far = results['exact_energies'][-1]
        assert -1.10 < e_far < -0.90, f"Dissociation limit {e_far:.4f} outside [-1.10, -0.90]"

    def test_pes_minimum_interior(self, results):
        """PES minimum should not be at the first or last bond length."""
        exact = results['exact_energies']
        min_idx = exact.index(min(exact))
        assert 1 <= min_idx <= 23, f"PES minimum at edge index {min_idx}"

    def test_pes_shape(self, results):
        """Energy at endpoints should be above the minimum."""
        exact = results['exact_energies']
        min_e = min(exact)
        assert exact[0] > min_e, "Energy at shortest R not above PES minimum"
        assert exact[-1] > min_e, "Energy at longest R not above PES minimum"

    def test_equilibrium_bond_length(self, results):
        """H2/STO-3G equilibrium bond length is ~0.735 A."""
        eq_bl = results['equilibrium_bond_length']
        assert 0.60 < eq_bl < 0.90, \
            f"Equilibrium bond length {eq_bl:.4f} outside [0.60, 0.90]"

    def test_equilibrium_energy(self, results):
        eq_e = results['equilibrium_energy']
        assert -1.20 < eq_e < -1.10, \
            f"Equilibrium energy {eq_e:.4f} outside [-1.20, -1.10]"

    def test_equilibrium_consistency(self, results):
        """equilibrium_energy should equal the minimum of exact_energies."""
        eq_e = results['equilibrium_energy']
        min_e = min(results['exact_energies'])
        assert abs(eq_e - min_e) < 1e-6, \
            f"equilibrium_energy {eq_e} != min(exact_energies) {min_e}"

    def test_dissociation_energy_range(self, results):
        """Dissociation energy of H2/STO-3G is ~0.07-0.18 Ha."""
        de = results['dissociation_energy']
        assert 0.02 < de < 0.25, f"Dissociation energy {de:.4f} outside [0.02, 0.25]"

    def test_dissociation_energy_consistency(self, results):
        de = results['dissociation_energy']
        computed = results['exact_energies'][-1] - results['equilibrium_energy']
        assert abs(de - computed) < 1e-6, \
            f"dissociation_energy {de} inconsistent with exact_energies"

    def test_trace_energies_above_ground(self, results):
        """Tr(H)/2^n (maximally mixed state energy) should be above ground state."""
        exact = np.array(results['exact_energies'])
        trace = np.array(results['trace_energies'])
        above = np.sum(trace > exact - 0.01)
        assert above >= 22, f"Only {above}/25 trace energies above exact"


# -- Error mitigation tests -------------------------------------------------

class TestErrorMitigation:
    """Verify noise model and ZNE effectiveness."""

    def test_noisy_above_exact(self, results):
        """Depolarizing noise pushes energy toward trace (above ground state)."""
        exact = np.array(results['exact_energies'])
        noisy = np.array(results['noisy_energies'])
        above = np.sum(noisy >= exact - 1e-4)
        assert above >= 20, f"Only {above}/25 noisy energies >= exact"

    def test_noisy_differs_from_exact(self, results):
        """Noisy energies should be measurably different from exact."""
        exact = np.array(results['exact_energies'])
        noisy = np.array(results['noisy_energies'])
        mean_diff = np.mean(np.abs(noisy - exact))
        assert mean_diff > 1e-6, f"Mean |noisy - exact| = {mean_diff} too small"

    def test_zne_mean_error_less_than_noisy(self, results):
        """ZNE-mitigated energies should be closer to exact than raw noisy."""
        exact = np.array(results['exact_energies'])
        noisy = np.array(results['noisy_energies'])
        zne = np.array(results['zne_energies'])
        noisy_err = np.mean(np.abs(noisy - exact))
        zne_err = np.mean(np.abs(zne - exact))
        assert zne_err < noisy_err, \
            f"ZNE mean error ({zne_err:.8f}) >= noisy mean error ({noisy_err:.8f})"

    def test_zne_max_error_bounded(self, results):
        """ZNE maximum absolute error should be < 0.1 Ha."""
        exact = np.array(results['exact_energies'])
        zne = np.array(results['zne_energies'])
        max_err = np.max(np.abs(zne - exact))
        assert max_err < 0.1, f"ZNE max error {max_err:.6f} >= 0.1 Ha"

    def test_zne_equilibrium_index_close(self, results):
        """ZNE PES minimum should be near exact PES minimum."""
        exact = np.array(results['exact_energies'])
        zne = np.array(results['zne_energies'])
        exact_min_idx = int(np.argmin(exact))
        zne_min_idx = int(np.argmin(zne))
        assert abs(exact_min_idx - zne_min_idx) <= 2, \
            f"ZNE min index {zne_min_idx} too far from exact min index {exact_min_idx}"
