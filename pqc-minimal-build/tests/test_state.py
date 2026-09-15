
import json
import subprocess
import os
import glob
import pytest


# Expected algorithm parameters per FIPS 203 (ML-KEM) and FIPS 204 (ML-DSA)
EXPECTED_KEMS = {
    "ML-KEM-512": {
        "nist_level": 1,
        "public_key_length": 800,
        "secret_key_length": 1632,
        "ciphertext_length": 768,
        "shared_secret_length": 32,
    },
    "ML-KEM-768": {
        "nist_level": 3,
        "public_key_length": 1184,
        "secret_key_length": 2400,
        "ciphertext_length": 1088,
        "shared_secret_length": 32,
    },
    "ML-KEM-1024": {
        "nist_level": 5,
        "public_key_length": 1568,
        "secret_key_length": 3168,
        "ciphertext_length": 1568,
        "shared_secret_length": 32,
    },
}

EXPECTED_SIGS = {
    "ML-DSA-44": {
        "nist_level": 2,
        "public_key_length": 1312,
        "secret_key_length": 2560,
        "signature_length": 2420,
    },
    "ML-DSA-65": {
        "nist_level": 3,
        "public_key_length": 1952,
        "secret_key_length": 4032,
        "signature_length": 3309,
    },
    "ML-DSA-87": {
        "nist_level": 5,
        "public_key_length": 2592,
        "secret_key_length": 4896,
        "signature_length": 4627,
    },
}

# Algorithms that must NOT be present in a minimal build
EXCLUDED_FAMILIES = [
    "bike", "hqc", "frodokem", "classic_mceliece", "ntruprime", "ntru_h",
    "kyber",
    "falcon", "sphincs", "slh_dsa", "mayo", "cross_rsdp", "uov", "snova", "mqom",
]


def _find_liboqs_so():
    """Find the liboqs shared library under /opt/liboqs/."""
    candidates = (
        glob.glob("/opt/liboqs/lib/liboqs.so*")
        + glob.glob("/opt/liboqs/lib64/liboqs.so*")
        + glob.glob("/opt/liboqs/lib/*/liboqs.so*")
    )
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _get_dynamic_symbols():
    """Return the dynamic symbol table of liboqs.so as a string."""
    lib = _find_liboqs_so()
    assert lib is not None, "liboqs.so not found"
    result = subprocess.run(["nm", "-D", lib], capture_output=True, text=True)
    return result.stdout


# ──────────────────────── Library installation tests ────────────────────────


class TestLiboqsInstallation:
    def test_shared_library_exists(self):
        assert _find_liboqs_so() is not None, (
            "liboqs shared library not found under /opt/liboqs/"
        )

    def test_headers_exist(self):
        header_found = (
            os.path.exists("/opt/liboqs/include/oqs/oqs.h")
            or os.path.exists("/opt/liboqs/include/oqs/kem.h")
        )
        assert header_found, "liboqs headers not found at /opt/liboqs/include/oqs/"

    def test_has_ml_kem_symbols(self):
        symbols = _get_dynamic_symbols()
        assert "OQS_KEM_ml_kem" in symbols, "ML-KEM symbols missing from liboqs.so"

    def test_has_ml_dsa_symbols(self):
        symbols = _get_dynamic_symbols()
        assert "OQS_SIG_ml_dsa" in symbols, "ML-DSA symbols missing from liboqs.so"


class TestMinimalBuild:
    """Verify excluded algorithm families are absent from the compiled library."""

    @pytest.mark.parametrize("family", EXCLUDED_FAMILIES)
    def test_excluded_family_absent(self, family):
        symbols = _get_dynamic_symbols().lower()
        pattern_kem = f"oqs_kem_{family}"
        pattern_sig = f"oqs_sig_{family}"
        assert pattern_kem not in symbols and pattern_sig not in symbols, (
            f"Algorithm family '{family}' should not be present in minimal build"
        )


# ──────────────────────── Output file existence & validity ──────────────────


