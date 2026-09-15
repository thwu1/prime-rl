"""
Verification tests for the numerical integration pipeline and
the quadrature method evaluation framework.

Validates:
1. The benchmark results file (results.json) is complete and accurate
2. Numerical results are correct (verified via mpmath)
3. The Python library is functional for finite and infinite domains
4. GK-21 internals produce correct Kronrod and Gauss estimates (anti-cheat)
5. The C shared library (libquad.so) exists and works correctly
6. Cross-validation entries exist for finite-domain integrals
7. Library output matches results.json values (anti-cheat)
8. The evaluation framework (evaluation.json) has correct structure
9. Evaluation best values match analytical references
10. Evaluation rankings are consistent and correct
11. Evaluation values match independent C library calls (anti-cheat)
"""

import ctypes
import json
import math
import os
import sys
import pytest

sys.path.insert(0, '/app')

RESULTS_PATH = '/app/results.json'
EVAL_PATH = '/app/evaluation.json'
LIBQUAD_PATH = '/app/libquad.so'

BENCHMARKS = [
    'smooth_arctan',
    'log_log_product',
    'log_fourth_power',
    'gaussian_integral',
    'sech_squared',
    'planck_integral',
]

FINITE_BENCHMARKS = [
    'smooth_arctan',
    'log_log_product',
    'log_fourth_power',
]

EVAL_INTEGRANDS = [
    'smooth_rational',
    'log_power',
    'sqrt_inverse',
    'beta_singular',
    'log_product',
    'log_sin',
]


def _reference_values():
    """Compute reference values independently using mpmath."""
    import mpmath
    mpmath.mp.dps = 50
    pi = mpmath.pi
    refs = {}
    refs['smooth_arctan'] = float(pi)
    refs['log_log_product'] = float(2 - pi ** 2 / 6)
    refs['log_fourth_power'] = float(mpmath.gamma(5))
    refs['gaussian_integral'] = float(mpmath.sqrt(pi) / 2)
    refs['sech_squared'] = 2.0
    refs['planck_integral'] = float(pi ** 4 / 15)
    return refs


def _eval_reference_values():
    """Compute true reference values for evaluation integrands via mpmath."""
    import mpmath
    mpmath.mp.dps = 50
    pi = mpmath.pi
    refs = {}
    refs['smooth_rational'] = float(pi)
    refs['log_power'] = float(mpmath.gamma(5))
    refs['sqrt_inverse'] = 2.0
    refs['beta_singular'] = float(pi)
    refs['log_product'] = float(2 - pi ** 2 / 6)
    refs['log_sin'] = float(-(pi / 2) * mpmath.log(2))
    return refs


# =====================================================================
# Test Suite 1: Results File Structure
# =====================================================================


class TestResultsFile:

    @pytest.fixture(scope='class')
    def data(self):
        assert os.path.exists(RESULTS_PATH), f'{RESULTS_PATH} not found'
        with open(RESULTS_PATH) as f:
            return json.load(f)

    def test_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_all_benchmarks_present(self, data):
        for name in BENCHMARKS:
            assert name in data, f'Missing benchmark: {name}'

    def test_each_has_required_fields(self, data):
        for name in BENCHMARKS:
            entry = data[name]
            for field in ('value', 'reference', 'relative_error', 'passed'):
                assert field in entry, f'{name}: missing field "{field}"'

    def test_all_benchmarks_passed(self, data):
        for name in BENCHMARKS:
            assert data[name]['passed'] is True, (
                f"{name}: passed={data[name]['passed']}, "
                f"rel_error={data[name].get('relative_error')}, "
                f"error={data[name].get('error', 'none')}"
            )

    def test_no_error_field(self, data):
        """No benchmark should have raised an exception."""
        for name in BENCHMARKS:
            assert 'error' not in data[name], (
                f"{name}: has error: {data[name].get('error')}"
            )


# =====================================================================
# Test Suite 2: Numerical Accuracy (cross-check via mpmath)
# =====================================================================


