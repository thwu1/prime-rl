"""Tests for PR EOS mixture implementation and VLE flash calculator.

Reference values sourced from CalebBell/thermo library validation suite,
which embeds hand-checked golden numbers from textbooks (Elliott & Lira)
and literature data (DDBST, Walas).
"""

import json
import math
import os
import subprocess
import sys

import pytest

sys.path.insert(0, '/app')


def assert_close(a, b, rtol=5e-4):
    """Assert two floats are close within relative tolerance."""
    denom = max(abs(b), 1e-30)
    rel_err = abs(a - b) / denom
    assert rel_err < rtol, (
        f"Values differ: {a} vs {b}, rel_err={rel_err:.2e}, rtol={rtol:.2e}"
    )


def assert_close1d(a, b, rtol=5e-4):
    """Assert two lists of floats are element-wise close."""
    assert len(a) == len(b), f"Length mismatch: {len(a)} vs {len(b)}"
    for i in range(len(a)):
        assert_close(a[i], b[i], rtol=rtol)


def normalize_flash_result(result, ref_xs_0):
    """Normalize flash result so xs[0] is closer to ref_xs_0.

    VLE flash can converge with xs/ys swapped (both are valid equilibria).
    This normalizes the labeling for deterministic comparison.
    """
    VF = result['VF']
    xs = list(result['xs'])
    ys = list(result['ys'])

    # If xs[0] is further from ref_xs_0 than ys[0], swap
    if abs(xs[0] - ref_xs_0) > abs(ys[0] - ref_xs_0):
        xs, ys = ys, xs
        VF = 1.0 - VF

    return VF, xs, ys


# == Build system and C library tests ========================================

class TestBuildSystem:
    """Verify the C shared library build chain and correctness."""

    def test_libcubic_exists_and_loadable(self):
        """libcubic.so must be a valid shared library loadable via ctypes."""
        import ctypes
        lib_path = '/app/libcubic/libcubic.so'
        assert os.path.exists(lib_path), f"libcubic.so not found at {lib_path}"
        lib = ctypes.CDLL(lib_path)
        solve = lib.solve_cubic_eos
        solve.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double * 3]
        solve.restype = ctypes.c_int

    def test_cubic_roots_satisfy_equation(self):
        """Z-roots from solve_cubic_eos must satisfy the original cubic."""
        import ctypes
        lib = ctypes.CDLL('/app/libcubic/libcubic.so')
        solve = lib.solve_cubic_eos
        solve.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double * 3]
        solve.restype = ctypes.c_int

        test_cases = [
            (0.5, 0.05),
            (1.0, 0.1),
            (0.2, 0.03),
            (2.0, 0.15),
            (0.8, 0.08),
        ]

        for A, B in test_cases:
            roots = (ctypes.c_double * 3)()
            count = solve(ctypes.c_double(A), ctypes.c_double(B), roots)
            assert count >= 1, f"No roots for A={A}, B={B}"

            c2 = -(1.0 - B)
            c1 = A - 3.0 * B * B - 2.0 * B
            c0 = -(A * B - B * B - B * B * B)

            for i in range(count):
                Z = roots[i]
                residual = Z * Z * Z + c2 * Z * Z + c1 * Z + c0
                assert abs(residual) < 1e-8, (
                    f"Root Z={Z} for A={A}, B={B} has residual={residual:.2e}"
                )

    def test_cubic_roots_sorted_ascending(self):
        """Returned roots must be sorted in ascending order."""
        import ctypes
        lib = ctypes.CDLL('/app/libcubic/libcubic.so')
        solve = lib.solve_cubic_eos
        solve.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double * 3]
        solve.restype = ctypes.c_int

        # Case likely to produce 3 roots
        roots = (ctypes.c_double * 3)()
        count = solve(ctypes.c_double(0.5), ctypes.c_double(0.05), roots)

        for i in range(count - 1):
            assert roots[i] <= roots[i + 1], (
                f"Roots not sorted: roots[{i}]={roots[i]} > roots[{i+1}]={roots[i+1]}"
            )


# == Integration: pr_mix.py must use ctypes ==================================

class TestIntegration:
    """Verify pr_mix.py uses the C shared library via ctypes."""

    def test_pr_mix_uses_ctypes_and_libcubic(self):
        """pr_mix.py must import ctypes and reference libcubic."""
        with open('/app/pr_mix.py') as f:
            source = f.read()
        assert 'ctypes' in source, "pr_mix.py must use ctypes to load the C library"
        assert 'libcubic' in source, "pr_mix.py must load libcubic.so"


# == Pure-component sanity check =============================================