OUTPUT_FILES = [
    "algorithm_audit.json",
    "kem_verification.json",
    "sig_verification.json",
    "cross_check.json",
    "py_audit.json",
]


class TestOutputFiles:
    @pytest.mark.parametrize("filename", OUTPUT_FILES)
    def test_file_exists(self, filename):
        path = f"/app/output/{filename}"
        assert os.path.exists(path), f"Missing output file: {path}"

    @pytest.mark.parametrize("filename", OUTPUT_FILES)
    def test_valid_json(self, filename):
        path = f"/app/output/{filename}"
        if not os.path.exists(path):
            pytest.skip(f"{path} does not exist")
        with open(path) as f:
            data = json.load(f)
        assert data is not None


# ──────────────────────── Algorithm parameter verification ──────────────────


class TestAlgorithmParameters:
    @pytest.fixture(autouse=True)
    def load_audit(self):
        path = "/app/output/algorithm_audit.json"
        if not os.path.exists(path):
            pytest.skip("algorithm_audit.json missing")
        with open(path) as f:
            self.audit = json.load(f)

    def test_exactly_3_kems(self):
        kems = [a for a in self.audit if a.get("type") == "KEM"]
        assert len(kems) == 3, f"Expected 3 KEM algorithms, got {len(kems)}: {[a.get('name') for a in kems]}"

    def test_exactly_3_sigs(self):
        sigs = [a for a in self.audit if a.get("type") == "SIG"]
        assert len(sigs) == 3, f"Expected 3 SIG algorithms, got {len(sigs)}: {[a.get('name') for a in sigs]}"

    @pytest.mark.parametrize("name,expected", list(EXPECTED_KEMS.items()))
    def test_kem_parameters(self, name, expected):
        algo = next((a for a in self.audit if a.get("name") == name), None)
        assert algo is not None, f"KEM algorithm {name} not found in audit"
        for key, val in expected.items():
            assert algo.get(key) == val, (
                f"{name}.{key}: expected {val}, got {algo.get(key)}"
            )

    @pytest.mark.parametrize("name,expected", list(EXPECTED_SIGS.items()))
    def test_sig_parameters(self, name, expected):
        algo = next((a for a in self.audit if a.get("name") == name), None)
        assert algo is not None, f"SIG algorithm {name} not found in audit"
        for key, val in expected.items():
            assert algo.get(key) == val, (
                f"{name}.{key}: expected {val}, got {algo.get(key)}"
            )


# ──────────────────────── Round-trip verification ───────────────────────────


class TestKemRoundTrips:
    @pytest.fixture(autouse=True)
    def load_results(self):
        path = "/app/output/kem_verification.json"
        if not os.path.exists(path):
            pytest.skip("kem_verification.json missing")
        with open(path) as f:
            self.results = json.load(f)

    def test_three_results(self):
        assert len(self.results) == 3, f"Expected 3 KEM results, got {len(self.results)}"

    @pytest.mark.parametrize("name", list(EXPECTED_KEMS.keys()))
    def test_kem_success(self, name):
        entry = next((r for r in self.results if r.get("name") == name), None)
        assert entry is not None, f"No KEM result for {name}"
        assert entry.get("success") is True, f"KEM round-trip failed for {name}"
        assert entry.get("shared_secrets_match") is True, (
            f"Shared secrets do not match for {name}"
        )


class TestSigRoundTrips:
    @pytest.fixture(autouse=True)
    def load_results(self):
        path = "/app/output/sig_verification.json"
        if not os.path.exists(path):
            pytest.skip("sig_verification.json missing")
        with open(path) as f:
            self.results = json.load(f)

    def test_three_results(self):
        assert len(self.results) == 3, f"Expected 3 SIG results, got {len(self.results)}"

    @pytest.mark.parametrize("name", list(EXPECTED_SIGS.keys()))
    def test_sig_success(self, name):
        entry = next((r for r in self.results if r.get("name") == name), None)
        assert entry is not None, f"No SIG result for {name}"
        assert entry.get("success") is True, f"SIG round-trip failed for {name}"
        assert entry.get("signature_valid") is True, (
            f"Signature verification failed for {name}"
        )


