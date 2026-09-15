"""
Tests for QCM-D multi-harmonic viscoelastic film analysis engine
and data processing pipeline.

Verifies forward calculation against analytical limits (Sauerbrey,
Gordon-Kanazawa), multi-layer coupling effects, forward-inverse
round-trip consistency, and pipeline output correctness.
"""


import pytest
import sys
import os
import json
import csv
import numpy as np

sys.path.insert(0, '/app')

ZQ = 8.84e6   # AT-cut quartz shear acoustic impedance (kg/m^2/s)
F1 = 5e6      # Fundamental resonant frequency (Hz) — default for engine tests
F1_CRYSTAL = 4.95e6  # Non-standard f1 from crystal.toml


class TestSauerbreyLimit:
    """A very stiff, thin, elastic film must match the Sauerbrey equation:
    delf = -2*n*f1^2*drho/Zq with negligible dissipation (delg ~ 0).
    """

    def setup_method(self):
        import qcm_engine
        self.engine = qcm_engine
        self.layers = {1: {'grho3': 1e14, 'phi': 0.0, 'drho': 1e-6}}
        self.harmonics = [3, 5, 7]

    def test_frequency_shifts_match_sauerbrey(self):
        result = self.engine.forward_calc(self.layers, self.harmonics)
        drho = 1e-6
        for n in self.harmonics:
            expected = -2.0 * n * F1 ** 2 * drho / ZQ
            actual = result[n]['delf']
            assert abs(actual - expected) / abs(expected) < 0.01, (
                f"n={n}: expected delf={expected:.6f}, got {actual:.6f}"
            )

    def test_negligible_dissipation(self):
        result = self.engine.forward_calc(self.layers, self.harmonics)
        for n in self.harmonics:
            assert abs(result[n]['delg']) < 0.01, (
                f"n={n}: expected delg~0, got {result[n]['delg']:.8f}"
            )


class TestGordonKanazawa:
    """Bulk Newtonian liquid (phi=90, drho=inf): |delf| = delg and both
    scale as sqrt(n). Tests against the analytical formula:
    delf = -f1*sqrt(grho3*n/3) / (sqrt(2)*pi*Zq)
    """

    def setup_method(self):
        import qcm_engine
        self.engine = qcm_engine
        self.grho3 = 9.4e7
        self.layers = {1: {'grho3': self.grho3, 'phi': 90.0, 'drho': float('inf')}}
        self.harmonics = [3, 5, 7]

    def test_delf_equals_delg(self):
        result = self.engine.forward_calc(self.layers, self.harmonics)
        for n in self.harmonics:
            delf = result[n]['delf']
            delg = result[n]['delg']
            assert delf < 0, f"n={n}: delf should be negative, got {delf}"
            assert delg > 0, f"n={n}: delg should be positive, got {delg}"
            ratio = abs(delf) / delg
            assert abs(ratio - 1.0) < 0.01, (
                f"n={n}: |delf|/delg = {ratio:.6f}, expected ~1.0"
            )

    def test_sqrt_n_scaling(self):
        result = self.engine.forward_calc(self.layers, self.harmonics)
        normalized = [abs(result[n]['delf']) / np.sqrt(n) for n in self.harmonics]
        ref = normalized[0]
        for val in normalized:
            assert abs(val - ref) / ref < 0.01, (
                f"delf/sqrt(n) not constant: {normalized}"
            )

    def test_absolute_values_match_analytical(self):
        result = self.engine.forward_calc(self.layers, self.harmonics)
        for n in self.harmonics:
            expected_delf = -F1 * np.sqrt(self.grho3 * n / 3.0) / (
                np.sqrt(2) * np.pi * ZQ
            )
            actual = result[n]['delf']
            assert abs(actual - expected_delf) / abs(expected_delf) < 0.005, (
                f"n={n}: expected delf={expected_delf:.2f}, got {actual:.2f}"
            )


class TestVacuumLoad:
    """Vacuum/air (grho3=0) produces zero frequency and bandwidth shifts."""

    def test_zero_shifts(self):
        import qcm_engine
        layers = {1: {'grho3': 0.0, 'phi': 90.0, 'drho': float('inf')}}
        result = qcm_engine.forward_calc(layers, [3, 5, 7])
        for n in [3, 5, 7]:
            assert abs(result[n]['delf']) < 1e-10, (
                f"n={n}: expected delf=0, got {result[n]['delf']}"
            )
            assert abs(result[n]['delg']) < 1e-10, (
                f"n={n}: expected delg=0, got {result[n]['delg']}"
            )


