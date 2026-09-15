
import ctypes
import json
import os
import sys
import importlib.util
import pytest

EXPECTED = {
    10:      {'pi': 4,     'M': -1,  'phi_sum': 32,           'Q': 7,      'L': 0},
    100:     {'pi': 25,    'M': 1,   'phi_sum': 3044,         'Q': 61,     'L': -2},
    10000:   {'pi': 1229,  'M': -23, 'phi_sum': 30397486,     'Q': 6083,   'L': -94},
    1000000: {'pi': 78498, 'M': 212, 'phi_sum': 303963552392, 'Q': 607926, 'L': -530},
}

LIB_PATH = '/app/build/libntsum.so'
BINDINGS_PATH = '/app/ntsum_bindings.py'
EVAL_PATH = '/app/evaluation.json'


@pytest.fixture(scope='session')
def ntlib():
    """Load the shared library directly via ctypes."""
    assert os.path.exists(LIB_PATH), f"Shared library not found at {LIB_PATH}"
    lib = ctypes.CDLL(LIB_PATH)
    for fname in ['ntsum_prime_count', 'ntsum_mertens', 'ntsum_totient_sum',
                  'ntsum_squarefree_count', 'ntsum_liouville_sum']:
        fn = getattr(lib, fname)
        fn.argtypes = [ctypes.c_longlong]
        fn.restype = ctypes.c_longlong
    return lib


