"""Tests for thin-film optics TMM engine: bug fixes, C kernel, ctypes FFI,
inc_tmm, results JSON, SQLite output, and Makefile.

Verifies the engine against independently computed (Mathematica) golden values,
checks physical consistency, validates the C shared library, ctypes integration,
inc_tmm, analysis results in JSON and SQLite, and Makefile targets.
"""

import sys
import json
import pytest
import numpy as np
from numpy import inf, pi

sys.path.insert(0, '/app')


# ---------------------------------------------------------------------------
# Golden-value tests for coh_tmm (verified against Mathematica)
# ---------------------------------------------------------------------------

class TestCohTmmGoldenS:
    """Verify s-polarization coh_tmm against Mathematica golden values."""

    @pytest.fixture(autouse=True)
    def setup(self):
        import tmm_engine
        self.data = tmm_engine.coh_tmm(
            's',
            [1, 2 + 4j, 3 + 0.3j, 1 + 0.1j],
            [inf, 2, 3, inf],
            0.1,
            100,
        )

    def test_reflection_amplitude(self):
        expected = -0.60331226568845775 - 0.093522181653632019j
        assert abs(self.data['r'] - expected) < 1e-6

    def test_transmission_amplitude(self):
        expected = 0.44429533471192989 + 0.16921936169383078j
        assert abs(self.data['t'] - expected) < 1e-6

    def test_reflectance(self):
        assert abs(self.data['R'] - 0.37273208839139516) < 1e-6

    def test_transmittance(self):
        assert abs(self.data['T'] - 0.22604491247079261) < 1e-6


class TestCohTmmGoldenP:
    """Verify p-polarization coh_tmm against Mathematica golden values."""

    @pytest.fixture(autouse=True)
    def setup(self):
        import tmm_engine
        self.data = tmm_engine.coh_tmm(
            'p',
            [1, 2 + 4j, 3 + 0.3j, 1 + 0.1j],
            [inf, 2, 3, inf],
            0.1,
            100,
        )

    def test_reflection_amplitude(self):
        expected = 0.60102654255772481 + 0.094489146845323682j
        assert abs(self.data['r'] - expected) < 1e-6

    def test_transmission_amplitude(self):
        expected = 0.4461816467503148 + 0.17061408427088917j
        assert abs(self.data['t'] - expected) < 1e-6

    def test_reflectance(self):
        assert abs(self.data['R'] - 0.37016110373044969) < 1e-6

    def test_transmittance(self):
        assert abs(self.data['T'] - 0.22824374314132009) < 1e-6


# ---------------------------------------------------------------------------
# Ellipsometry golden values
# ---------------------------------------------------------------------------

class TestEllipsometry:
    def test_psi(self):
        import tmm_engine
        data = tmm_engine.ellips(
            [1, 2 + 4j, 3 + 0.3j, 1 + 0.1j],
            [inf, 2, 3, inf],
            0.1,
            100,
        )
        assert abs(data['psi'] - 0.78366777347038352) < 1e-6

    def test_delta(self):
        import tmm_engine
        data = tmm_engine.ellips(
            [1, 2 + 4j, 3 + 0.3j, 1 + 0.1j],
            [inf, 2, 3, inf],
            0.1,
            100,
        )
        assert abs(data['Delta'] - 0.0021460774404193292) < 1e-6


# ---------------------------------------------------------------------------
# Position-resolved golden values (Mathematica)
# ---------------------------------------------------------------------------

class TestPositionResolved:
    @pytest.fixture(autouse=True)
    def setup(self):
        import tmm_engine
        self.tmm = tmm_engine
        self.n_list = [1, 2.2 + 0.2j, 3.3 + 0.3j, 1]
        self.d_list = [inf, 100, 300, inf]
        self.th_0 = pi / 4
        self.lam_vac = 400

    def test_kz_layer1(self):
        data = self.tmm.coh_tmm('p', self.n_list, self.d_list, self.th_0, self.lam_vac)
        expected = 0.0327410685922732 + 0.003315885921866465j
        assert abs(data['kz_list'][1] - expected) < 1e-6

    def test_p_poynting(self):
        data = self.tmm.coh_tmm('p', self.n_list, self.d_list, self.th_0, self.lam_vac)
        pr = self.tmm.position_resolved(1, 37, data)
        assert abs(pr['poyn'] - 0.7094950598055798) < 1e-5

    def test_p_absorption_density(self):
        data = self.tmm.coh_tmm('p', self.n_list, self.d_list, self.th_0, self.lam_vac)
        pr = self.tmm.position_resolved(1, 37, data)
        assert abs(pr['absor'] - 0.005135049118053356) < 1e-5

    def test_s_poynting(self):
        data = self.tmm.coh_tmm('s', self.n_list, self.d_list, self.th_0, self.lam_vac)
        pr = self.tmm.position_resolved(1, 37, data)
        assert abs(pr['poyn'] - 0.5422594735025152) < 1e-5

    def test_s_absorption_density(self):
        data = self.tmm.coh_tmm('s', self.n_list, self.d_list, self.th_0, self.lam_vac)
        pr = self.tmm.position_resolved(1, 37, data)
        assert abs(pr['absor'] - 0.004041912286816303) < 1e-5


