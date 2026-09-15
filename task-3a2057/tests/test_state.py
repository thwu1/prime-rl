
"""
Tests for the FPCore-to-C accuracy optimization pipeline.

Verifies:
- C shared library (libimproved.so) exists with correct exported symbols
- Makefile builds the library correctly
- Python ctypes bindings work
- Each improved function achieves relative error < 1e-12
- report.json has correct structure and metrics
"""

import os
import sys
import json
import ctypes
import subprocess
import pytest
import mpmath

mpmath.mp.dps = 50


def relative_error(computed, reference_mp):
    """Compute relative error between float64 result and mpmath reference."""
    ref_float = float(reference_mp)
    if ref_float == 0.0:
        return abs(computed)
    return abs((computed - ref_float) / ref_float)


def load_improved_lib():
    """Load libimproved.so via ctypes."""
    lib_path = '/app/libimproved.so'
    if not os.path.exists(lib_path):
        pytest.fail(f"Shared library not found: {lib_path}")
    lib = ctypes.CDLL(lib_path)
    return lib


# ---------------------------------------------------------------------------
# Build pipeline verification
# ---------------------------------------------------------------------------

class TestBuildPipeline:
    """Verify the Makefile and shared library build correctly."""

    def test_so_exists(self):
        assert os.path.exists('/app/libimproved.so'), \
            "libimproved.so not found at /app/libimproved.so"

    def test_makefile_exists(self):
        assert os.path.exists('/app/Makefile'), \
            "Makefile not found at /app/Makefile"

    def test_makefile_has_shared_flag(self):
        with open('/app/Makefile') as f:
            content = f.read()
        assert '-shared' in content, \
            "Makefile must contain -shared flag for shared library"

    def test_makefile_has_fpic(self):
        with open('/app/Makefile') as f:
            content = f.read()
        assert 'fPIC' in content or 'fpic' in content, \
            "Makefile must contain position-independent code flag (-fPIC)"

    def test_makefile_references_source(self):
        with open('/app/Makefile') as f:
            content = f.read()
        assert 'improved.c' in content, \
            "Makefile should reference improved.c"

    def test_make_succeeds(self):
        result = subprocess.run(
            ['make', '-C', '/app', 'libimproved.so'],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, \
            f"make libimproved.so failed: {result.stderr}"

    def test_exports_all_symbols(self):
        result = subprocess.run(
            ['nm', '-D', '/app/libimproved.so'],
            capture_output=True, text=True
        )
        symbols = result.stdout
        expected = [
            'improved_sqrt_diff',
            'improved_cos_cancellation',
            'improved_log_ratio',
            'improved_quadratic_root',
            'improved_exp_cancel',
            'improved_hamming_expq3',
        ]
        for name in expected:
            assert name in symbols, \
                f"Symbol {name} not exported from libimproved.so"

    def test_improved_c_exists(self):
        assert os.path.exists('/app/improved.c'), \
            "improved.c not found"

    def test_improved_h_exists(self):
        assert os.path.exists('/app/improved.h'), \
            "improved.h not found"


# ---------------------------------------------------------------------------
# Python ctypes bindings verification
# ---------------------------------------------------------------------------

class TestBindings:
    """Verify bindings.py loads the .so and exposes all functions."""

    def test_bindings_importable(self):
        sys.path.insert(0, '/app')
        import importlib
        if 'bindings' in sys.modules:
            importlib.reload(sys.modules['bindings'])
        else:
            import bindings

    def test_all_functions_exposed(self):
        sys.path.insert(0, '/app')
        import importlib
        if 'bindings' in sys.modules:
            bindings = importlib.reload(sys.modules['bindings'])
        else:
            import bindings
        expected = [
            'improved_sqrt_diff',
            'improved_cos_cancellation',
            'improved_log_ratio',
            'improved_quadratic_root',
            'improved_exp_cancel',
            'improved_hamming_expq3',
        ]
        for name in expected:
            assert hasattr(bindings, name), \
                f"bindings.{name} not found"
            assert callable(getattr(bindings, name)), \
                f"bindings.{name} is not callable"

    def test_bindings_return_floats(self):
        sys.path.insert(0, '/app')
        import importlib
        if 'bindings' in sys.modules:
            bindings = importlib.reload(sys.modules['bindings'])
        else:
            import bindings
        result = bindings.improved_sqrt_diff(1.0)
        assert isinstance(result, float), \
            f"improved_sqrt_diff should return float, got {type(result)}"


# ---------------------------------------------------------------------------
# Accuracy tests: load .so via ctypes, compare against mpmath references
# ---------------------------------------------------------------------------

class TestAccuracySqrtDiff:
    """Verify improved_sqrt_diff computes sqrt(x+1)-sqrt(x) accurately."""

    @pytest.fixture(autouse=True)
    def setup(self):
        lib = load_improved_lib()
        self.f = lib.improved_sqrt_diff
        self.f.restype = ctypes.c_double
        self.f.argtypes = [ctypes.c_double]

    @pytest.mark.parametrize("x", [
        0.01, 0.5, 1.0, 100.0,
        1e4, 1e6, 1e8, 1e10, 1e12, 1e15,
    ])
    def test_accuracy(self, x):
        xmp = mpmath.mpf(x)
        ref = mpmath.sqrt(xmp + 1) - mpmath.sqrt(xmp)
        computed = self.f(x)
        err = relative_error(computed, ref)
        assert err < 1e-12, \
            f"improved_sqrt_diff({x}): computed={computed}, ref={float(ref)}, relerr={err}"


class TestAccuracyCosCancellation:
    """Verify improved_cos_cancellation computes (1-cos(x))/x^2 accurately."""

    @pytest.fixture(autouse=True)
    def setup(self):
        lib = load_improved_lib()
        self.f = lib.improved_cos_cancellation
        self.f.restype = ctypes.c_double
        self.f.argtypes = [ctypes.c_double]

    @pytest.mark.parametrize("x", [
        1.0, 0.5, 0.1, 0.01,
        1e-4, 1e-6, 1e-8, 1e-10, 1e-12,
        -0.5, -0.01, -1e-6, -1e-10,
    ])
    def test_accuracy(self, x):
        xmp = mpmath.mpf(x)
        ref = (1 - mpmath.cos(xmp)) / (xmp * xmp)
        computed = self.f(x)
        err = relative_error(computed, ref)
        assert err < 1e-12, \
            f"improved_cos_cancellation({x}): computed={computed}, ref={float(ref)}, relerr={err}"


class TestAccuracyLogRatio:
    """Verify improved_log_ratio computes log((1-x)/(1+x)) accurately."""

    @pytest.fixture(autouse=True)
    def setup(self):
        lib = load_improved_lib()
        self.f = lib.improved_log_ratio
        self.f.restype = ctypes.c_double
        self.f.argtypes = [ctypes.c_double]

    @pytest.mark.parametrize("x", [
        0.5, 0.1, 0.01, 1e-4,
        1e-8, 1e-12, 1e-15, 1e-16, 5e-17,
        -0.3, -0.01, -1e-8, -1e-16,
    ])
    def test_accuracy(self, x):
        xmp = mpmath.mpf(x)
        ref = mpmath.log((1 - xmp) / (1 + xmp))
        computed = self.f(x)
        err = relative_error(computed, ref)
        assert err < 1e-12, \
            f"improved_log_ratio({x}): computed={computed}, ref={float(ref)}, relerr={err}"


class TestAccuracyQuadraticRoot:
    """Verify improved_quadratic_root computes the quadratic root accurately."""

    @pytest.fixture(autouse=True)
    def setup(self):
        lib = load_improved_lib()
        self.f = lib.improved_quadratic_root
        self.f.restype = ctypes.c_double
        self.f.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]

    @pytest.mark.parametrize("a,b,c", [
        (1, 1e8, 1),
        (1, 1e10, 0.5),
        (1, 1e12, 0.5),
        (2, 1e6, 3),
        (0.5, 1e4, 0.1),
        (3, 1e10, 2),
        (1, 1e14, 0.25),
        (1, 10, 1),
        (1, -3, 2),
        (1, 1, -6),
        (1, -10, 24),
    ])
    def test_accuracy(self, a, b, c):
        amp, bmp, cmp = mpmath.mpf(a), mpmath.mpf(b), mpmath.mpf(c)
        d = mpmath.sqrt(bmp * bmp - 4 * amp * cmp)
        ref = (-bmp + d) / (2 * amp)
        computed = self.f(float(a), float(b), float(c))
        err = relative_error(computed, ref)
        assert err < 1e-12, \
            f"improved_quadratic_root({a},{b},{c}): computed={computed}, ref={float(ref)}, relerr={err}"