@pytest.fixture(scope='session')
def bindings():
    """Load the Python bindings module."""
    assert os.path.isfile(BINDINGS_PATH), f"Bindings not found at {BINDINGS_PATH}"
    spec = importlib.util.spec_from_file_location("ntsum_bindings", BINDINGS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSharedLibraryExists:
    def test_library_file_exists(self):
        assert os.path.isfile(LIB_PATH), \
            f"Shared library not found at {LIB_PATH}"

    def test_library_is_elf_shared_object(self):
        assert os.path.isfile(LIB_PATH), f"Missing {LIB_PATH}"
        with open(LIB_PATH, 'rb') as f:
            magic = f.read(4)
        assert magic == b'\x7fELF', "libntsum.so is not a valid ELF file"

    def test_library_exports_symbols(self, ntlib):
        for fname in ['ntsum_prime_count', 'ntsum_mertens', 'ntsum_totient_sum',
                      'ntsum_squarefree_count', 'ntsum_liouville_sum']:
            assert hasattr(ntlib, fname), f"Library missing exported symbol: {fname}"


class TestSharedLibraryCorrectness:
    @pytest.mark.parametrize("N", sorted(EXPECTED.keys()))
    def test_prime_count(self, ntlib, N):
        result = ntlib.ntsum_prime_count(N)
        expected = EXPECTED[N]['pi']
        assert result == expected, f"pi({N}): expected {expected}, got {result}"

    @pytest.mark.parametrize("N", sorted(EXPECTED.keys()))
    def test_mertens(self, ntlib, N):
        result = ntlib.ntsum_mertens(N)
        expected = EXPECTED[N]['M']
        assert result == expected, f"M({N}): expected {expected}, got {result}"

    @pytest.mark.parametrize("N", sorted(EXPECTED.keys()))
    def test_totient_sum(self, ntlib, N):
        result = ntlib.ntsum_totient_sum(N)
        expected = EXPECTED[N]['phi_sum']
        assert result == expected, f"phi_sum({N}): expected {expected}, got {result}"

    @pytest.mark.parametrize("N", sorted(EXPECTED.keys()))
    def test_squarefree_count(self, ntlib, N):
        result = ntlib.ntsum_squarefree_count(N)
        expected = EXPECTED[N]['Q']
        assert result == expected, f"Q({N}): expected {expected}, got {result}"

    @pytest.mark.parametrize("N", sorted(EXPECTED.keys()))
    def test_liouville_sum(self, ntlib, N):
        result = ntlib.ntsum_liouville_sum(N)
        expected = EXPECTED[N]['L']
        assert result == expected, f"L({N}): expected {expected}, got {result}"


class TestLiouvilleCrosscheck:
    def test_liouville_sieve_crosscheck(self, ntlib):
        """Cross-check L(N) against direct Liouville sieve for N=10000."""
        N = 10000
        spf = list(range(N + 1))
        for i in range(2, int(N**0.5) + 2):
            if spf[i] == i:
                for j in range(i * i, N + 1, i):
                    if spf[j] == j:
                        spf[j] = i
        lam = [0] * (N + 1)
        lam[1] = 1
        for i in range(2, N + 1):
            lam[i] = -lam[i // spf[i]]
        expected_L = sum(lam[1:])
        assert expected_L == -94, f"Sieve sanity: L(10000) = {expected_L}"
        result = ntlib.ntsum_liouville_sum(N)
        assert result == expected_L, \
            f"L({N}): expected {expected_L} (sieve), got {result}"


class TestPythonBindings:
    def test_bindings_file_exists(self):
        assert os.path.isfile(BINDINGS_PATH), \
            f"Python bindings not found at {BINDINGS_PATH}"

    def test_bindings_has_all_functions(self, bindings):
        for fname in ['ntsum_prime_count', 'ntsum_mertens', 'ntsum_totient_sum',
                      'ntsum_squarefree_count', 'ntsum_liouville_sum']:
            assert hasattr(bindings, fname), \
                f"Bindings module missing function: {fname}"

    def test_bindings_prime_count(self, bindings):
        assert bindings.ntsum_prime_count(10000) == 1229

    def test_bindings_mertens(self, bindings):
        assert bindings.ntsum_mertens(10000) == -23

    def test_bindings_totient_sum(self, bindings):
        assert bindings.ntsum_totient_sum(10000) == 30397486

    def test_bindings_squarefree_count(self, bindings):
        assert bindings.ntsum_squarefree_count(10000) == 6083

    def test_bindings_liouville_sum(self, bindings):
        assert bindings.ntsum_liouville_sum(10000) == -94

    def test_bindings_large_values(self, bindings):
        """Test all functions at N=10^6 via bindings."""
        exp = EXPECTED[1000000]
        assert bindings.ntsum_prime_count(1000000) == exp['pi']
        assert bindings.ntsum_mertens(1000000) == exp['M']
        assert bindings.ntsum_totient_sum(1000000) == exp['phi_sum']
        assert bindings.ntsum_squarefree_count(1000000) == exp['Q']
        assert bindings.ntsum_liouville_sum(1000000) == exp['L']


class TestEvaluationReport:
    @pytest.fixture
    def eval_data(self):
        assert os.path.isfile(EVAL_PATH), \
            f"Evaluation report not found at {EVAL_PATH}"
        with open(EVAL_PATH) as f:
            data = json.load(f)
        return data

    def test_has_optimization_levels(self, eval_data):
        for key in ['O0', 'O2', 'O3']:
            assert key in eval_data, f"Missing optimization level key: {key}"

    def test_level_structure(self, eval_data):
        for level in ['O0', 'O2', 'O3']:
            entry = eval_data[level]
            assert isinstance(entry, dict), f"{level} should be a dict"
            for metric in ['prime_count_ms', 'mertens_ms']:
                assert metric in entry, f"{level} missing {metric}"
                val = entry[metric]
                assert isinstance(val, (int, float)), \
                    f"{level}.{metric} should be numeric, got {type(val)}"
                assert val > 0, f"{level}.{metric} must be positive, got {val}"

    def test_has_recommended(self, eval_data):
        assert 'recommended' in eval_data, "Missing 'recommended' key"
        assert eval_data['recommended'] in ['O0', 'O2', 'O3'], \
            f"'recommended' must be O0, O2, or O3, got {eval_data['recommended']}"

    def test_has_speedup(self, eval_data):
        assert 'speedup_vs_O0' in eval_data, "Missing 'speedup_vs_O0' key"
        speedup = eval_data['speedup_vs_O0']
        assert isinstance(speedup, (int, float)), "speedup_vs_O0 must be numeric"
        assert speedup >= 1.0, \
            f"speedup_vs_O0 should be >= 1.0 (optimized >= unoptimized), got {speedup}"

    def test_speedup_internally_consistent(self, eval_data):
        """The reported speedup should match the ratio of O0 to recommended totals."""
        o0_total = eval_data['O0']['prime_count_ms'] + eval_data['O0']['mertens_ms']
        rec = eval_data['recommended']
        rec_total = eval_data[rec]['prime_count_ms'] + eval_data[rec]['mertens_ms']
        if rec_total > 0:
            expected_speedup = o0_total / rec_total
            actual_speedup = eval_data['speedup_vs_O0']
            # Allow 15% tolerance for rounding
            assert abs(actual_speedup - expected_speedup) / max(expected_speedup, 0.01) < 0.15, \
                f"speedup_vs_O0={actual_speedup} inconsistent with data " \
                f"(O0={o0_total:.1f}ms, {rec}={rec_total:.1f}ms, expected ratio={expected_speedup:.2f})"

    def test_recommended_not_slowest(self, eval_data):
        """The recommended level should not be the slowest option."""
        totals = {}
        for level in ['O0', 'O2', 'O3']:
            totals[level] = eval_data[level]['prime_count_ms'] + eval_data[level]['mertens_ms']
        slowest = max(totals, key=totals.get)
        # If all are equal, any recommendation is fine
        if len(set(round(v, 1) for v in totals.values())) > 1:
            assert eval_data['recommended'] != slowest, \
                f"Recommended '{eval_data['recommended']}' is the slowest option"