# ---------------------------------------------------------------------------
# Physical consistency checks
# ---------------------------------------------------------------------------

class TestEnergyConservation:
    """Absorption in all layers must sum to 1."""

    @pytest.fixture(autouse=True)
    def setup(self):
        import tmm_engine
        self.tmm = tmm_engine

    def test_s_pol(self):
        data = self.tmm.coh_tmm(
            's', [1, 2.2 + 0.2j, 3.3 + 0.3j, 1], [inf, 100, 300, inf], pi / 4, 400,
        )
        absorp = self.tmm.absorp_in_each_layer(data)
        assert abs(sum(absorp) - 1.0) < 1e-6

    def test_p_pol(self):
        data = self.tmm.coh_tmm(
            'p', [1, 2.2 + 0.2j, 3.3 + 0.3j, 1], [inf, 100, 300, inf], pi / 4, 400,
        )
        absorp = self.tmm.absorp_in_each_layer(data)
        assert abs(sum(absorp) - 1.0) < 1e-6

    def test_s_pol_complex_incident(self):
        from numpy.lib.scimath import arcsin
        n0 = 1 + 0.1j
        th_0 = arcsin(1 * np.sin(pi / 4) / n0)
        data = self.tmm.coh_tmm(
            's', [n0, 2.2 + 0.2j, 3.3 + 0.3j, 1 + 0.4j],
            [inf, 100, 300, inf], th_0, 400,
        )
        absorp = self.tmm.absorp_in_each_layer(data)
        assert abs(sum(absorp) - 1.0) < 1e-6

    def test_p_pol_complex_incident(self):
        from numpy.lib.scimath import arcsin
        n0 = 1 + 0.1j
        th_0 = arcsin(1 * np.sin(pi / 4) / n0)
        data = self.tmm.coh_tmm(
            'p', [n0, 2.2 + 0.2j, 3.3 + 0.3j, 1 + 0.4j],
            [inf, 100, 300, inf], th_0, 400,
        )
        absorp = self.tmm.absorp_in_each_layer(data)
        assert abs(sum(absorp) - 1.0) < 1e-6


class TestPoyntingBoundary:
    """Poynting vector boundary conditions."""

    @pytest.fixture(autouse=True)
    def setup(self):
        import tmm_engine
        self.tmm = tmm_engine
        self.n_list = [1, 2.2 + 0.2j, 3.3 + 0.3j, 1]
        self.d_list = [inf, 100, 300, inf]

    def test_end_equals_T_s(self):
        data = self.tmm.coh_tmm('s', self.n_list, self.d_list, pi / 4, 400)
        pr = self.tmm.position_resolved(2, 300, data)
        assert abs(pr['poyn'] - data['T']) < 1e-6

    def test_end_equals_T_p(self):
        data = self.tmm.coh_tmm('p', self.n_list, self.d_list, pi / 4, 400)
        pr = self.tmm.position_resolved(2, 300, data)
        assert abs(pr['poyn'] - data['T']) < 1e-6

    def test_start_equals_power_entering_s(self):
        data = self.tmm.coh_tmm('s', self.n_list, self.d_list, pi / 4, 400)
        pr = self.tmm.position_resolved(1, 0, data)
        assert abs(pr['poyn'] - data['power_entering']) < 1e-6

    def test_start_equals_power_entering_p(self):
        data = self.tmm.coh_tmm('p', self.n_list, self.d_list, pi / 4, 400)
        pr = self.tmm.position_resolved(1, 0, data)
        assert abs(pr['poyn'] - data['power_entering']) < 1e-6

    def test_continuity_s(self):
        data = self.tmm.coh_tmm('s', self.n_list, self.d_list, pi / 4, 400)
        pr1 = self.tmm.position_resolved(1, 100, data)
        pr2 = self.tmm.position_resolved(2, 0, data)
        assert abs(pr1['poyn'] - pr2['poyn']) < 1e-6

    def test_continuity_p(self):
        data = self.tmm.coh_tmm('p', self.n_list, self.d_list, pi / 4, 400)
        pr1 = self.tmm.position_resolved(1, 100, data)
        pr2 = self.tmm.position_resolved(2, 0, data)
        assert abs(pr1['poyn'] - pr2['poyn']) < 1e-6