class TestMultiLayer:
    """Multi-layer calculations: coupling effects and physical constraints."""

    def setup_method(self):
        import qcm_engine
        self.engine = qcm_engine

    def test_film_plus_liquid_coupling(self):
        """Adding a liquid overlayer to a film must change the result."""
        film_only = {1: {'grho3': 5e8, 'phi': 30.0, 'drho': 2e-4}}
        film_liquid = {
            1: {'grho3': 5e8, 'phi': 30.0, 'drho': 2e-4},
            2: {'grho3': 9.4e7, 'phi': 90.0, 'drho': float('inf')},
        }
        r1 = self.engine.forward_calc(film_only, [3, 5, 7])
        r2 = self.engine.forward_calc(film_liquid, [3, 5, 7])
        for n in [3, 5, 7]:
            assert r2[n]['delf'] < 0, f"n={n}: combined delf should be negative"
            assert r2[n]['delg'] > 0, f"n={n}: combined delg should be positive"
            assert abs(r2[n]['delf'] - r1[n]['delf']) > 1.0, (
                f"n={n}: film+liquid delf too close to film-alone"
            )
            assert abs(r2[n]['delg'] - r1[n]['delg']) > 1.0, (
                f"n={n}: film+liquid delg too close to film-alone"
            )

    def test_three_layer_physical_constraints(self):
        """Three-layer stack must produce physical shifts."""
        layers = {
            1: {'grho3': 1e9, 'phi': 10.0, 'drho': 1e-4},
            2: {'grho3': 5e7, 'phi': 60.0, 'drho': 5e-5},
            3: {'grho3': 9.4e7, 'phi': 90.0, 'drho': float('inf')},
        }
        result = self.engine.forward_calc(layers, [3, 5, 7])
        for n in [3, 5, 7]:
            assert result[n]['delf'] < 0, f"n={n}: delf should be negative"
            assert result[n]['delg'] > 0, f"n={n}: delg should be positive"

    def test_three_layer_differs_from_two(self):
        """Inserting an extra layer between film and liquid changes result."""
        two_layer = {
            1: {'grho3': 1e9, 'phi': 10.0, 'drho': 1e-4},
            2: {'grho3': 9.4e7, 'phi': 90.0, 'drho': float('inf')},
        }
        three_layer = {
            1: {'grho3': 1e9, 'phi': 10.0, 'drho': 1e-4},
            2: {'grho3': 5e7, 'phi': 60.0, 'drho': 5e-5},
            3: {'grho3': 9.4e7, 'phi': 90.0, 'drho': float('inf')},
        }
        r2 = self.engine.forward_calc(two_layer, [3, 5, 7])
        r3 = self.engine.forward_calc(three_layer, [3, 5, 7])
        for n in [3, 5, 7]:
            assert abs(r3[n]['delf'] - r2[n]['delf']) > 0.1, (
                f"n={n}: three-layer delf too close to two-layer"
            )
            assert abs(r3[n]['delg'] - r2[n]['delg']) > 0.1, (
                f"n={n}: three-layer delg too close to two-layer"
            )

    def test_higher_harmonics_film_resonance(self):
        """Viscoelastic film in liquid: at high harmonics the film nears
        resonance, causing delf to approach zero or go positive and delg
        to peak then decrease. Verify this non-monotonic behavior."""
        layers = {
            1: {'grho3': 5e8, 'phi': 25.0, 'drho': 1.2e-4},
            2: {'grho3': 9.4e7, 'phi': 90.0, 'drho': float('inf')},
        }
        result = self.engine.forward_calc(layers, [3, 5, 7, 9, 11])
        # delf should become less negative at higher harmonics
        assert result[3]['delf'] < result[9]['delf'], (
            "Near-resonance: delf at n=9 should be less negative than n=3"
        )
        # delg should show a maximum (non-monotonic)
        delg_vals = [result[n]['delg'] for n in [3, 5, 7, 9, 11]]
        max_idx = delg_vals.index(max(delg_vals))
        assert 0 < max_idx < len(delg_vals) - 1, (
            f"delg should peak at an interior harmonic, max at index {max_idx}"
        )