# ──────────────────────── Cross-check verification ──────────────────────────


class TestCrossCheck:
    @pytest.fixture(autouse=True)
    def load_crosscheck(self):
        path = "/app/output/cross_check.json"
        if not os.path.exists(path):
            pytest.skip("cross_check.json missing")
        with open(path) as f:
            self.check = json.load(f)

    def test_all_parameters_match(self):
        assert self.check.get("all_parameters_match") is True, (
            "C and Python algorithm parameters do not match"
        )

    def test_kem_count(self):
        assert self.check.get("kem_count") == 3, (
            f"Expected kem_count=3, got {self.check.get('kem_count')}"
        )

    def test_sig_count(self):
        assert self.check.get("sig_count") == 3, (
            f"Expected sig_count=3, got {self.check.get('sig_count')}"
        )


# ──────────────────────── Python audit file verification ────────────────────


class TestPythonAudit:
    def test_py_audit_exists(self):
        assert os.path.exists("/app/output/py_audit.json"), "py_audit.json missing"

    def test_py_audit_valid(self):
        if not os.path.exists("/app/output/py_audit.json"):
            pytest.skip("py_audit.json missing")
        with open("/app/output/py_audit.json") as f:
            data = json.load(f)
        kems = [a for a in data if a.get("type") == "KEM"]
        sigs = [a for a in data if a.get("type") == "SIG"]
        assert len(kems) == 3, f"Python audit: expected 3 KEMs, got {len(kems)}"
        assert len(sigs) == 3, f"Python audit: expected 3 SIGs, got {len(sigs)}"

    def test_py_audit_uses_standardized_names(self):
        """Verify Python audit uses FIPS standardized names, not legacy names."""
        if not os.path.exists("/app/output/py_audit.json"):
            pytest.skip("py_audit.json missing")
        with open("/app/output/py_audit.json") as f:
            data = json.load(f)
        names = {a.get("name") for a in data}
        # Must use ML-KEM/ML-DSA names, not Kyber/Dilithium
        for legacy in ["Kyber512", "Kyber768", "Kyber1024",
                       "Dilithium2", "Dilithium3", "Dilithium5"]:
            assert legacy not in names, (
                f"Legacy algorithm name '{legacy}' found — must use FIPS standardized names"
            )
        for std_name in ["ML-KEM-512", "ML-KEM-768", "ML-KEM-1024",
                         "ML-DSA-44", "ML-DSA-65", "ML-DSA-87"]:
            assert std_name in names, (
                f"FIPS standardized name '{std_name}' missing from Python audit"
            )

    @pytest.mark.parametrize("name,expected", list(EXPECTED_KEMS.items()))
    def test_py_kem_parameters(self, name, expected):
        if not os.path.exists("/app/output/py_audit.json"):
            pytest.skip("py_audit.json missing")
        with open("/app/output/py_audit.json") as f:
            data = json.load(f)
        algo = next((a for a in data if a.get("name") == name), None)
        assert algo is not None, f"KEM {name} not in Python audit"
        for key, val in expected.items():
            assert algo.get(key) == val, (
                f"Python {name}.{key}: expected {val}, got {algo.get(key)}"
            )

    @pytest.mark.parametrize("name,expected", list(EXPECTED_SIGS.items()))
    def test_py_sig_parameters(self, name, expected):
        if not os.path.exists("/app/output/py_audit.json"):
            pytest.skip("py_audit.json missing")
        with open("/app/output/py_audit.json") as f:
            data = json.load(f)
        algo = next((a for a in data if a.get("name") == name), None)
        assert algo is not None, f"SIG {name} not in Python audit"
        for key, val in expected.items():
            assert algo.get(key) == val, (
                f"Python {name}.{key}: expected {val}, got {algo.get(key)}"
            )