class TestPoyntingDerivative:
    """d(Poynting)/dz should equal local absorption density."""

    @pytest.fixture(autouse=True)
    def setup(self):
        import tmm_engine
        self.tmm = tmm_engine
        self.n_list = [1, 2.2 + 0.2j, 3.3 + 0.3j, 1]
        self.d_list = [inf, 100, 300, inf]

    def test_s_pol(self):
        data = self.tmm.coh_tmm('s', self.n_list, self.d_list, pi / 4, 400)
        dx = 0.001
        pr1 = self.tmm.position_resolved(1, 37, data)
        pr2 = self.tmm.position_resolved(1, 37 + dx, data)
        deriv = (pr1['poyn'] - pr2['poyn']) / dx
        avg_absor = (pr1['absor'] + pr2['absor']) / 2
        rel_diff = abs(deriv - avg_absor) / max(abs(deriv), abs(avg_absor))
        assert rel_diff < 1e-3

    def test_p_pol(self):
        data = self.tmm.coh_tmm('p', self.n_list, self.d_list, pi / 4, 400)
        dx = 0.001
        pr1 = self.tmm.position_resolved(1, 37, data)
        pr2 = self.tmm.position_resolved(1, 37 + dx, data)
        deriv = (pr1['poyn'] - pr2['poyn']) / dx
        avg_absor = (pr1['absor'] + pr2['absor']) / 2
        rel_diff = abs(deriv - avg_absor) / max(abs(deriv), abs(avg_absor))
        assert rel_diff < 1e-3


# ---------------------------------------------------------------------------
# Return-value structure tests
# ---------------------------------------------------------------------------

class TestReturnStructure:
    """Verify that coh_tmm returns all required keys."""

    def test_required_keys(self):
        import tmm_engine
        data = tmm_engine.coh_tmm('s', [1, 2, 1], [inf, 100, inf], 0, 500)
        for key in ('r', 't', 'R', 'T', 'power_entering', 'vw_list',
                     'kz_list', 'th_list', 'pol', 'n_list', 'd_list',
                     'th_0', 'lam_vac'):
            assert key in data, f"Missing key: {key}"

    def test_position_resolved_keys(self):
        import tmm_engine
        data = tmm_engine.coh_tmm('s', [1, 2, 1], [inf, 100, inf], 0, 500)
        pr = tmm_engine.position_resolved(1, 50, data)
        for key in ('poyn', 'absor', 'Ex', 'Ey', 'Ez'):
            assert key in pr, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# C shared library tests
# ---------------------------------------------------------------------------