class TestInverse:
    """Inverse problem: forward-compute with known properties, then
    inverse-solve with a different initial guess, and verify recovery."""

    def setup_method(self):
        import qcm_engine
        self.engine = qcm_engine

    def test_single_layer_round_trip(self):
        true_props = {'grho3': 3e8, 'phi': 25.0, 'drho': 8e-5}
        true_layers = {1: true_props}
        harmonics = [3, 5, 7]

        measurements = self.engine.forward_calc(true_layers, harmonics)

        init_layers = {1: {'grho3': 1e9, 'phi': 45.0, 'drho': 1e-4}}
        solved = self.engine.inverse_calc(
            measurements,
            harmonics_f=[3, 5, 7],
            harmonics_g=[3, 5, 7],
            unknowns=['grho3_1', 'phi_1', 'drho_1'],
            layers_init=init_layers,
            bounds={
                'grho3_1': (1e6, 1e12),
                'phi_1': (0.0, 89.0),
                'drho_1': (1e-6, 1e-2),
            },
        )

        assert abs(solved['grho3_1'] - 3e8) / 3e8 < 0.05, (
            f"grho3: expected ~3e8, got {solved['grho3_1']:.4e}"
        )
        assert abs(solved['phi_1'] - 25.0) < 2.0, (
            f"phi: expected ~25, got {solved['phi_1']:.2f}"
        )
        assert abs(solved['drho_1'] - 8e-5) / 8e-5 < 0.05, (
            f"drho: expected ~8e-5, got {solved['drho_1']:.4e}"
        )

    def test_film_in_liquid_round_trip(self):
        true_layers = {
            1: {'grho3': 2e8, 'phi': 35.0, 'drho': 1.5e-4},
            2: {'grho3': 9.4e7, 'phi': 90.0, 'drho': float('inf')},
        }
        harmonics = [3, 5, 7]

        measurements = self.engine.forward_calc(true_layers, harmonics)

        init_layers = {
            1: {'grho3': 5e8, 'phi': 50.0, 'drho': 2e-4},
            2: {'grho3': 9.4e7, 'phi': 90.0, 'drho': float('inf')},
        }
        solved = self.engine.inverse_calc(
            measurements,
            harmonics_f=[3, 5, 7],
            harmonics_g=[3, 5, 7],
            unknowns=['grho3_1', 'phi_1', 'drho_1'],
            layers_init=init_layers,
            bounds={
                'grho3_1': (1e6, 1e12),
                'phi_1': (0.0, 89.0),
                'drho_1': (1e-6, 1e-2),
            },
        )

        assert abs(solved['grho3_1'] - 2e8) / 2e8 < 0.05, (
            f"grho3: expected ~2e8, got {solved['grho3_1']:.4e}"
        )
        assert abs(solved['phi_1'] - 35.0) < 2.0, (
            f"phi: expected ~35, got {solved['phi_1']:.2f}"
        )
        assert abs(solved['drho_1'] - 1.5e-4) / 1.5e-4 < 0.05, (
            f"drho: expected ~1.5e-4, got {solved['drho_1']:.4e}"
        )

    def test_inverse_with_nonstandard_crystal(self):
        """Inverse solver must respect custom f1 and Zq parameters."""
        true_layers = {1: {'grho3': 4e8, 'phi': 20.0, 'drho': 6e-5}}
        harmonics = [3, 5, 7]

        measurements = self.engine.forward_calc(
            true_layers, harmonics, f1=F1_CRYSTAL
        )
        init_layers = {1: {'grho3': 1e9, 'phi': 40.0, 'drho': 1e-4}}
        solved = self.engine.inverse_calc(
            measurements,
            harmonics_f=harmonics,
            harmonics_g=harmonics,
            unknowns=['grho3_1', 'phi_1', 'drho_1'],
            layers_init=init_layers,
            f1=F1_CRYSTAL,
            bounds={
                'grho3_1': (1e6, 1e12),
                'phi_1': (0.0, 89.0),
                'drho_1': (1e-6, 1e-2),
            },
        )

        assert abs(solved['grho3_1'] - 4e8) / 4e8 < 0.05
        assert abs(solved['phi_1'] - 20.0) < 2.0
        assert abs(solved['drho_1'] - 6e-5) / 6e-5 < 0.05


