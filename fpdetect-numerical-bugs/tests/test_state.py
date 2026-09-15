"""Tests for the precision audit of libfpmath.so"""


import ctypes
import json
import math
import os
import struct

import mpmath

mpmath.mp.dps = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def compute_ulp_error(computed, reference_mpf):
    """Compute ULP error of a float32 result against an mpmath reference."""
    # Safety: if reference is complex (out-of-domain), treat as infinite error
    if isinstance(reference_mpf, mpmath.mpc):
        if reference_mpf.imag != 0:
            return float('inf')
        reference_mpf = reference_mpf.real

    if not math.isfinite(computed):
        ref_f64 = float(reference_mpf)
        if math.isnan(computed) and math.isnan(ref_f64):
            return 0.0
        if (math.isinf(computed) and math.isinf(ref_f64)
                and math.copysign(1.0, computed) == math.copysign(1.0, ref_f64)):
            return 0.0
        return float('inf')

    ref_f64 = float(reference_mpf)
    try:
        ref_f32 = struct.unpack('>f', struct.pack('>f', ref_f64))[0]
    except (OverflowError, struct.error):
        return float('inf')

    if computed == ref_f32:
        return 0.0

    if ref_f32 == 0.0:
        return abs(computed) / (2 ** -149)

    bits = struct.unpack('>I', struct.pack('>f', ref_f32))[0]
    exponent = (bits >> 23) & 0xFF
    if exponent == 0:
        ulp = 2 ** -149
    else:
        ulp = 2.0 ** (exponent - 127 - 23)

    return abs(computed - ref_f32) / ulp


def reference_value(name, inputs):
    """Compute arbitrary-precision reference for a given function."""
    mp_args = [mpmath.mpf(str(x)) for x in inputs]
    if name == 'fp_expm1':
        return mpmath.expm1(mp_args[0])
    elif name == 'fp_log1p':
        return mpmath.log1p(mp_args[0])
    elif name == 'fp_hypot':
        return mpmath.sqrt(mp_args[0] ** 2 + mp_args[1] ** 2)
    elif name == 'fp_sigmoid':
        return 1 / (1 + mpmath.exp(-mp_args[0]))
    elif name == 'fp_sinc':
        if mp_args[0] == 0:
            return mpmath.mpf(1)
        return mpmath.sin(mp_args[0]) / mp_args[0]
    elif name == 'fp_mean':
        return (mp_args[0] + mp_args[1]) / 2
    raise ValueError(f"Unknown function {name}")


def call_func(lib, name, inputs):
    """Call a C function from a loaded shared library."""
    func = getattr(lib, name)
    if len(inputs) == 1:
        func.argtypes = [ctypes.c_float]
        func.restype = ctypes.c_float
        return func(ctypes.c_float(inputs[0]))
    elif len(inputs) == 2:
        func.argtypes = [ctypes.c_float, ctypes.c_float]
        func.restype = ctypes.c_float
        return func(ctypes.c_float(inputs[0]), ctypes.c_float(inputs[1]))
    raise ValueError(f"Unsupported input count: {len(inputs)}")


FLT_MAX = struct.unpack('>f', b'\x7f\x7f\xff\xff')[0]

ALL_FUNCTIONS = ['fp_expm1', 'fp_log1p', 'fp_hypot', 'fp_sigmoid', 'fp_sinc', 'fp_mean']
UNSTABLE_FUNCTIONS = ['fp_expm1', 'fp_log1p', 'fp_hypot', 'fp_sinc', 'fp_mean']


# ===========================================================================
# Audit report tests
# ===========================================================================

class TestAuditReportExists:
    def test_file_exists(self):
        assert os.path.exists('/app/audit_report.json'), \
            "audit_report.json not found at /app/audit_report.json"