class TestSharedLibrary:
    """Verify C shared library exists, loads, and computes correctly."""

    def test_library_exists(self):
        import os
        assert os.path.exists('/app/libmatkernel.so'), \
            "libmatkernel.so must exist at /app/"

    def test_ctypes_loadable(self):
        import ctypes
        lib = ctypes.CDLL('/app/libmatkernel.so')
        assert hasattr(lib, 'mat2x2_chain_multiply')
        assert hasattr(lib, 'mat2x2_mul')
        assert hasattr(lib, 'mat2x2_inv')

    def test_identity_chain(self):
        """Chain-multiplying zero matrices returns identity."""
        import ctypes
        lib = ctypes.CDLL('/app/libmatkernel.so')
        out = (ctypes.c_double * 8)()
        arr = (ctypes.c_double * 1)(0.0)
        lib.mat2x2_chain_multiply(arr, 0, out)
        assert abs(out[0] - 1.0) < 1e-12
        assert abs(out[1]) < 1e-12
        assert abs(out[2]) < 1e-12
        assert abs(out[3]) < 1e-12
        assert abs(out[4]) < 1e-12
        assert abs(out[5]) < 1e-12
        assert abs(out[6] - 1.0) < 1e-12
        assert abs(out[7]) < 1e-12

    def test_single_matrix(self):
        """Chain-multiplying a single matrix returns that matrix."""
        import ctypes
        lib = ctypes.CDLL('/app/libmatkernel.so')
        # Matrix [[2+1j, 0], [0, 3-1j]]
        arr = (ctypes.c_double * 8)(2.0, 1.0, 0.0, 0.0, 0.0, 0.0, 3.0, -1.0)
        out = (ctypes.c_double * 8)()
        lib.mat2x2_chain_multiply(arr, 1, out)
        assert abs(out[0] - 2.0) < 1e-12
        assert abs(out[1] - 1.0) < 1e-12
        assert abs(out[6] - 3.0) < 1e-12
        assert abs(out[7] - (-1.0)) < 1e-12

    def test_two_matrix_product(self):
        """Verify A*B for two known complex matrices."""
        import ctypes
        lib = ctypes.CDLL('/app/libmatkernel.so')
        # A = [[1+1j, 2], [0, 1-1j]], B = [[1, 0], [1j, 2+1j]]
        # A*B = [[1+3j, 4+2j], [1+1j, 3-1j]]
        A = [1, 1, 2, 0, 0, 0, 1, -1]
        B = [1, 0, 0, 0, 0, 1, 2, 1]
        arr = (ctypes.c_double * 16)(*A, *B)
        out = (ctypes.c_double * 8)()
        lib.mat2x2_chain_multiply(arr, 2, out)
        assert abs(out[0] - 1.0) < 1e-12   # Re(m00)
        assert abs(out[1] - 3.0) < 1e-12   # Im(m00)
        assert abs(out[2] - 4.0) < 1e-12   # Re(m01)
        assert abs(out[3] - 2.0) < 1e-12   # Im(m01)
        assert abs(out[4] - 1.0) < 1e-12   # Re(m10)
        assert abs(out[5] - 1.0) < 1e-12   # Im(m10)
        assert abs(out[6] - 3.0) < 1e-12   # Re(m11)
        assert abs(out[7] - (-1.0)) < 1e-12  # Im(m11)

    def test_noncommutative_order(self):
        """Chain multiply must respect left-to-right order (A*B != B*A)."""
        import ctypes
        lib = ctypes.CDLL('/app/libmatkernel.so')
        # A = [[0, 1], [1, 0]] (swap), B = [[2, 0], [0, 3]]
        # A*B = [[0, 3], [2, 0]], B*A = [[0, 2], [3, 0]]
        A = [0, 0, 1, 0, 1, 0, 0, 0]
        B = [2, 0, 0, 0, 0, 0, 3, 0]
        arr = (ctypes.c_double * 16)(*A, *B)
        out = (ctypes.c_double * 8)()
        lib.mat2x2_chain_multiply(arr, 2, out)
        # Expect A*B: [[0, 3], [2, 0]]
        assert abs(out[0] - 0.0) < 1e-12
        assert abs(out[2] - 3.0) < 1e-12
        assert abs(out[4] - 2.0) < 1e-12
        assert abs(out[6] - 0.0) < 1e-12

    def test_inverse(self):
        """Verify matrix inverse: A * A^{-1} = I."""
        import ctypes
        lib = ctypes.CDLL('/app/libmatkernel.so')
        # A = [[3+1j, 1-2j], [0.5j, 2+0.5j]]
        A = (ctypes.c_double * 8)(3, 1, 1, -2, 0, 0.5, 2, 0.5)
        B = (ctypes.c_double * 8)()
        lib.mat2x2_inv(A, B)
        # Multiply A * B, should give identity
        C = (ctypes.c_double * 8)()
        lib.mat2x2_mul(A, B, C)
        assert abs(C[0] - 1.0) < 1e-10  # Re(I[0,0])
        assert abs(C[1]) < 1e-10         # Im(I[0,0])
        assert abs(C[2]) < 1e-10         # Re(I[0,1])
        assert abs(C[3]) < 1e-10         # Im(I[0,1])
        assert abs(C[4]) < 1e-10         # Re(I[1,0])
        assert abs(C[5]) < 1e-10         # Im(I[1,0])
        assert abs(C[6] - 1.0) < 1e-10  # Re(I[1,1])
        assert abs(C[7]) < 1e-10         # Im(I[1,1])


# ---------------------------------------------------------------------------
# ctypes integration test
# ---------------------------------------------------------------------------

class TestCtypesIntegration:
    """Verify that tmm_engine loads the C kernel via ctypes."""

    def test_engine_has_cdll_handle(self):
        """tmm_engine must have a module-level ctypes.CDLL handle."""
        import tmm_engine
        import ctypes
        found = False
        for name in dir(tmm_engine):
            obj = getattr(tmm_engine, name, None)
            if isinstance(obj, ctypes.CDLL):
                found = True
                break
        assert found, \
            "tmm_engine must load libmatkernel.so via a module-level ctypes.CDLL"