class TestNumericalAccuracy:

    @pytest.fixture(scope='class')
    def data(self):
        with open(RESULTS_PATH) as f:
            return json.load(f)

    @pytest.fixture(scope='class')
    def refs(self):
        return _reference_values()

    @pytest.mark.parametrize('name', BENCHMARKS)
    def test_accuracy(self, data, refs, name):
        """Computed value must match high-precision analytical reference."""
        val = data[name]['value']
        ref = refs[name]
        if abs(ref) > 0:
            rel_err = abs(val - ref) / abs(ref)
        else:
            rel_err = abs(val)
        assert rel_err < 1e-8, (
            f'{name}: rel_error={rel_err:.2e}, '
            f'computed={val:.15e}, ref={ref:.15e}'
        )


# =====================================================================
# Test Suite 3: Direct Library Calls
# =====================================================================


class TestLibraryDirect:
    """Call quadrature.integrate directly to verify the library works."""

    @pytest.fixture(scope='class')
    def lib(self):
        from quadrature import integrate
        return integrate

    def test_finite_polynomial(self, lib):
        """x^3 on [0,1] = 0.25 -- exact for GK-21."""
        result, err = lib(lambda x: x ** 3, 0.0, 1.0)
        assert abs(result - 0.25) < 1e-14

    def test_finite_singular(self, lib):
        """1/sqrt(x) on (0,1] = 2."""
        def f(x):
            if x <= 0:
                return 0.0
            return 1.0 / math.sqrt(x)
        result, err = lib(f, 0.0, 1.0, tol=1e-10)
        assert abs(result - 2.0) < 1e-6

    def test_semi_infinite(self, lib):
        """exp(-x) on [0, inf) = 1."""
        result, err = lib(lambda x: math.exp(-x), 0.0, math.inf)
        assert abs(result - 1.0) < 1e-6, (
            f'Semi-infinite integral of exp(-x) = {result}, expected 1.0'
        )

    def test_doubly_infinite(self, lib):
        """exp(-x^2) on (-inf, inf) = sqrt(pi)."""
        result, err = lib(
            lambda x: math.exp(-x * x), -math.inf, math.inf
        )
        assert abs(result - math.sqrt(math.pi)) < 1e-6, (
            f'Doubly-infinite Gaussian integral = {result}, '
            f'expected {math.sqrt(math.pi)}'
        )

    def test_smooth_arctan_matches_results(self, lib):
        """Library output must match results.json (anti-cheat)."""
        result, _ = lib(
            lambda x: 4.0 / (1.0 + x * x), 0.0, 1.0, tol=1e-12
        )
        with open(RESULTS_PATH) as f:
            data = json.load(f)
        reported = data['smooth_arctan']['value']
        assert abs(result - reported) < 1e-14, (
            f'Library returned {result:.15e}, but results.json has '
            f'{reported:.15e}. Was the library used to generate results?'
        )

    def test_gaussian_matches_results(self, lib):
        """Semi-infinite library output must match results.json (anti-cheat)."""
        result, _ = lib(
            lambda x: math.exp(-x * x), 0.0, math.inf, tol=1e-12
        )
        with open(RESULTS_PATH) as f:
            data = json.load(f)
        reported = data['gaussian_integral']['value']
        assert abs(result - reported) < 1e-12, (
            f'Library returned {result:.15e}, but results.json has '
            f'{reported:.15e}. Was the library used to generate results?'
        )


# =====================================================================
# Test Suite 4: GK Internals (anti-cheat + correctness)
# =====================================================================


