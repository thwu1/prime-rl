"""Tests for QCM-D analysis library with C shared library and CLI tool."""


import pytest
import cmath
import math
import json
import subprocess
import os
import sys
import ctypes

sys.path.insert(0, "/app")


class TestCLibrary:
    """Test the C shared library directly via ctypes."""

    def test_libqcm_exists(self):
        assert os.path.exists("/app/libqcm_transfer.so"), \
            "C library not found: /app/libqcm_transfer.so"

    def test_libqcm_loads_and_has_symbol(self):
        lib = ctypes.CDLL("/app/libqcm_transfer.so")
        assert hasattr(lib, "qcm_delfstar"), \
            "C library missing qcm_delfstar symbol"

    def _call_c_delfstar(self, n, nlayers, grho3_list, phi_list, drho_list):
        lib = ctypes.CDLL("/app/libqcm_transfer.so")
        lib.qcm_delfstar.argtypes = [
            ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_double, ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
        ]
        lib.qcm_delfstar.restype = None

        grho3 = (ctypes.c_double * nlayers)(*grho3_list)
        phi = (ctypes.c_double * nlayers)(*phi_list)
        drho = (ctypes.c_double * nlayers)(*drho_list)
        out_delf = ctypes.c_double()
        out_delg = ctypes.c_double()

        lib.qcm_delfstar(n, nlayers, grho3, phi, drho,
                         5e6, 8.84e6,
                         ctypes.byref(out_delf), ctypes.byref(out_delg))
        return out_delf.value, out_delg.value

    def test_c_single_rigid_film_n3(self):
        delf, delg = self._call_c_delfstar(3, 1, [1e12], [0.01], [1e-4])
        assert abs(delf - (-1696.883)) < 0.01

    def test_c_single_rigid_film_n5(self):
        delf, delg = self._call_c_delfstar(5, 1, [1e12], [0.01], [1e-4])
        assert abs(delf - (-2828.287)) < 0.01

    def test_c_bulk_liquid_n3(self):
        delf, delg = self._call_c_delfstar(3, 1, [9.4e7], [90.0], [1e200])
        assert abs(delf - (-1234.289)) < 0.1
        assert abs(delg - 1234.289) < 0.1

    def test_c_two_layer_film_liquid_n3(self):
        delf, delg = self._call_c_delfstar(
            3, 2, [1e9, 9.4e7], [30.0, 90.0], [5e-4, 1e200])
        assert abs(delf - (-2212.138)) < 0.1
        assert abs(delg - 9687.850) < 0.1

    def test_c_two_layer_film_liquid_n5(self):
        delf, delg = self._call_c_delfstar(
            5, 2, [1e9, 9.4e7], [30.0, 90.0], [5e-4, 1e200])
        assert abs(delf - 373.472) < 0.1
        assert abs(delg - 6010.856) < 0.1

    def test_c_three_layer_n3(self):
        delf, delg = self._call_c_delfstar(
            3, 3, [2e9, 8e8, 9.4e7], [20.0, 40.0, 90.0],
            [1e-4, 2e-4, 1e200])
        assert isinstance(delf, float) and delf != 0
        assert isinstance(delg, float) and delg != 0