# ---------------------------------------------------------------------------
# inc_tmm consistency tests
# ---------------------------------------------------------------------------

class TestIncTmmConsistency:
    """For all-coherent interior layers, inc_tmm must match coh_tmm."""

    @pytest.fixture(autouse=True)
    def setup(self):
        import tmm_engine
        self.tmm = tmm_engine

    def test_two_coherent_s(self):
        n = [1, 2 + 0.5j, 1.5 + 0.2j, 1]
        d = [inf, 50, 80, inf]
        c = ['i', 'c', 'c', 'i']
        inc = self.tmm.inc_tmm('s', n, d, c, 0.3, 500)
        coh = self.tmm.coh_tmm('s', n, d, 0.3, 500)
        assert abs(inc['R'] - coh['R']) < 1e-6
        assert abs(inc['T'] - coh['T']) < 1e-6

    def test_two_coherent_p(self):
        n = [1, 2 + 0.5j, 1.5 + 0.2j, 1]
        d = [inf, 50, 80, inf]
        c = ['i', 'c', 'c', 'i']
        inc = self.tmm.inc_tmm('p', n, d, c, 0.3, 500)
        coh = self.tmm.coh_tmm('p', n, d, 0.3, 500)
        assert abs(inc['R'] - coh['R']) < 1e-6
        assert abs(inc['T'] - coh['T']) < 1e-6

    def test_single_coherent_s(self):
        n = [1, 2.5 + 0.1j, 1.3]
        d = [inf, 200, inf]
        c = ['i', 'c', 'i']
        inc = self.tmm.inc_tmm('s', n, d, c, 0.5, 600)
        coh = self.tmm.coh_tmm('s', n, d, 0.5, 600)
        assert abs(inc['R'] - coh['R']) < 1e-6
        assert abs(inc['T'] - coh['T']) < 1e-6

    def test_single_coherent_p(self):
        n = [1, 2.5 + 0.1j, 1.3]
        d = [inf, 200, inf]
        c = ['i', 'c', 'i']
        inc = self.tmm.inc_tmm('p', n, d, c, 0.5, 600)
        coh = self.tmm.coh_tmm('p', n, d, 0.5, 600)
        assert abs(inc['R'] - coh['R']) < 1e-6
        assert abs(inc['T'] - coh['T']) < 1e-6


# ---------------------------------------------------------------------------
# inc_tmm solar cell tests
# ---------------------------------------------------------------------------

class TestIncTmmSolarCell:
    """Test inc_tmm on multi-stack solar cell structure."""

    @pytest.fixture(autouse=True)
    def setup(self):
        import tmm_engine
        self.tmm = tmm_engine
        self.n = [1.0, 1.38, 3.5, 3.5 + 0.02j, 1.5]
        self.d = [inf, 100, 500000, 300, inf]
        self.c = ['i', 'c', 'i', 'c', 'i']

    def test_has_keys(self):
        data = self.tmm.inc_tmm('s', self.n, self.d, self.c, 0, 550)
        for key in ('R', 'T', 'VW_list', 'power_entering_list'):
            assert key in data

    def test_energy_conservation_s(self):
        data = self.tmm.inc_tmm('s', self.n, self.d, self.c, 0, 550)
        assert 0 <= data['R'] <= 1
        assert 0 <= data['T'] <= 1
        assert data['R'] + data['T'] <= 1.0 + 1e-6

    def test_energy_conservation_p(self):
        data = self.tmm.inc_tmm('p', self.n, self.d, self.c, 0, 550)
        assert 0 <= data['R'] <= 1
        assert 0 <= data['T'] <= 1
        assert data['R'] + data['T'] <= 1.0 + 1e-6

    def test_ar_reduces_reflection(self):
        """AR coating should reduce R compared to no coating."""
        data_ar = self.tmm.inc_tmm('s', self.n, self.d, self.c, 0, 550)
        n_bare = [1.0, 3.5, 3.5 + 0.02j, 1.5]
        d_bare = [inf, 500000, 300, inf]
        c_bare = ['i', 'i', 'c', 'i']
        data_bare = self.tmm.inc_tmm('s', n_bare, d_bare, c_bare, 0, 550)
        assert data_ar['R'] < data_bare['R']

    def test_power_entering_list_length(self):
        data = self.tmm.inc_tmm('s', self.n, self.d, self.c, 0, 550)
        assert len(data['power_entering_list']) == 3

    def test_normal_incidence_symmetry(self):
        """At normal incidence, s and p polarizations give identical R and T."""
        data_s = self.tmm.inc_tmm('s', self.n, self.d, self.c, 0, 550)
        data_p = self.tmm.inc_tmm('p', self.n, self.d, self.c, 0, 550)
        assert abs(data_s['R'] - data_p['R']) < 1e-6
        assert abs(data_s['T'] - data_p['T']) < 1e-6