class TestPipeline:
    """Verify the analysis pipeline correctly processes experiment data."""

    @pytest.fixture(autouse=True)
    def load_results(self):
        results_path = '/app/results.json'
        assert os.path.isfile(results_path), (
            "Pipeline must produce /app/results.json"
        )
        with open(results_path) as f:
            self.results = json.load(f)

    def test_all_experiments_present(self):
        for exp in ['water_cal', 'rigid_film', 'polymer_coating']:
            assert exp in self.results, f"Missing experiment: {exp}"

    def test_calibration_keys(self):
        cal = self.results['water_cal']
        for key in ['fitted_grho3', 'known_grho3', 'relative_error']:
            assert key in cal, f"Calibration missing key: {key}"

    def test_calibration_accuracy(self):
        cal = self.results['water_cal']
        assert abs(cal['fitted_grho3'] - 9.4e7) / 9.4e7 < 0.02, (
            f"Calibration grho3 off: {cal['fitted_grho3']:.4e} vs 9.4e7"
        )
        assert cal['relative_error'] < 0.02

    def test_rigid_film_keys(self):
        film = self.results['rigid_film']
        assert 'sauerbrey_drho' in film, "Rigid film missing sauerbrey_drho"

    def test_rigid_film_drho_with_correct_f1(self):
        """Sauerbrey drho must use f1 from crystal.toml, not default 5 MHz.
        With f1=4.95e6: drho=5.0000e-5; with f1=5e6: drho=4.9005e-5.
        Tight tolerance catches wrong f1."""
        film = self.results['rigid_film']
        expected = 5.0e-5
        assert abs(film['sauerbrey_drho'] - expected) / expected < 0.005, (
            f"Sauerbrey drho {film['sauerbrey_drho']:.6e} vs expected {expected:.6e}"
        )

    def test_polymer_coating_keys(self):
        coating = self.results['polymer_coating']
        for key in ['grho3', 'phi', 'drho']:
            assert key in coating, f"Polymer coating missing key: {key}"

    def test_polymer_coating_grho3(self):
        coating = self.results['polymer_coating']
        assert abs(coating['grho3'] - 5e8) / 5e8 < 0.05, (
            f"grho3: expected ~5e8, got {coating['grho3']:.4e}"
        )

    def test_polymer_coating_phi(self):
        coating = self.results['polymer_coating']
        assert abs(coating['phi'] - 25.0) < 2.0, (
            f"phi: expected ~25, got {coating['phi']:.2f}"
        )

    def test_polymer_coating_drho(self):
        coating = self.results['polymer_coating']
        assert abs(coating['drho'] - 1.2e-4) / 1.2e-4 < 0.05, (
            f"drho: expected ~1.2e-4, got {coating['drho']:.4e}"
        )

    def test_polymer_coating_self_consistency(self):
        """Forward model with fitted parameters must reproduce input data."""
        import qcm_engine
        coating = self.results['polymer_coating']

        # Read and convert original measurements
        measurements = {}
        with open('/app/data/polymer_coating/measurements.csv') as f:
            reader = csv.DictReader(f)
            for row in reader:
                n = int(row['harmonic'])
                delf = float(row['delf_hz'])
                delta_D = float(row['delta_D_1e6'])
                delg = delta_D * 1e-6 * n * F1_CRYSTAL / 2.0
                measurements[n] = {'delf': delf, 'delg': delg}

        layers = {
            1: {
                'grho3': coating['grho3'],
                'phi': coating['phi'],
                'drho': coating['drho'],
            },
            2: {'grho3': 9.4e7, 'phi': 90.0, 'drho': float('inf')},
        }
        computed = qcm_engine.forward_calc(
            layers, sorted(measurements.keys()), f1=F1_CRYSTAL
        )

        for n in measurements:
            delf_err = abs(computed[n]['delf'] - measurements[n]['delf'])
            scale_f = max(abs(measurements[n]['delf']), 1.0)
            assert delf_err / scale_f < 0.03, (
                f"n={n}: delf mismatch {computed[n]['delf']:.2f} "
                f"vs {measurements[n]['delf']:.2f}"
            )
            delg_err = abs(computed[n]['delg'] - measurements[n]['delg'])
            scale_g = max(abs(measurements[n]['delg']), 1.0)
            assert delg_err / scale_g < 0.03, (
                f"n={n}: delg mismatch {computed[n]['delg']:.2f} "
                f"vs {measurements[n]['delg']:.2f}"
            )