class TestPureComponent:
    """Verify PR EOS works for a single-component system (hexane)."""

    def test_hexane_liquid_fugacity_coefficient(self):
        from pr_mix import mixture_fugacity_coefficients

        phis = mixture_fugacity_coefficients(
            T=299.0, P=1e6, zs=[1.0],
            Tcs=[507.6], Pcs=[3025000.0], omegas=[0.2975],
            kijs=[[0.0]], phase='liquid'
        )
        assert len(phis) == 1
        assert_close(phis[0], 0.022212524527244346, rtol=5e-4)


# == Binary mixture fugacity coefficients ====================================

class TestBinaryFugacityCoefficients:
    """N2-CH4 binary at 115 K, 1 MPa, no binary interaction."""

    def test_liquid_phis(self):
        from pr_mix import mixture_fugacity_coefficients

        phis_l = mixture_fugacity_coefficients(
            T=115.0, P=1e6,
            zs=[0.5, 0.5],
            Tcs=[126.1, 190.6],
            Pcs=[33.94e5, 46.04e5],
            omegas=[0.04, 0.011],
            kijs=[[0, 0], [0, 0]],
            phase='liquid'
        )
        assert_close1d(phis_l, [1.5877216764229214, 0.14693710450607678])

    def test_vapor_phis(self):
        from pr_mix import mixture_fugacity_coefficients

        phis_g = mixture_fugacity_coefficients(
            T=115.0, P=1e6,
            zs=[0.5, 0.5],
            Tcs=[126.1, 190.6],
            Pcs=[33.94e5, 46.04e5],
            omegas=[0.04, 0.011],
            kijs=[[0, 0], [0, 0]],
            phase='vapor'
        )
        assert_close1d(phis_g, [0.8730618494018239, 0.7162292765506479])

    def test_fugacities(self):
        """Verify f_i = phi_i * z_i * P."""
        from pr_mix import mixture_fugacity_coefficients

        zs = [0.5, 0.5]
        P = 1e6
        phis_l = mixture_fugacity_coefficients(
            T=115.0, P=P, zs=zs,
            Tcs=[126.1, 190.6],
            Pcs=[33.94e5, 46.04e5],
            omegas=[0.04, 0.011],
            kijs=[[0, 0], [0, 0]],
            phase='liquid'
        )
        fugacities_l = [phis_l[i] * zs[i] * P for i in range(2)]
        assert_close1d(fugacities_l, [793860.8382114634, 73468.55225303846])


# == Ternary mixture with binary interaction parameters ======================

class TestTernaryElliottLira:
    """3-component system from Elliott & Lira textbook."""

    def _params(self):
        return dict(
            T=322.29, P=101325.0,
            zs=[0.8168, 0.1501, 0.0331],
            Tcs=[469.7, 507.4, 540.3],
            Pcs=[3.369e6, 3.012e6, 2.736e6],
            omegas=[0.249, 0.305, 0.349],
            kijs=[
                [0, 0.00076, 0.00171],
                [0.00076, 0, 0.00061],
                [0.00171, 0.00061, 0],
            ],
        )

    def test_vapor_phis(self):
        from pr_mix import mixture_fugacity_coefficients

        p = self._params()
        phis_g = mixture_fugacity_coefficients(**p, phase='vapor')
        assert_close1d(
            phis_g,
            [0.966475030274237, 0.953292801077091, 0.940728104174207],
            rtol=5e-4,
        )

    def test_liquid_phis(self):
        from pr_mix import mixture_fugacity_coefficients

        p = self._params()
        phis_l = mixture_fugacity_coefficients(**p, phase='liquid')
        assert_close1d(
            phis_l,
            [1.45191729893103, 0.502201064053298, 0.185146457753801],
            rtol=5e-4,
        )

    def test_fugacities_gas(self):
        """Verify gas fugacities for the ternary."""
        from pr_mix import mixture_fugacity_coefficients

        p = self._params()
        phis_g = mixture_fugacity_coefficients(**p, phase='vapor')
        P = p['P']
        zs = p['zs']
        fug_g = [phis_g[i] * zs[i] * P for i in range(3)]
        assert_close1d(
            fug_g,
            [79987.657739064, 14498.518199677, 3155.0680076450003],
            rtol=5e-4,
        )


# == Supercritical / gas-only phase ==========================================

class TestGasOnly:
    """High-T binary: single gas-phase region."""

    def test_gas_phis_supercritical(self):
        from pr_mix import mixture_fugacity_coefficients

        phis_g = mixture_fugacity_coefficients(
            T=300.0, P=1e7,
            zs=[0.5, 0.5],
            Tcs=[126.1, 190.6],
            Pcs=[33.94e5, 46.04e5],
            omegas=[0.04, 0.011],
            kijs=[[0, 0], [0, 0]],
            phase='vapor'
        )
        assert_close1d(phis_g, [0.9855336740251448, 0.8338953860988254])