# ---------------------------------------------------------------------------
# Makefile tests
# ---------------------------------------------------------------------------

class TestMakefile:
    """Verify Makefile exists and has required targets."""

    def test_makefile_exists(self):
        import os
        assert os.path.exists('/app/Makefile')

    def test_has_lib_target(self):
        import subprocess
        result = subprocess.run(
            ['make', '-n', 'lib'], capture_output=True, cwd='/app')
        assert result.returncode == 0, "Makefile must have a 'lib' target"

    def test_has_all_target(self):
        import subprocess
        result = subprocess.run(
            ['make', '-n', 'all'], capture_output=True, cwd='/app')
        assert result.returncode == 0, "Makefile must have an 'all' target"


# ---------------------------------------------------------------------------
# Results JSON: basic section
# ---------------------------------------------------------------------------

class TestResultsBasic:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open('/app/results.json') as f:
            self.results = json.load(f)

    def test_R_s(self):
        assert abs(self.results['basic']['R_s'] - 0.37273208839139516) < 1e-5

    def test_T_s(self):
        assert abs(self.results['basic']['T_s'] - 0.22604491247079261) < 1e-5

    def test_R_p(self):
        assert abs(self.results['basic']['R_p'] - 0.37016110373044969) < 1e-5

    def test_T_p(self):
        assert abs(self.results['basic']['T_p'] - 0.22824374314132009) < 1e-5

    def test_psi(self):
        assert abs(self.results['basic']['psi'] - 0.78366777347038352) < 1e-5

    def test_delta(self):
        assert abs(self.results['basic']['Delta'] - 0.0021460774404193292) < 1e-5


# ---------------------------------------------------------------------------
# Results JSON: SPR analysis
# ---------------------------------------------------------------------------

class TestResultsSPR:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open('/app/results.json') as f:
            self.results = json.load(f)
        import tmm_engine
        self.tmm = tmm_engine

    def test_angle_in_physical_range(self):
        assert 40 < self.results['spr']['spr_angle_deg'] < 50

    def test_R_min_is_low(self):
        assert self.results['spr']['R_min'] < 0.3

    def test_is_minimum(self):
        angle = self.results['spr']['spr_angle_deg']
        n_list = [1.517, 3.719 + 4.362j, 0.130 + 3.162j, 1.0]
        d_list = [inf, 5, 30, inf]
        R_c = self.tmm.coh_tmm('p', n_list, d_list, angle * pi / 180, 633)['R']
        R_l = self.tmm.coh_tmm('p', n_list, d_list, (angle - 0.5) * pi / 180, 633)['R']
        R_r = self.tmm.coh_tmm('p', n_list, d_list, (angle + 0.5) * pi / 180, 633)['R']
        assert R_c <= R_l + 1e-4
        assert R_c <= R_r + 1e-4

    def test_R_min_self_consistent(self):
        angle = self.results['spr']['spr_angle_deg']
        n_list = [1.517, 3.719 + 4.362j, 0.130 + 3.162j, 1.0]
        d_list = [inf, 5, 30, inf]
        R = self.tmm.coh_tmm('p', n_list, d_list, angle * pi / 180, 633)['R']
        assert abs(R - self.results['spr']['R_min']) < 0.005


# ---------------------------------------------------------------------------
# Results JSON: AR coating optimization
# ---------------------------------------------------------------------------

