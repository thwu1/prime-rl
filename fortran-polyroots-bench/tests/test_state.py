"""Tests for polynomial root-finding benchmark results.

Validates that /app/results.json contains correct root-finding results
for P(x) = (x-1)^8 + 10^{-4} across multiple methods and precision levels.
"""

import json
import os
import numpy as np
import pytest

RESULTS_PATH = '/app/results.json'
COEFFS = [1.0, -8.0, 28.0, -56.0, 70.0, -56.0, 28.0, -8.0, 1.0001]
DEGREE = 8
EXPECTED_R64_METHODS = {'rpoly', 'rpzero', 'rpqr79', 'dpolz', 'polyroots', 'qr_algeq_solver'}
EXPECTED_R128_METHODS = {'rpoly', 'rpzero', 'rpqr79', 'dpolz', 'qr_algeq_solver'}
# Expected root distance from z=1 is 10^{-1/2} ~ 0.31623
EXPECTED_RADIUS = 10.0 ** (-0.5)


@pytest.fixture
def results():
    assert os.path.isfile(RESULTS_PATH), "results.json not found at /app/results.json"
    with open(RESULTS_PATH) as f:
        return json.load(f)


class TestFileStructure:
    """Validate the basic JSON structure."""

    def test_file_exists(self):
        assert os.path.isfile(RESULTS_PATH), "results.json not found"

    def test_valid_json(self):
        with open(RESULTS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_precision_levels_present(self, results):
        assert 'real64' in results, "Missing 'real64' key"
        assert 'real128' in results, "Missing 'real128' key"

    def test_r64_has_methods_and_best(self, results):
        assert 'methods' in results['real64']
        assert 'best_method' in results['real64']

    def test_r128_has_methods_and_best(self, results):
        assert 'methods' in results['real128']
        assert 'best_method' in results['real128']


class TestMethodPresence:
    """Validate that the correct methods are present."""

    def test_r64_all_six_methods(self, results):
        methods = set(results['real64']['methods'].keys())
        for m in EXPECTED_R64_METHODS:
            assert m in methods, f"Method '{m}' missing from real64 results"

    def test_r128_five_methods(self, results):
        methods = set(results['real128']['methods'].keys())
        for m in EXPECTED_R128_METHODS:
            assert m in methods, f"Method '{m}' missing from real128 results"

    def test_r128_no_polyroots_success(self, results):
        """polyroots should not succeed at real128 (requires LAPACK, unavailable at quad precision)."""
        r128_methods = results['real128']['methods']
        if 'polyroots' in r128_methods:
            assert r128_methods['polyroots'].get('status', -1) != 0, \
                "polyroots should not succeed at real128"


class TestRootCount:
    """Verify each successful method found the correct number of roots."""

    def test_r64_root_count(self, results):
        for name, data in results['real64']['methods'].items():
            if data.get('status', -1) == 0:
                assert len(data['roots']) == DEGREE, \
                    f"real64/{name}: expected {DEGREE} roots, got {len(data['roots'])}"

    def test_r128_root_count(self, results):
        for name, data in results['real128']['methods'].items():
            if data.get('status', -1) == 0:
                assert len(data['roots']) == DEGREE, \
                    f"real128/{name}: expected {DEGREE} roots, got {len(data['roots'])}"


class TestBackwardErrors:
    """Validate backward error magnitudes."""

    def test_r64_backward_errors_bounded(self, results):
        """All backward errors at real64 should be below 1e-4."""
        for name, data in results['real64']['methods'].items():
            if data.get('status', -1) == 0:
                berr = data['max_backward_error']
                assert berr is not None, f"real64/{name}: backward error is None"
                assert berr >= 0, f"real64/{name}: negative backward error {berr}"
                assert berr < 1e-4, f"real64/{name}: backward error too large: {berr}"

    def test_r64_some_methods_very_accurate(self, results):
        """At least 3 real64 methods should achieve backward error < 1e-8."""
        count = sum(
            1 for data in results['real64']['methods'].values()
            if data.get('status', -1) == 0
            and data.get('max_backward_error') is not None
            and data['max_backward_error'] < 1e-8
        )
        assert count >= 3, f"Only {count} methods achieved backward error < 1e-8 at real64"

    def test_r128_backward_errors_bounded(self, results):
        """All backward errors at real128 should be below 1e-4."""
        for name, data in results['real128']['methods'].items():
            if data.get('status', -1) == 0:
                berr = data['max_backward_error']
                assert berr is not None, f"real128/{name}: backward error is None"
                assert berr >= 0, f"real128/{name}: negative backward error {berr}"
                assert berr < 1e-4, f"real128/{name}: backward error too large: {berr}"


class TestBestMethod:
    """Validate best_method consistency."""

    def test_r64_best_method_valid(self, results):
        r64 = results['real64']
        best = r64['best_method']
        assert best is not None, "best_method is None for real64"
        assert best in r64['methods'], f"best_method '{best}' not in methods dict"

    def test_r64_best_method_consistent(self, results):
        """best_method should have the smallest max backward error."""
        r64 = results['real64']
        best = r64['best_method']
        best_berr = r64['methods'][best]['max_backward_error']
        for name, data in r64['methods'].items():
            if data.get('status', -1) == 0 and data.get('max_backward_error') is not None:
                assert best_berr <= data['max_backward_error'] + 1e-30, \
                    f"real64: '{best}' (berr={best_berr}) is not best; " \
                    f"'{name}' has berr={data['max_backward_error']}"

    def test_r128_best_method_valid(self, results):
        r128 = results['real128']
        best = r128['best_method']
        assert best is not None, "best_method is None for real128"
        assert best in r128['methods'], f"best_method '{best}' not in methods dict"


class TestRootAccuracy:
    """Verify roots are mathematically correct."""

    def test_roots_are_roots_of_polynomial(self, results):
        """Evaluating P(z) at each reported root should give near-zero."""
        coeffs = np.array(COEFFS, dtype=np.float64)
        for prec in ['real64', 'real128']:
            for name, data in results[prec]['methods'].items():
                if data.get('status', -1) != 0:
                    continue
                for root in data['roots']:
                    z = complex(root['real'], root['imag'])
                    val = np.polyval(coeffs, z)
                    assert abs(val) < 0.1, \
                        f"{prec}/{name}: root ({root['real']:.6f}, {root['imag']:.6f}i) " \
                        f"has |P(z)| = {abs(val):.6e}"

    def test_roots_on_expected_circle(self, results):
        """All roots of (x-1)^8 + 1e-4 lie at distance ~0.31623 from z=1."""
        for prec in ['real64', 'real128']:
            for name, data in results[prec]['methods'].items():
                if data.get('status', -1) != 0:
                    continue
                for root in data['roots']:
                    z = complex(root['real'], root['imag'])
                    dist = abs(z - 1.0)
                    assert abs(dist - EXPECTED_RADIUS) < 0.05, \
                        f"{prec}/{name}: root {z} distance from 1 is {dist:.6f}, " \
                        f"expected ~{EXPECTED_RADIUS:.6f}"

    def test_conjugate_pairing(self, results):
        """Complex roots of a real polynomial come in conjugate pairs."""
        for prec in ['real64', 'real128']:
            for name, data in results[prec]['methods'].items():
                if data.get('status', -1) != 0:
                    continue
                roots = data['roots']
                for root in roots:
                    if abs(root['imag']) > 1e-10:
                        found_conj = any(
                            abs(other['real'] - root['real']) < 1e-4 and
                            abs(other['imag'] + root['imag']) < 1e-4
                            for other in roots
                        )
                        assert found_conj, \
                            f"{prec}/{name}: root ({root['real']:.6f}, {root['imag']:.6f}i) " \
                            f"missing conjugate"

    def test_reference_roots_match(self, results):
        """Each method's roots should match numpy.roots reference within 1e-4."""
        coeffs = np.array(COEFFS, dtype=np.float64)
        ref_roots = np.roots(coeffs)

        for name, data in results['real64']['methods'].items():
            if data.get('status', -1) != 0:
                continue
            computed = [complex(r['real'], r['imag']) for r in data['roots']]
            for root in computed:
                min_dist = min(abs(root - ref) for ref in ref_roots)
                assert min_dist < 1e-4, \
                    f"real64/{name}: root {root} too far from any numpy reference root " \
                    f"(min dist: {min_dist:.6e})"


class TestSortOrder:
    """Verify roots are sorted by real part, then imaginary part."""

    def test_roots_sorted(self, results):
        for prec in ['real64', 'real128']:
            for name, data in results[prec]['methods'].items():
                if data.get('status', -1) != 0:
                    continue
                roots = data['roots']
                for i in range(len(roots) - 1):
                    r1, r2 = roots[i], roots[i + 1]
                    ok = (r1['real'] < r2['real'] - 1e-10) or \
                         (abs(r1['real'] - r2['real']) < 1e-10 and
                          r1['imag'] <= r2['imag'] + 1e-10)
                    assert ok, \
                        f"{prec}/{name}: roots not sorted at index {i}: " \
                        f"({r1['real']:.6f}, {r1['imag']:.6f}) vs " \
                        f"({r2['real']:.6f}, {r2['imag']:.6f})"


class TestPrecisionComparison:
    """Compare real64 vs real128 results."""

    def test_r128_improves_on_r64(self, results):
        """At least 2 common methods should show improved accuracy at real128."""
        r64 = results['real64']['methods']
        r128 = results['real128']['methods']
        common = set(r64.keys()) & set(r128.keys())

        improved = 0
        for name in common:
            d64 = r64[name]
            d128 = r128[name]
            if (d64.get('status', -1) == 0 and d128.get('status', -1) == 0
                    and d64.get('max_backward_error') is not None
                    and d128.get('max_backward_error') is not None):
                if d128['max_backward_error'] < d64['max_backward_error']:
                    improved += 1

        assert improved >= 2, \
            f"Only {improved} methods improved from real64 to real128 (expected >= 2)"