class TestAuditReportStructure:
    def test_top_level_key(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        assert 'functions' in report

    def test_all_functions_present(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        for name in ALL_FUNCTIONS:
            assert name in report['functions'], f"Missing function entry: {name}"

    def test_required_fields(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        for name in ALL_FUNCTIONS:
            entry = report['functions'][name]
            assert 'classification' in entry, f"{name}: missing classification"
            assert entry['classification'] in ('stable', 'unstable'), \
                f"{name}: classification must be 'stable' or 'unstable'"
            assert 'max_ulp_error' in entry, f"{name}: missing max_ulp_error"
            assert isinstance(entry['max_ulp_error'], (int, float)), \
                f"{name}: max_ulp_error must be numeric"
            assert 'worst_case_input' in entry, f"{name}: missing worst_case_input"
            assert isinstance(entry['worst_case_input'], list), \
                f"{name}: worst_case_input must be a list"

    def test_unstable_have_bug_type(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        for name in ALL_FUNCTIONS:
            entry = report['functions'][name]
            if entry['classification'] == 'unstable':
                assert 'bug_type' in entry, \
                    f"{name}: unstable functions must have bug_type"


class TestClassifications:
    def test_sigmoid_stable(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        assert report['functions']['fp_sigmoid']['classification'] == 'stable', \
            "fp_sigmoid should be classified as stable"

    def test_expm1_unstable(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        assert report['functions']['fp_expm1']['classification'] == 'unstable'

    def test_log1p_unstable(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        assert report['functions']['fp_log1p']['classification'] == 'unstable'

    def test_hypot_unstable(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        assert report['functions']['fp_hypot']['classification'] == 'unstable'

    def test_sinc_unstable(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        assert report['functions']['fp_sinc']['classification'] == 'unstable'

    def test_mean_unstable(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        assert report['functions']['fp_mean']['classification'] == 'unstable'


class TestBugTypes:
    def test_expm1_catastrophic_cancellation(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        assert report['functions']['fp_expm1']['bug_type'] == 'catastrophic_cancellation'

    def test_log1p_catastrophic_cancellation(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        assert report['functions']['fp_log1p']['bug_type'] == 'catastrophic_cancellation'

    def test_hypot_overflow(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        assert report['functions']['fp_hypot']['bug_type'] == 'overflow'

    def test_sinc_special_value(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        assert report['functions']['fp_sinc']['bug_type'] == 'special_value'

    def test_mean_overflow(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        assert report['functions']['fp_mean']['bug_type'] == 'overflow'


class TestWorstCaseInputs:
    """Verify that reported worst-case inputs produce > 100 ULP error in original."""

    def test_worst_case_produces_large_ulp_error(self):
        with open('/app/audit_report.json') as f:
            report = json.load(f)
        lib = ctypes.CDLL('/app/libfpmath.so')
        for name in UNSTABLE_FUNCTIONS:
            entry = report['functions'][name]
            inputs = entry['worst_case_input']
            result = call_func(lib, name, inputs)
            ref = reference_value(name, inputs)
            ulp_err = compute_ulp_error(result, ref)
            assert ulp_err > 100, \
                f"{name}: worst-case ULP error {ulp_err} should be > 100"


# ===========================================================================
# Original library bug verification
# ===========================================================================

class TestOriginalLibraryBugs:
    def test_expm1_cancellation(self):
        lib = ctypes.CDLL('/app/libfpmath.so')
        lib.fp_expm1.argtypes = [ctypes.c_float]
        lib.fp_expm1.restype = ctypes.c_float
        result = lib.fp_expm1(ctypes.c_float(1e-8))
        ref = float(mpmath.expm1(mpmath.mpf('1e-8')))
        assert abs(result) < abs(ref) * 0.01, \
            f"Original expm1(1e-8) should show catastrophic cancellation, got {result}"

    def test_log1p_cancellation(self):
        lib = ctypes.CDLL('/app/libfpmath.so')
        lib.fp_log1p.argtypes = [ctypes.c_float]
        lib.fp_log1p.restype = ctypes.c_float
        result = lib.fp_log1p(ctypes.c_float(1e-8))
        ref = float(mpmath.log1p(mpmath.mpf('1e-8')))
        assert abs(result) < abs(ref) * 0.01, \
            f"Original log1p(1e-8) should show catastrophic cancellation, got {result}"

    def test_hypot_overflow(self):
        lib = ctypes.CDLL('/app/libfpmath.so')
        lib.fp_hypot.argtypes = [ctypes.c_float, ctypes.c_float]
        lib.fp_hypot.restype = ctypes.c_float
        result = lib.fp_hypot(ctypes.c_float(2e19), ctypes.c_float(2e19))
        assert math.isinf(result), \
            f"Original hypot(2e19, 2e19) should overflow to inf, got {result}"

    def test_sinc_nan_at_zero(self):
        lib = ctypes.CDLL('/app/libfpmath.so')
        lib.fp_sinc.argtypes = [ctypes.c_float]
        lib.fp_sinc.restype = ctypes.c_float
        result = lib.fp_sinc(ctypes.c_float(0.0))
        assert math.isnan(result), \
            f"Original sinc(0) should return NaN, got {result}"

    def test_mean_overflow(self):
        lib = ctypes.CDLL('/app/libfpmath.so')
        lib.fp_mean.argtypes = [ctypes.c_float, ctypes.c_float]
        lib.fp_mean.restype = ctypes.c_float
        result = lib.fp_mean(ctypes.c_float(FLT_MAX), ctypes.c_float(FLT_MAX))
        assert math.isinf(result), \
            f"Original mean(FLT_MAX, FLT_MAX) should overflow to inf, got {result}"


# ===========================================================================
# Fixed library tests
# ===========================================================================

class TestFixedLibraryLoading:
    def test_file_exists(self):
        assert os.path.exists('/app/libfpmath_fixed.so'), \
            "Fixed library not found at /app/libfpmath_fixed.so"

    def test_all_symbols_exported(self):
        lib = ctypes.CDLL('/app/libfpmath_fixed.so')
        for name in ALL_FUNCTIONS:
            assert hasattr(lib, name), f"Missing symbol {name} in fixed library"


class TestFixedExpm1:
    def test_small_input_not_cancelled(self):
        lib = ctypes.CDLL('/app/libfpmath_fixed.so')
        lib.fp_expm1.argtypes = [ctypes.c_float]
        lib.fp_expm1.restype = ctypes.c_float
        result = lib.fp_expm1(ctypes.c_float(1e-8))
        assert result != 0.0, "Fixed expm1(1e-8) should not return 0"

    def test_ulp_accuracy(self):
        lib = ctypes.CDLL('/app/libfpmath_fixed.so')
        lib.fp_expm1.argtypes = [ctypes.c_float]
        lib.fp_expm1.restype = ctypes.c_float
        for x in [1e-8, 1e-6, 1e-4, 0.5, 1.0, 10.0]:
            result = lib.fp_expm1(ctypes.c_float(x))
            ref = mpmath.expm1(mpmath.mpf(str(x)))
            ulp_err = compute_ulp_error(result, ref)
            assert ulp_err <= 4, f"Fixed expm1({x}): ULP error {ulp_err} > 4"


class TestFixedLog1p:
    def test_small_input_not_cancelled(self):
        lib = ctypes.CDLL('/app/libfpmath_fixed.so')
        lib.fp_log1p.argtypes = [ctypes.c_float]
        lib.fp_log1p.restype = ctypes.c_float
        result = lib.fp_log1p(ctypes.c_float(1e-8))
        assert result != 0.0, "Fixed log1p(1e-8) should not return 0"

    def test_ulp_accuracy(self):
        lib = ctypes.CDLL('/app/libfpmath_fixed.so')
        lib.fp_log1p.argtypes = [ctypes.c_float]
        lib.fp_log1p.restype = ctypes.c_float
        for x in [1e-8, 1e-6, 1e-4, 0.5, 1.0, 10.0]:
            result = lib.fp_log1p(ctypes.c_float(x))
            ref = mpmath.log1p(mpmath.mpf(str(x)))
            ulp_err = compute_ulp_error(result, ref)
            assert ulp_err <= 4, f"Fixed log1p({x}): ULP error {ulp_err} > 4"


class TestFixedHypot:
    def test_no_overflow(self):
        lib = ctypes.CDLL('/app/libfpmath_fixed.so')
        lib.fp_hypot.argtypes = [ctypes.c_float, ctypes.c_float]
        lib.fp_hypot.restype = ctypes.c_float
        result = lib.fp_hypot(ctypes.c_float(2e19), ctypes.c_float(2e19))
        assert math.isfinite(result), \
            f"Fixed hypot(2e19, 2e19) should not overflow, got {result}"

    def test_ulp_accuracy(self):
        lib = ctypes.CDLL('/app/libfpmath_fixed.so')
        lib.fp_hypot.argtypes = [ctypes.c_float, ctypes.c_float]
        lib.fp_hypot.restype = ctypes.c_float
        for x, y in [(3.0, 4.0), (1.0, 1.0), (2e19, 2e19), (1e30, 1e30)]:
            result = lib.fp_hypot(ctypes.c_float(x), ctypes.c_float(y))
            ref = mpmath.sqrt(mpmath.mpf(str(x)) ** 2 + mpmath.mpf(str(y)) ** 2)
            assert math.isfinite(result), f"Fixed hypot({x}, {y}) should be finite"
            ulp_err = compute_ulp_error(result, ref)
            assert ulp_err <= 4, f"Fixed hypot({x}, {y}): ULP error {ulp_err} > 4"


class TestFixedSinc:
    def test_zero_returns_one(self):
        lib = ctypes.CDLL('/app/libfpmath_fixed.so')
        lib.fp_sinc.argtypes = [ctypes.c_float]
        lib.fp_sinc.restype = ctypes.c_float
        result = lib.fp_sinc(ctypes.c_float(0.0))
        assert not math.isnan(result), "Fixed sinc(0) should not be NaN"
        assert result == 1.0, f"Fixed sinc(0) should be 1.0, got {result}"

    def test_ulp_accuracy(self):
        lib = ctypes.CDLL('/app/libfpmath_fixed.so')
        lib.fp_sinc.argtypes = [ctypes.c_float]
        lib.fp_sinc.restype = ctypes.c_float
        for x in [0.001, 0.1, 1.0, 2.0, 5.0]:
            result = lib.fp_sinc(ctypes.c_float(x))
            ref = mpmath.sin(mpmath.mpf(str(x))) / mpmath.mpf(str(x))
            ulp_err = compute_ulp_error(result, ref)
            assert ulp_err <= 4, f"Fixed sinc({x}): ULP error {ulp_err} > 4"


class TestFixedMean:
    def test_no_overflow(self):
        lib = ctypes.CDLL('/app/libfpmath_fixed.so')
        lib.fp_mean.argtypes = [ctypes.c_float, ctypes.c_float]
        lib.fp_mean.restype = ctypes.c_float
        result = lib.fp_mean(ctypes.c_float(FLT_MAX), ctypes.c_float(FLT_MAX))
        assert math.isfinite(result), \
            f"Fixed mean(FLT_MAX, FLT_MAX) should not overflow, got {result}"

    def test_exact_large(self):
        lib = ctypes.CDLL('/app/libfpmath_fixed.so')
        lib.fp_mean.argtypes = [ctypes.c_float, ctypes.c_float]
        lib.fp_mean.restype = ctypes.c_float
        result = lib.fp_mean(ctypes.c_float(FLT_MAX), ctypes.c_float(FLT_MAX))
        assert result == FLT_MAX, \
            f"Fixed mean(FLT_MAX, FLT_MAX) should be FLT_MAX, got {result}"

    def test_normal_values(self):
        lib = ctypes.CDLL('/app/libfpmath_fixed.so')
        lib.fp_mean.argtypes = [ctypes.c_float, ctypes.c_float]
        lib.fp_mean.restype = ctypes.c_float
        result = lib.fp_mean(ctypes.c_float(2.0), ctypes.c_float(4.0))
        assert result == 3.0, f"Fixed mean(2, 4) should be 3.0, got {result}"


class TestFixedSigmoid:
    def test_still_correct(self):
        lib = ctypes.CDLL('/app/libfpmath_fixed.so')
        lib.fp_sigmoid.argtypes = [ctypes.c_float]
        lib.fp_sigmoid.restype = ctypes.c_float
        for x in [0.0, 1.0, -1.0, 10.0, -10.0, 50.0, -50.0]:
            result = lib.fp_sigmoid(ctypes.c_float(x))
            ref = 1 / (1 + mpmath.exp(-mpmath.mpf(str(x))))
            ulp_err = compute_ulp_error(result, ref)
            assert ulp_err <= 4, f"Fixed sigmoid({x}): ULP error {ulp_err} > 4"