class TestResultsARCoating:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open('/app/results.json') as f:
            self.results = json.load(f)
        import tmm_engine
        self.tmm = tmm_engine

    def test_optimal_thickness_near_quarter_wave(self):
        assert 95 < self.results['ar_coating']['optimal_thickness_nm'] < 105

    def test_R_min_range(self):
        assert 0.005 < self.results['ar_coating']['R_min'] < 0.02

    def test_R_min_self_consistent(self):
        d = self.results['ar_coating']['optimal_thickness_nm']
        R = self.tmm.coh_tmm('s', [1.0, 1.38, 1.52], [inf, d, inf], 0, 550)['R']
        assert abs(R - self.results['ar_coating']['R_min']) < 0.001

    def test_avg_R_reasonable(self):
        assert 0.005 < self.results['ar_coating']['avg_R_400_700'] < 0.06

    def test_avg_R_self_consistent(self):
        d = self.results['ar_coating']['optimal_thickness_nm']
        n_list = [1.0, 1.38, 1.52]
        R_sum = 0.0
        for lam in range(400, 701):
            Rs = self.tmm.coh_tmm('s', n_list, [inf, d, inf], 0, lam)['R']
            Rp = self.tmm.coh_tmm('p', n_list, [inf, d, inf], 0, lam)['R']
            R_sum += (Rs + Rp) / 2.0
        assert abs(R_sum / 301.0 - self.results['ar_coating']['avg_R_400_700']) < 0.002

    def test_is_minimum(self):
        d = self.results['ar_coating']['optimal_thickness_nm']
        n_list = [1.0, 1.38, 1.52]
        R_opt = self.tmm.coh_tmm('s', n_list, [inf, d, inf], 0, 550)['R']
        R_m = self.tmm.coh_tmm('s', n_list, [inf, d - 2, inf], 0, 550)['R']
        R_p = self.tmm.coh_tmm('s', n_list, [inf, d + 2, inf], 0, 550)['R']
        assert R_opt <= R_m + 1e-6
        assert R_opt <= R_p + 1e-6


# ---------------------------------------------------------------------------
# Results JSON: solar cell with inc_tmm
# ---------------------------------------------------------------------------

class TestResultsSolarCell:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open('/app/results.json') as f:
            self.results = json.load(f)
        import tmm_engine
        self.tmm = tmm_engine
        self.sc = self.results['solar_cell']

    def test_R_reasonable(self):
        assert 0 < self.sc['R_s'] < 0.25
        assert 0 < self.sc['R_p'] < 0.25

    def test_T_reasonable(self):
        assert 0 < self.sc['T_s'] < 1
        assert 0 < self.sc['T_p'] < 1

    def test_has_absorption(self):
        assert self.sc['R_s'] + self.sc['T_s'] < 0.99

    def test_normal_incidence_symmetry(self):
        assert abs(self.sc['R_s'] - self.sc['R_p']) < 1e-6
        assert abs(self.sc['T_s'] - self.sc['T_p']) < 1e-6

    def test_self_consistent_s(self):
        n = [1.0, 1.38, 3.5, 3.5 + 0.02j, 1.5]
        d = [inf, 100, 500000, 300, inf]
        c = ['i', 'c', 'i', 'c', 'i']
        data = self.tmm.inc_tmm('s', n, d, c, 0, 550)
        assert abs(data['R'] - self.sc['R_s']) < 1e-6
        assert abs(data['T'] - self.sc['T_s']) < 1e-6

    def test_self_consistent_p(self):
        n = [1.0, 1.38, 3.5, 3.5 + 0.02j, 1.5]
        d = [inf, 100, 500000, 300, inf]
        c = ['i', 'c', 'i', 'c', 'i']
        data = self.tmm.inc_tmm('p', n, d, c, 0, 550)
        assert abs(data['R'] - self.sc['R_p']) < 1e-6
        assert abs(data['T'] - self.sc['T_p']) < 1e-6

    def test_absorption_sum_s(self):
        a = self.sc['absorption_per_layer_s']
        assert abs(sum(a) - 1.0) < 1e-6

    def test_absorption_sum_p(self):
        a = self.sc['absorption_per_layer_p']
        assert abs(sum(a) - 1.0) < 1e-6

    def test_absorption_first_equals_R(self):
        assert abs(self.sc['absorption_per_layer_s'][0] - self.sc['R_s']) < 1e-6
        assert abs(self.sc['absorption_per_layer_p'][0] - self.sc['R_p']) < 1e-6

    def test_absorption_last_equals_T(self):
        assert abs(self.sc['absorption_per_layer_s'][-1] - self.sc['T_s']) < 1e-6
        assert abs(self.sc['absorption_per_layer_p'][-1] - self.sc['T_p']) < 1e-6

    def test_absorption_nonnegative(self):
        for a in self.sc['absorption_per_layer_s']:
            assert a >= -1e-10
        for a in self.sc['absorption_per_layer_p']:
            assert a >= -1e-10

    def test_real_layers_no_absorption(self):
        """Layers with real n (1.38, 3.5) should have negligible absorption."""
        assert abs(self.sc['absorption_per_layer_s'][1]) < 1e-6
        assert abs(self.sc['absorption_per_layer_s'][2]) < 1e-6

    def test_active_layer_absorption(self):
        """Active layer absorbs exactly 1 - R - T."""
        R = self.sc['R_s']
        T = self.sc['T_s']
        A_active = self.sc['absorption_per_layer_s'][3]
        assert abs(A_active - (1.0 - R - T)) < 1e-6

    def test_absorption_length(self):
        assert len(self.sc['absorption_per_layer_s']) == 5
        assert len(self.sc['absorption_per_layer_p']) == 5