class TestGKInternals:
    """Verify the GK rule internals produce correct results.

    These tests call internal functions directly, which prevents
    bypassing the library with scipy or hardcoded values.
    """

    def test_gk21_function_exists(self):
        from quadrature import _apply_gk21
        assert callable(_apply_gk21)

    def test_gk21_kronrod_exact_for_degree_20(self):
        """GK-21 Kronrod estimate must be exact for degree-20 polynomials."""
        from quadrature import _apply_gk21
        # x^20 on [-1, 1] = 2/21
        res_k, res_g, _ = _apply_gk21(lambda x: x ** 20, -1.0, 1.0)
        expected = 2.0 / 21.0
        assert abs(res_k - expected) < 1e-13, (
            f'GK-21 Kronrod: {res_k:.15e}, expected {expected:.15e}'
        )

    def test_gk21_gauss_exact_for_degree_8(self):
        """Embedded G-10 estimate must be exact for degree-8 polynomials.

        If the Gauss node selection parity is wrong, this test will fail.
        """
        from quadrature import _apply_gk21
        # x^8 on [-1, 1] = 2/9
        res_k, res_g, _ = _apply_gk21(lambda x: x ** 8, -1.0, 1.0)
        expected = 2.0 / 9.0
        assert abs(res_k - expected) < 1e-13, (
            f'Kronrod: {res_k:.15e}, expected {expected:.15e}'
        )
        assert abs(res_g - expected) < 1e-13, (
            f'G-10 Gauss: {res_g:.15e}, expected {expected:.15e}'
        )

    def test_gk15_gauss_exact_for_degree_6(self):
        """Embedded G-7 in GK-15 must be exact for degree-6 polynomials."""
        from quadrature import _apply_gk15
        # x^6 on [-1, 1] = 2/7
        res_k, res_g, _ = _apply_gk15(lambda x: x ** 6, -1.0, 1.0)
        expected = 2.0 / 7.0
        assert abs(res_k - expected) < 1e-13, (
            f'GK-15 Kronrod: {res_k:.15e}, expected {expected:.15e}'
        )
        assert abs(res_g - expected) < 1e-13, (
            f'G-7 Gauss: {res_g:.15e}, expected {expected:.15e}'
        )

    def test_gk21_gauss_differs_from_kronrod_on_high_degree(self):
        """For degree-22, Kronrod should be exact but G-10 should not."""
        from quadrature import _apply_gk21
        # x^22 on [-1, 1] = 2/23; G-10 exact only for degree <= 19
        res_k, res_g, _ = _apply_gk21(lambda x: x ** 22, -1.0, 1.0)
        expected = 2.0 / 23.0
        assert abs(res_k - expected) < 1e-13
        assert abs(res_g - expected) > 1e-10, (
            f'G-10 should not be exact for degree 22, but got {res_g:.15e} '
            f'vs expected {expected:.15e}'
        )


# =====================================================================
# Test Suite 5: C Shared Library
# =====================================================================


class TestCLibrary:
    """Verify that libquad.so exists, is loadable, and works correctly."""

    def test_libquad_exists(self):
        assert os.path.exists(LIBQUAD_PATH), (
            f'{LIBQUAD_PATH} not found -- was it built with make?'
        )

    def test_libquad_loadable(self):
        lib = ctypes.CDLL(LIBQUAD_PATH)
        assert lib is not None

    def test_libquad_has_quad_integrate(self):
        lib = ctypes.CDLL(LIBQUAD_PATH)
        fn = getattr(lib, 'quad_integrate', None)
        assert fn is not None, 'quad_integrate symbol not found in libquad.so'

    def test_gsl_integration_correct(self):
        """Call the C library directly to verify x^2 on [0,1] = 1/3.

        Uses correct ctypes declarations to test the C library
        independently of gsl_bridge.py.
        """
        lib = ctypes.CDLL(LIBQUAD_PATH)
        IFUNC = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_double)

        lib.quad_integrate.restype = ctypes.c_double
        lib.quad_integrate.argtypes = [
            IFUNC,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]

        abserr = ctypes.c_double(0.0)
        neval = ctypes.c_int(0)
        status = ctypes.c_int(0)

        def x_squared(x):
            return x * x

        cb = IFUNC(x_squared)

        result = lib.quad_integrate(
            cb, 0.0, 1.0, 1e-12, 1e-12, 0,
            ctypes.byref(abserr),
            ctypes.byref(neval),
            ctypes.byref(status),
        )

        assert status.value == 0, (
            f'GSL returned error status {status.value} for method=0'
        )
        expected = 1.0 / 3.0
        assert abs(result - expected) < 1e-10, (
            f'x^2 integral = {result}, expected {expected}'
        )


# =====================================================================
# Test Suite 6: Cross-Validation
# =====================================================================