class TestAccuracyExpCancel:
    """Verify improved_exp_cancel computes 2*(exp(x)-1-x)/x^2 accurately."""

    @pytest.fixture(autouse=True)
    def setup(self):
        lib = load_improved_lib()
        self.f = lib.improved_exp_cancel
        self.f.restype = ctypes.c_double
        self.f.argtypes = [ctypes.c_double]

    @pytest.mark.parametrize("x", [
        2.0, 1.0, 0.5, 0.1, 0.01,
        1e-4, 1e-6, 1e-8, 1e-10, 1e-12, 1e-14,
        -0.5, -0.1, -0.01, -1e-6, -1e-10,
    ])
    def test_accuracy(self, x):
        xmp = mpmath.mpf(x)
        ref = 2 * (mpmath.exp(xmp) - 1 - xmp) / (xmp * xmp)
        computed = self.f(x)
        err = relative_error(computed, ref)
        assert err < 1e-12, \
            f"improved_exp_cancel({x}): computed={computed}, ref={float(ref)}, relerr={err}"


class TestAccuracyHammingExpq3:
    """Verify improved_hamming_expq3 computes the Hamming expq3 expression."""

    @pytest.fixture(autouse=True)
    def setup(self):
        lib = load_improved_lib()
        self.f = lib.improved_hamming_expq3
        self.f.restype = ctypes.c_double
        self.f.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]

    @pytest.mark.parametrize("a,b,eps", [
        (3, 5, 1.0),
        (3, 5, 0.5),
        (2, 7, 0.1),
        (3, 5, 0.01),
        (3, 5, 1e-4),
        (10, 3, 1e-4),
        (3, 5, 1e-8),
        (3, 5, 1e-12),
        (3, 5, 1e-15),
        (1, 1, 1e-10),
        (2, 7, 1e-14),
        (10, 3, 1e-6),
    ])
    def test_accuracy(self, a, b, eps):
        amp, bmp, epsmp = mpmath.mpf(a), mpmath.mpf(b), mpmath.mpf(eps)
        numer = epsmp * (mpmath.exp((amp + bmp) * epsmp) - 1)
        denom = (mpmath.exp(amp * epsmp) - 1) * (mpmath.exp(bmp * epsmp) - 1)
        ref = numer / denom
        computed = self.f(float(a), float(b), float(eps))
        err = relative_error(computed, ref)
        assert err < 1e-12, \
            f"improved_hamming_expq3({a},{b},{eps}): computed={computed}, ref={float(ref)}, relerr={err}"