# == Rachford-Rice solver ====================================================

class TestRachfordRice:
    """Verify Rachford-Rice with analytically solvable cases."""

    def test_symmetric_binary(self):
        """zs=[0.5,0.5], Ks=[2.0,0.5] => VF=0.5 exactly."""
        from pr_mix import rachford_rice

        VF = rachford_rice([0.5, 0.5], [2.0, 0.5])
        assert_close(VF, 0.5, rtol=1e-10)

    def test_ternary_with_unity_k(self):
        from pr_mix import rachford_rice

        VF = rachford_rice([0.3, 0.5, 0.2], [3.0, 1.0, 0.1])
        assert_close(VF, 0.42 / 0.9, rtol=1e-8)

    def test_asymmetric_binary(self):
        from pr_mix import rachford_rice

        VF = rachford_rice([0.7, 0.3], [4.0, 0.2])
        assert_close(VF, 1.86 / 2.4, rtol=1e-8)


# == Full VLE flash: ethane-pentane binary ===================================

class TestFlashEthanePentane:
    """C2H6-C5H12 binary flash at 360 K, 3 MPa."""

    _zs = [0.7058336794895449, 0.29416632051045505]
    _Tcs = [305.32, 469.7]
    _Pcs = [4872000.0, 3370000.0]
    _omegas = [0.098, 0.251]
    _kijs = [[0, 0], [0, 0]]

    _ref_ethane_rich = [0.8178671482462099, 0.18213285175379013]
    _ref_pentane_rich = [0.3676551321096354, 0.6323448678903647]
    _ref_VF_pentane_rich = 0.24884602085493626

    def _do_flash(self):
        from pr_mix import flash_pt
        return flash_pt(
            T=360.0, P=3e6,
            zs=self._zs, Tcs=self._Tcs, Pcs=self._Pcs,
            omegas=self._omegas, kijs=self._kijs,
        )

    def test_equilibrium_compositions(self):
        result = self._do_flash()
        VF, xs, ys = normalize_flash_result(result, self._ref_ethane_rich[0])

        assert_close(VF, self._ref_VF_pentane_rich, rtol=5e-3)
        assert_close1d(xs, self._ref_ethane_rich, rtol=5e-3)
        assert_close1d(ys, self._ref_pentane_rich, rtol=5e-3)

    def test_material_balance(self):
        """z_i = x_i*(1-VF) + y_i*VF for each component."""
        result = self._do_flash()
        VF = result['VF']
        for i in range(2):
            z_calc = result['xs'][i] * (1 - VF) + result['ys'][i] * VF
            assert_close(z_calc, self._zs[i], rtol=1e-6)

    def test_fugacity_equality(self):
        """At equilibrium, f_i^L = f_i^V for each component."""
        from pr_mix import flash_pt, mixture_fugacity_coefficients

        T, P = 360.0, 3e6
        result = flash_pt(
            T=T, P=P, zs=self._zs, Tcs=self._Tcs, Pcs=self._Pcs,
            omegas=self._omegas, kijs=self._kijs,
        )
        xs, ys = result['xs'], result['ys']

        phis_l = mixture_fugacity_coefficients(
            T, P, xs, self._Tcs, self._Pcs, self._omegas, self._kijs, 'liquid'
        )
        phis_g = mixture_fugacity_coefficients(
            T, P, ys, self._Tcs, self._Pcs, self._omegas, self._kijs, 'vapor'
        )

        fug_l = [phis_l[i] * xs[i] * P for i in range(2)]
        fug_g = [phis_g[i] * ys[i] * P for i in range(2)]

        assert_close1d(fug_l, fug_g, rtol=1e-3)


# == Flash with binary interaction parameters ================================