class TestCrossValidation:
    """Verify that finite-domain results include GSL cross-validation."""

    @pytest.fixture(scope='class')
    def data(self):
        with open(RESULTS_PATH) as f:
            return json.load(f)

    @pytest.mark.parametrize('name', FINITE_BENCHMARKS)
    def test_gsl_value_present(self, data, name):
        """Finite-domain benchmarks must include gsl_value."""
        assert 'gsl_value' in data[name], (
            f'{name}: missing gsl_value -- GSL cross-validation required'
        )

    @pytest.mark.parametrize('name', FINITE_BENCHMARKS)
    def test_cross_validation_agreement(self, data, name):
        """Python and GSL results must agree for finite-domain integrals."""
        py_val = data[name]['value']
        gsl_val = data[name]['gsl_value']
        ref = data[name]['reference']
        cross_err = (abs(py_val - gsl_val) / abs(ref)
                     if ref != 0 else abs(py_val - gsl_val))
        assert cross_err < 1e-8, (
            f'{name}: Python={py_val:.15e}, GSL={gsl_val:.15e}, '
            f'cross_err={cross_err:.2e}'
        )


# =====================================================================
# Test Suite 7: Evaluation File Structure
# =====================================================================


class TestEvaluationStructure:
    """Verify evaluation.json exists and has correct structure."""

    @pytest.fixture(scope='class')
    def data(self):
        assert os.path.exists(EVAL_PATH), f'{EVAL_PATH} not found'
        with open(EVAL_PATH) as f:
            return json.load(f)

    def test_file_exists(self):
        assert os.path.exists(EVAL_PATH)

    def test_has_benchmarks(self, data):
        assert 'benchmarks' in data

    def test_all_integrands_present(self, data):
        for name in EVAL_INTEGRANDS:
            assert name in data['benchmarks'], (
                f'Missing evaluation integrand: {name}'
            )

    def test_each_has_7_methods(self, data):
        for name in EVAL_INTEGRANDS:
            methods = data['benchmarks'][name]['methods']
            for mid in range(7):
                assert str(mid) in methods, (
                    f'{name}: missing method {mid}'
                )

    def test_method_entries_complete(self, data):
        for name in EVAL_INTEGRANDS:
            for mid in range(7):
                entry = data['benchmarks'][name]['methods'][str(mid)]
                for field in ('value', 'abserr', 'neval', 'status'):
                    assert field in entry, (
                        f'{name} method {mid}: missing field "{field}"'
                    )

    def test_has_best_method_and_ranking(self, data):
        for name in EVAL_INTEGRANDS:
            bm = data['benchmarks'][name]
            assert 'best_method' in bm, f'{name}: missing best_method'
            assert 'best_value' in bm, f'{name}: missing best_value'
            assert 'ranking' in bm, f'{name}: missing ranking'

    def test_ranking_is_valid_permutation(self, data):
        for name in EVAL_INTEGRANDS:
            ranking = data['benchmarks'][name]['ranking']
            assert sorted(ranking) == list(range(7)), (
                f'{name}: ranking {ranking} is not a permutation of 0-6'
            )

    def test_best_method_is_first_in_ranking(self, data):
        for name in EVAL_INTEGRANDS:
            bm = data['benchmarks'][name]
            assert bm['ranking'][0] == bm['best_method'], (
                f'{name}: best_method={bm["best_method"]} '
                f'but ranking starts with {bm["ranking"][0]}'
            )

    def test_has_overall_ranking(self, data):
        assert 'overall_ranking' in data
        overall = data['overall_ranking']
        assert sorted(overall) == list(range(7)), (
            f'overall_ranking {overall} is not a permutation of 0-6'
        )

    def test_has_method_names(self, data):
        assert 'method_names' in data
        for mid in range(7):
            assert str(mid) in data['method_names']


# =====================================================================
# Test Suite 8: Evaluation Accuracy
# =====================================================================


class TestEvaluationAccuracy:
    """Verify best values match true analytical references."""

    @pytest.fixture(scope='class')
    def data(self):
        with open(EVAL_PATH) as f:
            return json.load(f)

    @pytest.fixture(scope='class')
    def refs(self):
        return _eval_reference_values()

    @pytest.mark.parametrize('name', EVAL_INTEGRANDS)
    def test_best_value_accuracy(self, data, refs, name):
        """Best method must produce a value close to the true answer."""
        best = data['benchmarks'][name]['best_value']
        ref = refs[name]
        if abs(ref) > 0:
            rel_err = abs(best - ref) / abs(ref)
        else:
            rel_err = abs(best)
        assert rel_err < 1e-6, (
            f'{name}: best_value={best:.15e}, ref={ref:.15e}, '
            f'rel_err={rel_err:.2e}'
        )