# ---------------------------------------------------------------------------
# Report structure verification
# ---------------------------------------------------------------------------

class TestReport:
    """Verify report.json exists with correct structure and metrics."""

    @pytest.fixture(autouse=True)
    def setup(self):
        report_path = '/app/report.json'
        if not os.path.exists(report_path):
            pytest.fail(f"report.json not found at {report_path}")
        with open(report_path) as f:
            self.report = json.load(f)

    def test_is_list(self):
        assert isinstance(self.report, list), \
            "report.json must be a JSON array"

    def test_has_six_entries(self):
        assert len(self.report) == 6, \
            f"Expected 6 entries, got {len(self.report)}"

    def test_required_fields(self):
        required = {'name', 'naive_max_relerr', 'improved_max_relerr',
                    'improvement_ratio', 'test_points_count'}
        for entry in self.report:
            missing = required - set(entry.keys())
            assert not missing, \
                f"Entry {entry.get('name', '?')} missing fields: {missing}"

    def test_names_present(self):
        names = {e['name'] for e in self.report}
        expected = {'sqrt_diff', 'cos_cancellation', 'log_ratio',
                    'quadratic_root', 'exp_cancel', 'hamming_expq3'}
        assert names == expected, \
            f"Expected names {expected}, got {names}"

    def test_improved_accuracy_in_report(self):
        for entry in self.report:
            assert entry['improved_max_relerr'] < 1e-12, \
                f"{entry['name']}: improved_max_relerr={entry['improved_max_relerr']} >= 1e-12"

    def test_improvement_ratio_positive(self):
        for entry in self.report:
            assert entry['improvement_ratio'] > 1.0, \
                f"{entry['name']}: improvement_ratio={entry['improvement_ratio']} should be > 1"

    def test_test_points_count(self):
        for entry in self.report:
            assert entry['test_points_count'] >= 5, \
                f"{entry['name']}: test_points_count={entry['test_points_count']} should be >= 5"

    def test_numeric_values(self):
        for entry in self.report:
            assert isinstance(entry['naive_max_relerr'], (int, float)), \
                f"{entry['name']}: naive_max_relerr must be numeric"
            assert isinstance(entry['improved_max_relerr'], (int, float)), \
                f"{entry['name']}: improved_max_relerr must be numeric"
            assert entry['naive_max_relerr'] >= 0, \
                f"{entry['name']}: naive_max_relerr must be non-negative"