class TestFlashCH4H2S:
    """CH4-H2S flash at 190 K, 40.53 bar with kij = 0.083."""

    _T = 190.0
    _P = 40.53e5
    _Tcs = [190.63, 373.55]
    _Pcs = [46.17e5, 90.07e5]
    _omegas = [0.01, 0.1]
    _kijs = [[0, 0.083], [0.083, 0]]

    def _flash_params(self):
        return dict(
            T=self._T, P=self._P,
            zs=[0.5, 0.5],
            Tcs=self._Tcs, Pcs=self._Pcs,
            omegas=self._omegas, kijs=self._kijs,
        )

    def test_vapor_fraction(self):
        from pr_mix import flash_pt

        result = flash_pt(**self._flash_params())
        VF, xs, ys = normalize_flash_result(result, 0.1164)
        assert_close(VF, 0.44424170, rtol=5e-3)

    def test_equilibrium_fugacities_known_compositions(self):
        """At known equilibrium compositions, fugacities must match."""
        from pr_mix import mixture_fugacity_coefficients

        xs = [0.1164203, 0.8835797]
        ys = [0.9798684, 0.0201315]

        phis_l = mixture_fugacity_coefficients(
            self._T, self._P, xs, self._Tcs, self._Pcs,
            self._omegas, self._kijs, 'liquid'
        )
        phis_g = mixture_fugacity_coefficients(
            self._T, self._P, ys, self._Tcs, self._Pcs,
            self._omegas, self._kijs, 'vapor'
        )

        fug_l = [phis_l[i] * xs[i] * self._P for i in range(2)]
        fug_g = [phis_g[i] * ys[i] * self._P for i in range(2)]

        assert_close1d(fug_l, fug_g, rtol=1e-3)
        assert_close1d(fug_l, [2721190, 27752.94], rtol=5e-3)

    def test_flash_fugacity_equality(self):
        """The flash solution itself must satisfy fugacity equality."""
        from pr_mix import flash_pt, mixture_fugacity_coefficients

        p = self._flash_params()
        result = flash_pt(**p)
        xs, ys = result['xs'], result['ys']

        phis_l = mixture_fugacity_coefficients(
            p['T'], p['P'], xs, p['Tcs'], p['Pcs'], p['omegas'], p['kijs'], 'liquid'
        )
        phis_g = mixture_fugacity_coefficients(
            p['T'], p['P'], ys, p['Tcs'], p['Pcs'], p['omegas'], p['kijs'], 'vapor'
        )

        fug_l = [phis_l[i] * xs[i] * p['P'] for i in range(2)]
        fug_g = [phis_g[i] * ys[i] * p['P'] for i in range(2)]

        assert_close1d(fug_l, fug_g, rtol=1e-3)


# == CLI tool ================================================================

class TestCLI:
    """Test the flash_cli.py command-line tool."""

    def test_cli_c2_c5(self):
        input_data = {
            'T': 360.0,
            'P': 3e6,
            'zs': [0.7058336794895449, 0.29416632051045505],
            'Tcs': [305.32, 469.7],
            'Pcs': [4872000.0, 3370000.0],
            'omegas': [0.098, 0.251],
            'kijs': [[0, 0], [0, 0]],
        }

        input_path = '/tmp/test_flash_input.json'
        with open(input_path, 'w') as f:
            json.dump(input_data, f)

        proc = subprocess.run(
            ['python3', '/app/flash_cli.py', input_path],
            capture_output=True, text=True, timeout=120,
        )

        assert proc.returncode == 0, f"CLI failed with stderr: {proc.stderr}"

        output = json.loads(proc.stdout)
        assert 'VF' in output, "Output missing 'VF' key"
        assert 'xs' in output, "Output missing 'xs' key"
        assert 'ys' in output, "Output missing 'ys' key"
        assert 'phis_l' in output, "Output missing 'phis_l' key"
        assert 'phis_g' in output, "Output missing 'phis_g' key"

        VF, xs, ys = normalize_flash_result(output, 0.818)
        assert_close(VF, 0.24884602085493626, rtol=5e-3)
        assert_close1d(xs, [0.8178671482462099, 0.18213285175379013], rtol=5e-3)
        assert_close1d(ys, [0.3676551321096354, 0.6323448678903647], rtol=5e-3)

    def test_cli_ch4_h2s(self):
        input_data = {
            'T': 190.0,
            'P': 40.53e5,
            'zs': [0.5, 0.5],
            'Tcs': [190.63, 373.55],
            'Pcs': [46.17e5, 90.07e5],
            'omegas': [0.01, 0.1],
            'kijs': [[0, 0.083], [0.083, 0]],
        }

        input_path = '/tmp/test_flash_kij_input.json'
        with open(input_path, 'w') as f:
            json.dump(input_data, f)

        proc = subprocess.run(
            ['python3', '/app/flash_cli.py', input_path],
            capture_output=True, text=True, timeout=120,
        )

        assert proc.returncode == 0, f"CLI failed with stderr: {proc.stderr}"

        output = json.loads(proc.stdout)
        VF, xs, ys = normalize_flash_result(output, 0.1164)
        assert_close(VF, 0.44424170, rtol=5e-3)

        P = input_data['P']
        phis_l = output['phis_l']
        phis_g = output['phis_g']
        raw_xs = output['xs']
        raw_ys = output['ys']

        fug_l = [phis_l[i] * raw_xs[i] * P for i in range(2)]
        fug_g = [phis_g[i] * raw_ys[i] * P for i in range(2)]
        assert_close1d(fug_l, fug_g, rtol=1e-3)