# =====================================================================
# Test Suite 9: Evaluation Rankings
# =====================================================================


class TestEvaluationRankings:
    """Verify rankings are consistent and correct."""

    @pytest.fixture(scope='class')
    def data(self):
        with open(EVAL_PATH) as f:
            return json.load(f)

    @pytest.mark.parametrize('name', EVAL_INTEGRANDS)
    def test_successful_before_failed(self, data, name):
        """Methods with status==0 must be ranked before status!=0."""
        bm = data['benchmarks'][name]
        ranking = bm['ranking']
        methods = bm['methods']
        seen_failed = False
        for mid in ranking:
            status = methods[str(mid)]['status']
            if status != 0:
                seen_failed = True
            elif seen_failed:
                pytest.fail(
                    f'{name}: method {mid} (status=0) ranked '
                    f'after a failed method'
                )

    def test_overall_ranking_by_rank_sum(self, data):
        """Overall ranking must be sorted by rank-sum across integrands."""
        benchmarks = data['benchmarks']
        rank_sums = {m: 0 for m in range(7)}
        for name in EVAL_INTEGRANDS:
            bm = benchmarks[name]
            for pos, mid in enumerate(bm['ranking']):
                rank_sums[mid] += pos

        actual = data['overall_ranking']
        actual_sums = [rank_sums[m] for m in actual]
        for i in range(len(actual_sums) - 1):
            assert actual_sums[i] <= actual_sums[i + 1], (
                f'Overall ranking not sorted by rank-sum: '
                f'method {actual[i]} (sum={actual_sums[i]}) before '
                f'method {actual[i + 1]} (sum={actual_sums[i + 1]})'
            )


# =====================================================================
# Test Suite 10: Evaluation Anti-Cheat
# =====================================================================


class TestEvaluationAntiCheat:
    """Verify evaluation values come from actual C library calls."""

    @pytest.fixture(scope='class')
    def data(self):
        with open(EVAL_PATH) as f:
            return json.load(f)

    def _call_library(self, f_py, a, b, method):
        """Helper: call libquad.so directly with correct ctypes setup."""
        lib = ctypes.CDLL(LIBQUAD_PATH)
        IFUNC = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_double)
        lib.quad_integrate.restype = ctypes.c_double
        lib.quad_integrate.argtypes = [
            IFUNC,
            ctypes.c_double, ctypes.c_double,
            ctypes.c_double, ctypes.c_double,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        abserr = ctypes.c_double(0.0)
        neval = ctypes.c_int(0)
        status = ctypes.c_int(0)
        cb = IFUNC(f_py)
        result = lib.quad_integrate(
            cb, a, b, 1e-12, 1e-12, method,
            ctypes.byref(abserr),
            ctypes.byref(neval),
            ctypes.byref(status),
        )
        return result, status.value

    def test_smooth_rational_gk15_matches(self, data):
        """Verify smooth_rational method 0 matches independent library call."""
        def smooth_rational(x):
            return 4.0 / (1.0 + x * x)

        result, status = self._call_library(smooth_rational, 0.0, 1.0, 0)
        assert status == 0
        eval_val = data['benchmarks']['smooth_rational']['methods']['0']['value']
        assert abs(result - eval_val) < 1e-14, (
            f'Library returns {result:.15e} but evaluation.json has '
            f'{eval_val:.15e} — was libquad.so actually used?'
        )

    def test_sqrt_inverse_qags_matches(self, data):
        """Verify sqrt_inverse QAGS result matches independent library call."""
        def sqrt_inverse(x):
            if x <= 0.0:
                return 0.0
            return 1.0 / math.sqrt(x)

        result, status = self._call_library(sqrt_inverse, 0.0, 1.0, 6)
        eval_entry = data['benchmarks']['sqrt_inverse']['methods']['6']
        if status == 0 and eval_entry['status'] == 0:
            assert abs(result - eval_entry['value']) < 1e-12, (
                f'Library returns {result:.15e} but evaluation.json has '
                f'{eval_entry["value"]:.15e} for sqrt_inverse QAGS'
            )
