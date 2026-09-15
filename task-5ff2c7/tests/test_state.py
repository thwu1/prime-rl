
"""Verify the SP 800-185 FIPS certification pre-assessment.

Tests validate correct conformance status, defect classification
(including compound detection), security impact assessment,
deployment recommendations, and corrected vendor implementations.
"""

import json
import os
import sys
import pytest
import importlib.util

sys.path.insert(0, '/app')

REPORT_PATH = '/app/audit_report.json'
VECTORS_PATH = '/app/test_vectors.json'


@pytest.fixture(scope='module')
def report():
    assert os.path.exists(REPORT_PATH), \
        f"Audit report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def vectors():
    with open(VECTORS_PATH) as f:
        return json.load(f)


def _load_module(path, name):
    """Import a Python module from a file path."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _verify_cshake(mod, vecs):
    """Run all cSHAKE test vectors against module. Returns True if all pass."""
    for tv in vecs['cshake']:
        data = bytes.fromhex(tv['data'])
        N = tv['N'].encode()
        S = tv['S'].encode()
        try:
            result = mod.cshake(tv['security'], data, tv['output_bits'], N, S)
            if result.hex() != tv['expected']:
                return False
        except Exception:
            return False
    return True


def _verify_kmac(mod, vecs):
    """Run all KMAC test vectors against module. Returns True if all pass."""
    for tv in vecs['kmac']:
        key = bytes.fromhex(tv['key'])
        data = bytes.fromhex(tv['data'])
        S = tv['S'].encode()
        try:
            result = mod.kmac(tv['security'], key, data, tv['output_bits'], S)
            if result.hex() != tv['expected']:
                return False
        except Exception:
            return False
    return True


def _verify_tuplehash(mod, vecs):
    """Run all TupleHash test vectors against module. Returns True if all pass."""
    for tv in vecs['tuplehash']:
        tuples_data = [bytes.fromhex(t) for t in tv['tuples']]
        S = tv['S'].encode()
        try:
            result = mod.tuplehash(tv['security'], tuples_data,
                                    tv['output_bits'], S)
            if result.hex() != tv['expected']:
                return False
        except Exception:
            return False
    return True


# ===== Report Structure Tests =====

class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH)

    def test_valid_json(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_has_candidates(self, report):
        assert 'candidates' in report

    def test_all_vendors_present(self, report):
        for v in ['vendor_alpha', 'vendor_beta', 'vendor_gamma', 'vendor_delta']:
            assert v in report['candidates'], f"Missing vendor: {v}"

    def test_has_selected_vendor(self, report):
        assert 'selected_vendor' in report


# ===== Vendor Alpha: cSHAKE ok, KMAC independent defect, TupleHash ok =====

class TestVendorAlpha:
    def _v(self, report):
        return report['candidates']['vendor_alpha']

    def test_cshake_pass(self, report):
        assert self._v(report)['cshake'] == 'pass'

    def test_kmac_fail(self, report):
        assert self._v(report)['kmac'] == 'fail'

    def test_tuplehash_pass(self, report):
        assert self._v(report)['tuplehash'] == 'pass'

    def test_recommendation_reject(self, report):
        assert self._v(report)['recommendation'] == 'reject'

    def test_has_defects(self, report):
        assert len(self._v(report)['defects']) >= 1

    def test_kmac_defect_classification(self, report):
        defects = self._v(report)['defects']
        kmac_d = [d for d in defects if d['function'] == 'kmac']
        assert len(kmac_d) >= 1
        assert kmac_d[0]['classification'] == 'independent'

    def test_kmac_security_impact(self, report):
        defects = self._v(report)['defects']
        kmac_d = [d for d in defects if d['function'] == 'kmac']
        assert len(kmac_d) >= 1
        assert kmac_d[0]['security_impact'] == 'high'


# ===== Vendor Beta: compound defect in KMAC =====

class TestVendorBeta:
    def _v(self, report):
        return report['candidates']['vendor_beta']

    def test_cshake_fail(self, report):
        assert self._v(report)['cshake'] == 'fail'

    def test_kmac_fail(self, report):
        assert self._v(report)['kmac'] == 'fail'

    def test_tuplehash_fail(self, report):
        assert self._v(report)['tuplehash'] == 'fail'

    def test_recommendation_reject(self, report):
        assert self._v(report)['recommendation'] == 'reject'

    def test_cshake_defect_independent(self, report):
        defects = self._v(report)['defects']
        cs_d = [d for d in defects if d['function'] == 'cshake']
        assert len(cs_d) >= 1
        assert cs_d[0]['classification'] == 'independent'

    def test_cshake_security_critical(self, report):
        defects = self._v(report)['defects']
        cs_d = [d for d in defects if d['function'] == 'cshake']
        assert len(cs_d) >= 1
        assert cs_d[0]['security_impact'] == 'critical'

    def test_kmac_defect_compound(self, report):
        """KMAC has both inherited cSHAKE defect and own independent bug."""
        defects = self._v(report)['defects']
        kmac_d = [d for d in defects if d['function'] == 'kmac']
        assert len(kmac_d) >= 1
        assert kmac_d[0]['classification'] == 'compound'

    def test_kmac_inherited_from_cshake(self, report):
        defects = self._v(report)['defects']
        kmac_d = [d for d in defects if d['function'] == 'kmac']
        assert len(kmac_d) >= 1
        assert kmac_d[0]['inherited_from'] == 'cshake'

    def test_kmac_security_high(self, report):
        defects = self._v(report)['defects']
        kmac_d = [d for d in defects if d['function'] == 'kmac']
        assert len(kmac_d) >= 1
        assert kmac_d[0]['security_impact'] == 'high'

    def test_tuplehash_defect_inherited(self, report):
        defects = self._v(report)['defects']
        th_d = [d for d in defects if d['function'] == 'tuplehash']
        assert len(th_d) >= 1
        assert th_d[0]['classification'] == 'inherited'

    def test_tuplehash_security_null(self, report):
        defects = self._v(report)['defects']
        th_d = [d for d in defects if d['function'] == 'tuplehash']
        assert len(th_d) >= 1
        assert th_d[0]['security_impact'] is None


# ===== Vendor Gamma: fully conformant =====

class TestVendorGamma:
    def _v(self, report):
        return report['candidates']['vendor_gamma']

    def test_cshake_pass(self, report):
        assert self._v(report)['cshake'] == 'pass'

    def test_kmac_pass(self, report):
        assert self._v(report)['kmac'] == 'pass'

    def test_tuplehash_pass(self, report):
        assert self._v(report)['tuplehash'] == 'pass'

    def test_recommendation_deploy(self, report):
        assert self._v(report)['recommendation'] == 'deploy'

    def test_no_defects(self, report):
        assert len(self._v(report)['defects']) == 0


# ===== Vendor Delta: TupleHash independent defect =====

class TestVendorDelta:
    def _v(self, report):
        return report['candidates']['vendor_delta']

    def test_cshake_pass(self, report):
        assert self._v(report)['cshake'] == 'pass'

    def test_kmac_pass(self, report):
        assert self._v(report)['kmac'] == 'pass'

    def test_tuplehash_fail(self, report):
        assert self._v(report)['tuplehash'] == 'fail'

    def test_recommendation_reject(self, report):
        assert self._v(report)['recommendation'] == 'reject'

    def test_tuplehash_defect_independent(self, report):
        defects = self._v(report)['defects']
        th_d = [d for d in defects if d['function'] == 'tuplehash']
        assert len(th_d) >= 1
        assert th_d[0]['classification'] == 'independent'

    def test_tuplehash_security_critical(self, report):
        defects = self._v(report)['defects']
        th_d = [d for d in defects if d['function'] == 'tuplehash']
        assert len(th_d) >= 1
        assert th_d[0]['security_impact'] == 'critical'


# ===== Selected Vendor =====

class TestSelectedVendor:
    def test_selected_vendor_is_gamma(self, report):
        assert report['selected_vendor'] == 'vendor_gamma'


# ===== Patched Implementation Tests =====

@pytest.fixture(scope='module')
def patched_alpha():
    path = '/app/patched/vendor_alpha.py'
    assert os.path.exists(path), "Patched vendor_alpha.py not found"
    return _load_module(path, 'patched_alpha')


@pytest.fixture(scope='module')
def patched_beta():
    path = '/app/patched/vendor_beta.py'
    assert os.path.exists(path), "Patched vendor_beta.py not found"
    return _load_module(path, 'patched_beta')


@pytest.fixture(scope='module')
def patched_delta():
    path = '/app/patched/vendor_delta.py'
    assert os.path.exists(path), "Patched vendor_delta.py not found"
    return _load_module(path, 'patched_delta')


class TestPatchedAlpha:
    """Patched Alpha must pass all NIST vectors."""

    def test_exists(self):
        assert os.path.exists('/app/patched/vendor_alpha.py')

    def test_cshake_conformant(self, patched_alpha, vectors):
        assert _verify_cshake(patched_alpha, vectors)

    def test_kmac_conformant(self, patched_alpha, vectors):
        assert _verify_kmac(patched_alpha, vectors)

    def test_tuplehash_conformant(self, patched_alpha, vectors):
        assert _verify_tuplehash(patched_alpha, vectors)


class TestPatchedBeta:
    """Patched Beta must pass all NIST vectors — requires fixing both
    the cSHAKE dependency and the independent KMAC construction error."""

    def test_exists(self):
        assert os.path.exists('/app/patched/vendor_beta.py')

    def test_cshake_conformant(self, patched_beta, vectors):
        assert _verify_cshake(patched_beta, vectors)

    def test_kmac_conformant(self, patched_beta, vectors):
        assert _verify_kmac(patched_beta, vectors)

    def test_tuplehash_conformant(self, patched_beta, vectors):
        assert _verify_tuplehash(patched_beta, vectors)


class TestPatchedDelta:
    """Patched Delta must pass all NIST vectors."""

    def test_exists(self):
        assert os.path.exists('/app/patched/vendor_delta.py')

    def test_cshake_conformant(self, patched_delta, vectors):
        assert _verify_cshake(patched_delta, vectors)

    def test_kmac_conformant(self, patched_delta, vectors):
        assert _verify_kmac(patched_delta, vectors)

    def test_tuplehash_conformant(self, patched_delta, vectors):
        assert _verify_tuplehash(patched_delta, vectors)