class TestCtypesIntegration:
    """Verify qcm_analysis.py uses ctypes to load the C library."""

    def test_module_uses_ctypes(self):
        import importlib
        import inspect
        source = inspect.getsource(importlib.import_module('qcm_analysis'))
        assert 'ctypes' in source, \
            "qcm_analysis.py must use ctypes to load the C library"
        assert 'libqcm_transfer' in source, \
            "qcm_analysis.py must reference libqcm_transfer.so"

    def test_calc_delfstar_agrees_with_c_direct(self):
        """calc_delfstar Python wrapper must agree with direct C call."""
        from qcm_analysis import calc_delfstar
        lib = ctypes.CDLL("/app/libqcm_transfer.so")
        lib.qcm_delfstar.argtypes = [
            ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_double, ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
        ]
        lib.qcm_delfstar.restype = None

        layers = {
            1: {"grho3": 1e9, "phi": 30.0, "drho": 5e-4},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        for n in [3, 5, 7]:
            py_result = calc_delfstar(n, layers)
            grho3 = (ctypes.c_double * 2)(1e9, 9.4e7)
            phi = (ctypes.c_double * 2)(30.0, 90.0)
            drho = (ctypes.c_double * 2)(5e-4, 1e200)
            out_delf = ctypes.c_double()
            out_delg = ctypes.c_double()
            lib.qcm_delfstar(n, 2, grho3, phi, drho, 5e6, 8.84e6,
                             ctypes.byref(out_delf), ctypes.byref(out_delg))
            assert abs(py_result.real - out_delf.value) < 1e-6
            assert abs(py_result.imag - out_delg.value) < 1e-6


class TestSauerbreyMass:
    """Test the Sauerbrey mass calculation."""

    def test_sauerbrey_n3_basic(self):
        from qcm_analysis import sauerbrey_mass
        result = sauerbrey_mass(3, -100.0)
        expected = 100.0 * 8.84e6 / (2 * 3 * (5e6)**2)
        assert abs(result - expected) / expected < 1e-10

    def test_sauerbrey_n5(self):
        from qcm_analysis import sauerbrey_mass
        result = sauerbrey_mass(5, -250.0)
        expected = 250.0 * 8.84e6 / (2 * 5 * (5e6)**2)
        assert abs(result - expected) / expected < 1e-10

    def test_sauerbrey_positive_delf_negative_mass(self):
        from qcm_analysis import sauerbrey_mass
        result = sauerbrey_mass(3, 50.0)
        assert result < 0

    def test_sauerbrey_zero_shift(self):
        from qcm_analysis import sauerbrey_mass
        result = sauerbrey_mass(3, 0.0)
        assert result == 0.0

    def test_sauerbrey_scales_inversely_with_n(self):
        from qcm_analysis import sauerbrey_mass
        delf = -100.0
        m3 = sauerbrey_mass(3, delf)
        m5 = sauerbrey_mass(5, delf)
        assert abs(m3 / m5 - 5 / 3) < 1e-10


class TestGrho:
    """Test the power-law |G*|rho scaling."""

    def test_grho_at_n3_equals_grho3(self):
        from qcm_analysis import grho
        result = grho(3, 1e9, 30.0)
        assert abs(result - 1e9) / 1e9 < 1e-10

    def test_grho_power_law_n5(self):
        from qcm_analysis import grho
        result = grho(5, 1e9, 30.0)
        expected = 1e9 * (5 / 3) ** (30.0 / 90.0)
        assert abs(result - expected) / expected < 1e-10

    def test_grho_power_law_n7(self):
        from qcm_analysis import grho
        result = grho(7, 1e9, 30.0)
        expected = 1e9 * (7 / 3) ** (30.0 / 90.0)
        assert abs(result - expected) / expected < 1e-10

    def test_grho_phi_zero_constant(self):
        from qcm_analysis import grho
        for n in [1, 3, 5, 7, 9]:
            result = grho(n, 1e9, 0.0)
            assert abs(result - 1e9) / 1e9 < 1e-10

    def test_grho_phi_90_linear(self):
        from qcm_analysis import grho
        result = grho(9, 1e9, 90.0)
        expected = 1e9 * 3.0
        assert abs(result - expected) / expected < 1e-10

    def test_grho_n1(self):
        from qcm_analysis import grho
        result = grho(1, 1e9, 30.0)
        expected = 1e9 * (1 / 3) ** (30.0 / 90.0)
        assert abs(result - expected) / expected < 1e-10


class TestZstarBulk:
    """Test complex acoustic impedance calculation."""

    def test_zstar_returns_complex(self):
        from qcm_analysis import zstar_bulk
        result = zstar_bulk(3, 1e9, 30.0)
        assert isinstance(result, complex)

    def test_zstar_n3_values(self):
        from qcm_analysis import zstar_bulk
        result = zstar_bulk(3, 1e9, 30.0)
        gstar = 1e9 * cmath.exp(1j * math.pi * 30 / 180)
        expected = cmath.sqrt(gstar)
        assert abs(result - expected) / abs(expected) < 1e-10

    def test_zstar_n5_values(self):
        from qcm_analysis import zstar_bulk
        result = zstar_bulk(5, 1e9, 30.0)
        grho_val = 1e9 * (5 / 3) ** (30.0 / 90.0)
        gstar = grho_val * cmath.exp(1j * math.pi * 30 / 180)
        expected = cmath.sqrt(gstar)
        assert abs(result - expected) / abs(expected) < 1e-10

    def test_zstar_phi0_real(self):
        from qcm_analysis import zstar_bulk
        result = zstar_bulk(3, 1e9, 0.0)
        assert abs(result.imag) / abs(result) < 1e-6

    def test_zstar_phi90_equal_parts(self):
        from qcm_analysis import zstar_bulk
        result = zstar_bulk(3, 1e9, 90.0)
        phase = cmath.phase(result)
        assert abs(phase - math.pi / 4) < 1e-6


class TestCalcDelfstar:
    """Test forward calculation of complex frequency shifts."""

    def test_thin_rigid_film_matches_sauerbrey(self):
        from qcm_analysis import calc_delfstar
        layers = {1: {"grho3": 1e12, "phi": 0.01, "drho": 1e-4}}
        for n in [3, 5, 7]:
            result = calc_delfstar(n, layers)
            sauerbrey_delf = -2 * n * (5e6)**2 * 1e-4 / 8.84e6
            assert abs(result.real - sauerbrey_delf) / abs(sauerbrey_delf) < 0.01
            assert abs(result.imag) < abs(result.real) * 0.001

    def test_thin_rigid_film_n3_precise(self):
        from qcm_analysis import calc_delfstar
        layers = {1: {"grho3": 1e12, "phi": 0.01, "drho": 1e-4}}
        result = calc_delfstar(3, layers)
        assert abs(result.real - (-1696.883)) < 0.01

    def test_thin_rigid_film_n5_precise(self):
        from qcm_analysis import calc_delfstar
        layers = {1: {"grho3": 1e12, "phi": 0.01, "drho": 1e-4}}
        result = calc_delfstar(5, layers)
        assert abs(result.real - (-2828.287)) < 0.01

    def test_bulk_liquid_delf_equals_neg_delg(self):
        from qcm_analysis import calc_delfstar
        layers = {1: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")}}
        for n in [3, 5, 7]:
            result = calc_delfstar(n, layers)
            assert abs(result.real + result.imag) / abs(result.real) < 1e-6

    def test_bulk_liquid_n3_values(self):
        from qcm_analysis import calc_delfstar
        layers = {1: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")}}
        result = calc_delfstar(3, layers)
        assert abs(result.real - (-1234.289)) < 0.1
        assert abs(result.imag - 1234.289) < 0.1

    def test_film_plus_liquid_n3(self):
        from qcm_analysis import calc_delfstar
        layers = {
            1: {"grho3": 1e9, "phi": 30.0, "drho": 5e-4},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        result = calc_delfstar(3, layers)
        assert abs(result.real - (-2212.138)) < 0.1
        assert abs(result.imag - 9687.850) < 0.1

    def test_film_plus_liquid_n5(self):
        from qcm_analysis import calc_delfstar
        layers = {
            1: {"grho3": 1e9, "phi": 30.0, "drho": 5e-4},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        result = calc_delfstar(5, layers)
        assert abs(result.real - 373.472) < 0.1
        assert abs(result.imag - 6010.856) < 0.1

    def test_film_plus_liquid_n7(self):
        from qcm_analysis import calc_delfstar
        layers = {
            1: {"grho3": 1e9, "phi": 30.0, "drho": 5e-4},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        result = calc_delfstar(7, layers)
        assert abs(result.real - (-1380.189)) < 0.1
        assert abs(result.imag - 5138.877) < 0.1

    def test_single_viscoelastic_film_n3(self):
        from qcm_analysis import calc_delfstar
        layers = {1: {"grho3": 5e8, "phi": 15.0, "drho": 2e-4}}
        result = calc_delfstar(3, layers)
        assert abs(result.real - (-4425.137)) < 0.1
        assert abs(result.imag - 392.578) < 0.1

    def test_frequency_shift_scales_with_drho(self):
        from qcm_analysis import calc_delfstar
        layers1 = {1: {"grho3": 1e12, "phi": 0.01, "drho": 1e-5}}
        layers2 = {1: {"grho3": 1e12, "phi": 0.01, "drho": 2e-5}}
        r1 = calc_delfstar(3, layers1)
        r2 = calc_delfstar(3, layers2)
        assert abs(r2.real / r1.real - 2.0) < 0.01


class TestThreeLayerStack:
    """Test forward calculation with 3-layer stacks."""

    def test_three_layer_vanishing_middle_matches_two_layer(self):
        from qcm_analysis import calc_delfstar
        layers_3 = {
            1: {"grho3": 1e9, "phi": 30.0, "drho": 5e-4},
            2: {"grho3": 1e12, "phi": 0.01, "drho": 1e-12},
            3: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        layers_2 = {
            1: {"grho3": 1e9, "phi": 30.0, "drho": 5e-4},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        for n in [3, 5, 7]:
            r3 = calc_delfstar(n, layers_3)
            r2 = calc_delfstar(n, layers_2)
            assert abs(r3.real - r2.real) / max(abs(r2.real), 1.0) < 0.001
            assert abs(r3.imag - r2.imag) / max(abs(r2.imag), 1.0) < 0.001

    def test_three_layer_substantial_middle_differs(self):
        from qcm_analysis import calc_delfstar
        layers_3 = {
            1: {"grho3": 1e9, "phi": 30.0, "drho": 5e-4},
            2: {"grho3": 5e8, "phi": 45.0, "drho": 3e-4},
            3: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        layers_2 = {
            1: {"grho3": 1e9, "phi": 30.0, "drho": 5e-4},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        for n in [3, 5, 7]:
            r3 = calc_delfstar(n, layers_3)
            r2 = calc_delfstar(n, layers_2)
            assert abs(r3 - r2) / abs(r2) > 0.01

    def test_three_layer_returns_complex(self):
        from qcm_analysis import calc_delfstar
        layers = {
            1: {"grho3": 2e9, "phi": 20.0, "drho": 1e-4},
            2: {"grho3": 8e8, "phi": 40.0, "drho": 2e-4},
            3: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        result = calc_delfstar(3, layers)
        assert isinstance(result, complex)
        assert result.real != 0
        assert result.imag != 0

    def test_three_layer_overtone_dependence(self):
        from qcm_analysis import calc_delfstar
        layers = {
            1: {"grho3": 2e9, "phi": 20.0, "drho": 1e-4},
            2: {"grho3": 8e8, "phi": 40.0, "drho": 2e-4},
            3: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        r3 = calc_delfstar(3, layers)
        r5 = calc_delfstar(5, layers)
        r7 = calc_delfstar(7, layers)
        ratio_35 = r5.real / r3.real
        ratio_37 = r7.real / r3.real
        assert abs(ratio_35 - 5 / 3) > 0.01 or abs(ratio_37 - 7 / 3) > 0.01


class TestComputeSensitivity:
    """Test sensitivity (numerical derivative) calculations."""

    def test_sensitivity_returns_complex(self):
        from qcm_analysis import compute_sensitivity
        layers = {1: {"grho3": 1e9, "phi": 30.0, "drho": 1e-4}}
        result = compute_sensitivity(3, layers, "drho", 1)
        assert isinstance(result, complex)

    def test_sensitivity_drho_sauerbrey_limit(self):
        from qcm_analysis import compute_sensitivity
        layers = {1: {"grho3": 1e12, "phi": 0.01, "drho": 1e-4}}
        sens = compute_sensitivity(3, layers, "drho", 1)
        expected_sauerbrey = -2 * 3 * (5e6)**2 / 8.84e6
        assert abs(sens.real - expected_sauerbrey) / abs(expected_sauerbrey) < 0.01

    def test_sensitivity_phi_nonzero_for_viscoelastic(self):
        from qcm_analysis import compute_sensitivity
        layers = {
            1: {"grho3": 1e9, "phi": 30.0, "drho": 5e-4},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        sens = compute_sensitivity(3, layers, "phi", 1)
        assert abs(sens) > 1.0

    def test_sensitivity_grho3_nonzero(self):
        from qcm_analysis import compute_sensitivity
        layers = {
            1: {"grho3": 1e9, "phi": 30.0, "drho": 5e-4},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        sens = compute_sensitivity(3, layers, "grho3", 1)
        assert abs(sens) > 0

    def test_sensitivity_drho_imaginary_negligible_rigid(self):
        from qcm_analysis import compute_sensitivity
        layers = {1: {"grho3": 1e12, "phi": 0.01, "drho": 1e-4}}
        sens = compute_sensitivity(3, layers, "drho", 1)
        assert abs(sens.imag) < abs(sens.real) * 0.01

    def test_sensitivity_layer2_liquid(self):
        from qcm_analysis import compute_sensitivity
        layers = {
            1: {"grho3": 1e9, "phi": 30.0, "drho": 5e-4},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        sens = compute_sensitivity(3, layers, "grho3", layer_idx=2)
        assert abs(sens) > 0


class TestSolveInverse:
    """Test inverse problem solver."""

    def _generate_synthetic_data(self, layers, harmonics):
        from qcm_analysis import calc_delfstar
        delfstar = {}
        for n in harmonics:
            val = calc_delfstar(n, layers)
            delfstar[n] = val
        return delfstar

    def test_inverse_single_layer_recovers_drho(self):
        from qcm_analysis import solve_inverse
        true_props = {"grho3": 2e9, "phi": 20.0, "drho": 1e-4}
        layers_true = {
            1: true_props,
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        delfstar = self._generate_synthetic_data(layers_true, [3, 5, 7])
        layers_init = {
            1: {"grho3": 5e9, "phi": 10.0, "drho": 5e-5},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        result = solve_inverse(delfstar, [3, 5], [7], layers_init)
        assert abs(result["drho"] - true_props["drho"]) / true_props["drho"] < 0.05

    def test_inverse_recovers_grho3(self):
        from qcm_analysis import solve_inverse
        true_props = {"grho3": 2e9, "phi": 20.0, "drho": 1e-4}
        layers_true = {
            1: true_props,
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        delfstar = self._generate_synthetic_data(layers_true, [3, 5, 7])
        layers_init = {
            1: {"grho3": 5e9, "phi": 10.0, "drho": 5e-5},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        result = solve_inverse(delfstar, [3, 5], [7], layers_init)
        assert abs(result["grho3"] - true_props["grho3"]) / true_props["grho3"] < 0.1

    def test_inverse_recovers_phi(self):
        from qcm_analysis import solve_inverse
        true_props = {"grho3": 2e9, "phi": 20.0, "drho": 1e-4}
        layers_true = {
            1: true_props,
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        delfstar = self._generate_synthetic_data(layers_true, [3, 5, 7])
        layers_init = {
            1: {"grho3": 5e9, "phi": 10.0, "drho": 5e-5},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        result = solve_inverse(delfstar, [3, 5], [7], layers_init)
        assert abs(result["phi"] - true_props["phi"]) < 3.0

    def test_inverse_different_properties(self):
        from qcm_analysis import solve_inverse
        true_props = {"grho3": 5e8, "phi": 40.0, "drho": 3e-4}
        layers_true = {
            1: true_props,
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        delfstar = self._generate_synthetic_data(layers_true, [3, 5, 7])
        layers_init = {
            1: {"grho3": 1e9, "phi": 20.0, "drho": 1e-4},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        result = solve_inverse(delfstar, [3, 5], [7], layers_init)
        assert abs(result["drho"] - true_props["drho"]) / true_props["drho"] < 0.1
        assert abs(result["grho3"] - true_props["grho3"]) / true_props["grho3"] < 0.15

    def test_inverse_five_harmonics(self):
        from qcm_analysis import solve_inverse, calc_delfstar
        true_props = {"grho3": 1e9, "phi": 35.0, "drho": 2e-4}
        layers_true = {
            1: true_props,
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        delfstar = {}
        for n in [3, 5, 7, 9, 11]:
            delfstar[n] = calc_delfstar(n, layers_true)
        layers_init = {
            1: {"grho3": 3e9, "phi": 15.0, "drho": 8e-5},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        result = solve_inverse(delfstar, [3, 5, 7], [9, 11], layers_init)
        assert abs(result["drho"] - true_props["drho"]) / true_props["drho"] < 0.05
        assert abs(result["grho3"] - true_props["grho3"]) / true_props["grho3"] < 0.1
        assert abs(result["phi"] - true_props["phi"]) < 3.0

    def test_inverse_roundtrip_residual(self):
        from qcm_analysis import solve_inverse, calc_delfstar
        true_props = {"grho3": 2e9, "phi": 20.0, "drho": 1e-4}
        layers_true = {
            1: true_props,
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        delfstar = self._generate_synthetic_data(layers_true, [3, 5, 7])
        layers_init = {
            1: {"grho3": 5e9, "phi": 10.0, "drho": 5e-5},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        result = solve_inverse(delfstar, [3, 5], [7], layers_init)
        layers_recovered = {
            1: {"grho3": result["grho3"], "phi": result["phi"],
                "drho": result["drho"]},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        max_residual = 0
        for n in [3, 5, 7]:
            calc = calc_delfstar(n, layers_recovered)
            max_residual = max(max_residual,
                               abs(calc.real - delfstar[n].real))
            max_residual = max(max_residual,
                               abs(calc.imag - delfstar[n].imag))
        assert max_residual < 1.0


class TestCLIForward:
    """Test the CLI tool in forward mode."""

    def test_cli_forward_basic(self):
        input_data = {
            "mode": "forward",
            "harmonics": [3, 5, 7],
            "layers": {
                "1": {"grho3": 1e12, "phi": 0.01, "drho": 1e-4}
            },
        }
        input_path = "/tmp/test_cli_fwd_input.json"
        output_path = "/tmp/test_cli_fwd_output.json"
        with open(input_path, "w") as f:
            json.dump(input_data, f)

        result = subprocess.run(
            ["python3", "/app/qcm_cli.py", "--input", input_path,
             "--output", output_path],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(output_path) as f:
            output = json.load(f)

        assert "delfstar" in output
        assert "3" in output["delfstar"]
        assert "5" in output["delfstar"]
        assert "7" in output["delfstar"]
        delf3 = output["delfstar"]["3"][0]
        assert abs(delf3 - (-1696.883)) < 0.1

    def test_cli_forward_two_layers(self):
        input_data = {
            "mode": "forward",
            "harmonics": [3, 5],
            "layers": {
                "1": {"grho3": 1e9, "phi": 30.0, "drho": 5e-4},
                "2": {"grho3": 9.4e7, "phi": 90.0, "drho": 1e300},
            },
        }
        input_path = "/tmp/test_cli_fwd2_input.json"
        output_path = "/tmp/test_cli_fwd2_output.json"
        with open(input_path, "w") as f:
            json.dump(input_data, f)

        result = subprocess.run(
            ["python3", "/app/qcm_cli.py", "--input", input_path,
             "--output", output_path],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(output_path) as f:
            output = json.load(f)

        delf3 = output["delfstar"]["3"][0]
        delg3 = output["delfstar"]["3"][1]
        assert abs(delf3 - (-2212.138)) < 1.0
        assert abs(delg3 - 9687.850) < 1.0


class TestCLIInverse:
    """Test the CLI tool in inverse mode."""

    def test_cli_inverse_basic(self):
        input_fwd = {
            "mode": "forward",
            "harmonics": [3, 5, 7],
            "layers": {
                "1": {"grho3": 2e9, "phi": 20.0, "drho": 1e-4},
                "2": {"grho3": 9.4e7, "phi": 90.0, "drho": 1e300},
            },
        }
        fwd_in = "/tmp/test_cli_inv_fwd_in.json"
        fwd_out = "/tmp/test_cli_inv_fwd_out.json"
        with open(fwd_in, "w") as f:
            json.dump(input_fwd, f)

        subprocess.run(
            ["python3", "/app/qcm_cli.py", "--input", fwd_in,
             "--output", fwd_out],
            capture_output=True, text=True, timeout=30,
        )
        with open(fwd_out) as f:
            fwd_data = json.load(f)

        input_inv = {
            "mode": "inverse",
            "layers": {
                "1": {"grho3": 5e9, "phi": 10.0, "drho": 5e-5},
                "2": {"grho3": 9.4e7, "phi": 90.0, "drho": 1e300},
            },
            "delfstar_expt": fwd_data["delfstar"],
            "harmonics_f": [3, 5],
            "harmonics_g": [7],
        }
        inv_in = "/tmp/test_cli_inv_input.json"
        inv_out = "/tmp/test_cli_inv_output.json"
        with open(inv_in, "w") as f:
            json.dump(input_inv, f)

        result = subprocess.run(
            ["python3", "/app/qcm_cli.py", "--input", inv_in,
             "--output", inv_out],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(inv_out) as f:
            output = json.load(f)

        assert "solution" in output
        assert "residual_hz" in output
        assert abs(output["solution"]["drho"] - 1e-4) / 1e-4 < 0.1
        assert output["residual_hz"] < 1.0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_thin_film_approaches_sauerbrey(self):
        from qcm_analysis import calc_delfstar
        drho = 1e-6
        layers = {1: {"grho3": 1e10, "phi": 5.0, "drho": drho}}
        result = calc_delfstar(3, layers)
        sauerbrey_delf = -2 * 3 * (5e6)**2 * drho / 8.84e6
        assert abs(result.real - sauerbrey_delf) / abs(sauerbrey_delf) < 0.001

    def test_constants_correct(self):
        from qcm_analysis import Zq, f1
        assert Zq == 8.84e6
        assert f1 == 5e6

    def test_delfstar_returns_complex(self):
        from qcm_analysis import calc_delfstar
        layers = {1: {"grho3": 1e9, "phi": 30.0, "drho": 1e-4}}
        result = calc_delfstar(3, layers)
        assert isinstance(result, complex)

    def test_solve_inverse_returns_dict_with_keys(self):
        from qcm_analysis import solve_inverse, calc_delfstar
        true_props = {"grho3": 2e9, "phi": 20.0, "drho": 1e-4}
        layers_true = {
            1: true_props,
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        delfstar = {}
        for n in [3, 5, 7]:
            delfstar[n] = calc_delfstar(n, layers_true)
        layers_init = {
            1: {"grho3": 5e9, "phi": 10.0, "drho": 5e-5},
            2: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")},
        }
        result = solve_inverse(delfstar, [3, 5], [7], layers_init)
        assert "grho3" in result
        assert "phi" in result
        assert "drho" in result

    def test_bulk_liquid_frequency_scales_with_sqrt_n(self):
        from qcm_analysis import calc_delfstar
        layers = {1: {"grho3": 9.4e7, "phi": 90.0, "drho": float("inf")}}
        r3 = calc_delfstar(3, layers)
        r5 = calc_delfstar(5, layers)
        ratio = abs(r5.real) / abs(r3.real)
        expected_ratio = math.sqrt(5 / 3)
        assert abs(ratio - expected_ratio) / expected_ratio < 0.01
