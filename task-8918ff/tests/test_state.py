
"""
Wycheproof-based verification tests for /app/crypto_service.py.

These tests confirm that every planted vulnerability has been fixed and
that correct behaviour is preserved for valid inputs.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, "/app")
import crypto_service as cs


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def load_vectors(filename):
    with open(f"/app/vectors/{filename}") as fh:
        return json.load(fh)


# ===================================================================
# AES-GCM
# ===================================================================

class TestAesGcm:

    @pytest.fixture(autouse=True, scope="class")
    def _load(self):
        TestAesGcm._data = load_vectors("aes_gcm_test.json")

    # -- valid vectors must decrypt correctly -----------------------

    def test_valid_vectors(self):
        failures = []
        for grp in self._data["testGroups"]:
            iv_bytes = grp["ivSize"] // 8
            # Skip IV sizes unsupported by the cryptography backend
            if iv_bytes < 8 or iv_bytes > 128:
                continue
            for t in grp["tests"]:
                if t["result"] != "valid":
                    continue
                got = cs.aes_gcm_decrypt(
                    t["key"], t["iv"], t["ct"], t["tag"],
                    t.get("aad", ""),
                )
                if got is None:
                    failures.append(f'tcId={t["tcId"]}: valid vector rejected')
                elif got != t["msg"]:
                    failures.append(f'tcId={t["tcId"]}: wrong plaintext')
        assert not failures, "\n".join(failures[:15])

    # -- invalid vectors must be rejected ---------------------------

    def test_invalid_vectors(self):
        failures = []
        for grp in self._data["testGroups"]:
            iv_bytes = grp["ivSize"] // 8
            if iv_bytes < 8 or iv_bytes > 128:
                continue
            for t in grp["tests"]:
                if t["result"] != "invalid":
                    continue
                got = cs.aes_gcm_decrypt(
                    t["key"], t["iv"], t["ct"], t["tag"],
                    t.get("aad", ""),
                )
                if got is not None:
                    failures.append(
                        f'tcId={t["tcId"]}: invalid vector accepted '
                        f'(flags={t.get("flags", [])})'
                    )
        assert not failures, "\n".join(failures[:15])

    # -- zero-length IV must be rejected (CVE-2017-7822) ------------

    def test_zero_length_iv_rejected(self):
        """Sending an empty IV must not silently produce a decryption.

        The buggy service derives a deterministic fallback nonce from
        the key, which means an attacker who knows the key can craft
        ciphertext that decrypts via the empty-IV path.
        """
        import hashlib as _hl
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _GCM

        # Pick the first valid vector's key.
        for grp in self._data["testGroups"]:
            for t in grp["tests"]:
                if t["result"] == "valid":
                    key_hex = t["key"]
                    break
            break

        # Encrypt a known plaintext with the fallback nonce the buggy
        # code would derive: MD5(key)[:12].
        key = bytes.fromhex(key_hex)
        derived_iv = _hl.md5(key).digest()[:12]
        pt = b"\x42" * 16
        ct_tag = _GCM(key).encrypt(derived_iv, pt, b"")
        ct_hex = ct_tag[:-16].hex()
        tag_hex = ct_tag[-16:].hex()

        got = cs.aes_gcm_decrypt(key_hex, "", ct_hex, tag_hex, "")
        assert got is None, (
            "Zero-length IV must be rejected, but the service "
            "decrypted via the fallback nonce (ZeroLengthIv / AUTH_BYPASS)"
        )


# ===================================================================
# ECDSA  (secp256r1 / SHA-256)
# ===================================================================

class TestEcdsa:

    @pytest.fixture(autouse=True, scope="class")
    def _load(self):
        TestEcdsa._data = load_vectors("ecdsa_secp256r1_sha256_test.json")

    # -- valid signatures must verify -------------------------------

    def test_valid_signatures(self):
        failures = []
        for grp in self._data["testGroups"]:
            pk = grp["publicKeyDer"]
            for t in grp["tests"]:
                if t["result"] != "valid":
                    continue
                ok = cs.ecdsa_verify(pk, t["msg"], t["sig"])
                if not ok:
                    failures.append(f'tcId={t["tcId"]}: valid sig rejected')
        assert not failures, "\n".join(failures[:15])

    # -- invalid signatures must be rejected ------------------------

    def test_invalid_signatures(self):
        failures = []
        for grp in self._data["testGroups"]:
            pk = grp["publicKeyDer"]
            for t in grp["tests"]:
                if t["result"] != "invalid":
                    continue
                ok = cs.ecdsa_verify(pk, t["msg"], t["sig"])
                if ok:
                    failures.append(
                        f'tcId={t["tcId"]}: invalid sig accepted '
                        f'(flags={t.get("flags", [])})'
                    )
        assert not failures, "\n".join(failures[:15])

    # -- r=0 / s=0 must be rejected (CVE-2022-21449) ---------------

    def test_invalid_signature_flag_rejected(self):
        for grp in self._data["testGroups"]:
            pk = grp["publicKeyDer"]
            for t in grp["tests"]:
                if "InvalidSignature" not in t.get("flags", []):
                    continue
                ok = cs.ecdsa_verify(pk, t["msg"], t["sig"])
                assert not ok, (
                    f'tcId={t["tcId"]}: InvalidSignature accepted '
                    f'({t["comment"]})'
                )

    # -- BER-encoded sigs must be rejected --------------------------

    def test_ber_encoded_rejected(self):
        accepted = []
        for grp in self._data["testGroups"]:
            pk = grp["publicKeyDer"]
            for t in grp["tests"]:
                if "BerEncodedSignature" not in t.get("flags", []):
                    continue
                ok = cs.ecdsa_verify(pk, t["msg"], t["sig"])
                if ok:
                    accepted.append(f'tcId={t["tcId"]}: {t["comment"]}')
        assert not accepted, (
            f"Accepted {len(accepted)} BER sigs:\n" + "\n".join(accepted[:15])
        )

    # -- out-of-range r/s must be rejected --------------------------

    def test_range_check_rejected(self):
        accepted = []
        for grp in self._data["testGroups"]:
            pk = grp["publicKeyDer"]
            for t in grp["tests"]:
                if "RangeCheck" not in t.get("flags", []):
                    continue
                if t["result"] != "invalid":
                    continue
                ok = cs.ecdsa_verify(pk, t["msg"], t["sig"])
                if ok:
                    accepted.append(f'tcId={t["tcId"]}: {t["comment"]}')
        assert not accepted, (
            f"Accepted {len(accepted)} out-of-range sigs:\n"
            + "\n".join(accepted[:15])
        )


# ===================================================================
# X25519
# ===================================================================

class TestX25519:

    @pytest.fixture(autouse=True, scope="class")
    def _load(self):
        TestX25519._data = load_vectors("x25519_test.json")

    # -- valid exchanges must produce correct shared secrets --------

    def test_valid_exchanges(self):
        failures = []
        for grp in self._data["testGroups"]:
            for t in grp["tests"]:
                if t["result"] != "valid":
                    continue
                got = cs.x25519_exchange(t["private"], t["public"])
                if got != t["shared"]:
                    failures.append(
                        f'tcId={t["tcId"]}: expected {t["shared"]}, got {got}'
                    )
        assert not failures, "\n".join(failures[:15])

    # -- all-zero shared secret must be rejected (RFC 7748 s6.1) ----

    def test_zero_shared_secret_rejected(self):
        accepted = []
        for grp in self._data["testGroups"]:
            for t in grp["tests"]:
                if "ZeroSharedSecret" not in t.get("flags", []):
                    continue
                got = cs.x25519_exchange(t["private"], t["public"])
                if got is not None and got == "0" * 64:
                    accepted.append(
                        f'tcId={t["tcId"]}: all-zero shared secret returned'
                    )
        assert not accepted, "\n".join(accepted[:10])


# ===================================================================
# HMAC-SHA256  (correct implementation – regression guard)
# ===================================================================

class TestHmacSha256:

    @pytest.fixture(autouse=True, scope="class")
    def _load(self):
        TestHmacSha256._data = load_vectors("hmac_sha256_test.json")

    def test_valid_tags(self):
        failures = []
        for grp in self._data["testGroups"]:
            for t in grp["tests"]:
                if t["result"] != "valid":
                    continue
                ok = cs.hmac_sha256_verify(t["key"], t["msg"], t["tag"])
                if not ok:
                    failures.append(f'tcId={t["tcId"]}: valid tag rejected')
        assert not failures, "\n".join(failures[:15])

    def test_invalid_tags(self):
        failures = []
        for grp in self._data["testGroups"]:
            for t in grp["tests"]:
                if t["result"] != "invalid":
                    continue
                ok = cs.hmac_sha256_verify(t["key"], t["msg"], t["tag"])
                if ok:
                    failures.append(f'tcId={t["tcId"]}: invalid tag accepted')
        assert not failures, "\n".join(failures[:15])


# ===================================================================
# HKDF-SHA256  (correct implementation – regression guard)
# ===================================================================

class TestHkdfSha256:

    @pytest.fixture(autouse=True, scope="class")
    def _load(self):
        TestHkdfSha256._data = load_vectors("hkdf_sha256_test.json")

    def test_valid_derivations(self):
        failures = []
        for grp in self._data["testGroups"]:
            for t in grp["tests"]:
                if t["result"] != "valid":
                    continue
                got = cs.hkdf_sha256(
                    t["ikm"], t["salt"], t["info"], t["size"],
                )
                if got != t["okm"]:
                    failures.append(f'tcId={t["tcId"]}: wrong derived key')
        assert not failures, "\n".join(failures[:15])

    def test_invalid_derivations_rejected(self):
        failures = []
        for grp in self._data["testGroups"]:
            for t in grp["tests"]:
                if t["result"] != "invalid":
                    continue
                got = cs.hkdf_sha256(
                    t["ikm"], t["salt"], t["info"], t["size"],
                )
                if got is not None:
                    failures.append(
                        f'tcId={t["tcId"]}: invalid derivation accepted'
                    )
        assert not failures, "\n".join(failures[:15])


# ===================================================================
# Audit report validation
# ===================================================================

class TestAuditReport:

    def test_report_exists(self):
        assert os.path.isfile("/app/audit_report.json"), \
            "/app/audit_report.json not found"

    def test_report_has_five_vulnerabilities(self):
        with open("/app/audit_report.json") as fh:
            report = json.load(fh)
        vulns = report.get("vulnerabilities", [])
        assert len(vulns) >= 5, (
            f"Expected at least 5 vulnerabilities, got {len(vulns)}"
        )

    def test_report_bug_types(self):
        with open("/app/audit_report.json") as fh:
            report = json.load(fh)
        found = {v["bug_type"] for v in report["vulnerabilities"]}
        required = {
            "ZeroLengthIv",
            "InvalidSignature",
            "BerEncodedSignature",
            "RangeCheck",
            "ZeroSharedSecret",
        }
        missing = required - found
        assert not missing, f"Missing bug types: {missing}"

    def test_report_affected_functions(self):
        with open("/app/audit_report.json") as fh:
            report = json.load(fh)
        funcs = {v["function"] for v in report["vulnerabilities"]}
        required = {"aes_gcm_decrypt", "ecdsa_verify", "x25519_exchange"}
        missing = required - funcs
        assert not missing, f"Missing affected functions: {missing}"