# ---------------------------------------------------------------------------
# SQLite database tests
# ---------------------------------------------------------------------------

class TestSQLiteDatabase:
    """Verify results.db exists with correct schema and consistent data."""

    def test_db_exists(self):
        import os
        assert os.path.exists('/app/results.db'), \
            "results.db must exist at /app/"

    def test_schema_stack_results(self):
        import sqlite3
        conn = sqlite3.connect('/app/results.db')
        c = conn.cursor()
        c.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='stack_results'")
        assert c.fetchone() is not None, "Table 'stack_results' must exist"
        c.execute("PRAGMA table_info(stack_results)")
        cols = {row[1] for row in c.fetchall()}
        assert 'stack_name' in cols
        assert 'key' in cols
        assert 'value' in cols
        conn.close()

    def test_schema_absorption(self):
        import sqlite3
        conn = sqlite3.connect('/app/results.db')
        c = conn.cursor()
        c.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='absorption'")
        assert c.fetchone() is not None, "Table 'absorption' must exist"
        c.execute("PRAGMA table_info(absorption)")
        cols = {row[1] for row in c.fetchall()}
        assert 'stack_name' in cols
        assert 'polarization' in cols
        assert 'layer_index' in cols
        assert 'absorption' in cols
        conn.close()

    def test_basic_values_match_json(self):
        import sqlite3
        with open('/app/results.json') as f:
            jdata = json.load(f)
        conn = sqlite3.connect('/app/results.db')
        c = conn.cursor()
        for key in ['R_s', 'T_s', 'R_p', 'T_p', 'psi', 'Delta']:
            c.execute(
                "SELECT value FROM stack_results "
                "WHERE stack_name='basic' AND key=?", (key,))
            row = c.fetchone()
            assert row is not None, f"Missing basic/{key} in SQLite"
            assert abs(row[0] - jdata['basic'][key]) < 1e-10
        conn.close()

    def test_spr_values_in_db(self):
        import sqlite3
        conn = sqlite3.connect('/app/results.db')
        c = conn.cursor()
        c.execute(
            "SELECT value FROM stack_results "
            "WHERE stack_name='spr' AND key='spr_angle_deg'")
        row = c.fetchone()
        assert row is not None
        assert 40 < row[0] < 50
        c.execute(
            "SELECT value FROM stack_results "
            "WHERE stack_name='spr' AND key='R_min'")
        row = c.fetchone()
        assert row is not None
        assert row[0] < 0.3
        conn.close()

    def test_absorption_rows(self):
        import sqlite3
        conn = sqlite3.connect('/app/results.db')
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM absorption "
            "WHERE stack_name='solar_cell' AND polarization='s'")
        assert c.fetchone()[0] == 5
        c.execute(
            "SELECT COUNT(*) FROM absorption "
            "WHERE stack_name='solar_cell' AND polarization='p'")
        assert c.fetchone()[0] == 5
        conn.close()

    def test_absorption_sum_in_db(self):
        import sqlite3
        conn = sqlite3.connect('/app/results.db')
        c = conn.cursor()
        c.execute(
            "SELECT SUM(absorption) FROM absorption "
            "WHERE stack_name='solar_cell' AND polarization='s'")
        s = c.fetchone()[0]
        assert abs(s - 1.0) < 1e-6
        c.execute(
            "SELECT SUM(absorption) FROM absorption "
            "WHERE stack_name='solar_cell' AND polarization='p'")
        p = c.fetchone()[0]
        assert abs(p - 1.0) < 1e-6
        conn.close()

    def test_absorption_matches_json(self):
        import sqlite3
        with open('/app/results.json') as f:
            jdata = json.load(f)
        conn = sqlite3.connect('/app/results.db')
        c = conn.cursor()
        for pol in ['s', 'p']:
            c.execute(
                "SELECT layer_index, absorption FROM absorption "
                "WHERE stack_name='solar_cell' AND polarization=? "
                "ORDER BY layer_index", (pol,))
            rows = c.fetchall()
            json_vals = jdata['solar_cell'][f'absorption_per_layer_{pol}']
            assert len(rows) == len(json_vals)
            for (idx, val), jval in zip(rows, json_vals):
                assert abs(val - jval) < 1e-10
        conn.close()
