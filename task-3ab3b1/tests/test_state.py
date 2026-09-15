"""

Verification tests for crypto_ops.py using Wycheproof test vectors.
Validates that all security bugs have been fixed and findings documented.
"""

import json
import os
import sys
import pytest

sys.path.insert(0, '/app')
from crypto_ops import (
    aes_gcm_encrypt,
    aes_gcm_decrypt,
    ecdsa_verify,
    hmac_compute,
    hmac_verify,
    hkdf_derive,
)


def load_vectors(filename):
    with open(f"/app/vectors/{filename}") as f:
        return json.load(f)


# ---- AES-GCM Tests ----

class TestAesGcm:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_vectors("aes_gcm_test.json")

    def test_valid_decrypt(self):
        """All valid AES-GCM test vectors must decrypt to the expected plaintext.
        Skips vectors with IV sizes outside the cryptography library's supported
        range of 8-128 bytes (the GCM spec allows arbitrary IV lengths, but the
        library enforces this narrower range)."""
        failures = []
        count = 0
        for group in self.data["testGroups"]:
            iv_size_bytes = group["ivSize"] // 8
            # The cryptography library only supports IVs between 8 and 128 bytes;
            # skip test groups outside that range (SmallIv / LongIv vectors).
            if iv_size_bytes < 8 or iv_size_bytes > 128:
                continue
            for tc in group["tests"]:
                if tc["result"] != "valid":
                    continue
                try:
                    key = bytes.fromhex(tc["key"])
                    iv = bytes.fromhex(tc["iv"])
                    ct = bytes.fromhex(tc["ct"])
                    tag = bytes.fromhex(tc["tag"])
                    aad = bytes.fromhex(tc["aad"])
                    expected = bytes.fromhex(tc["msg"])
                    result = aes_gcm_decrypt(key, iv, ct, tag, aad)
                    if result != expected:
                        failures.append(f"tcId={tc['tcId']}: plaintext mismatch")
                except Exception as e:
                    failures.append(f"tcId={tc['tcId']}: {type(e).__name__}: {e}")
                count += 1
        assert count > 0, "No valid AES-GCM vectors found"
        assert not failures, "Failed valid vectors:\n" + "\n".join(failures[:15])

    def test_zero_length_iv_must_raise(self):
        """Zero-length IV must raise an exception, not silently return."""
        zero_iv_count = 0
        for group in self.data["testGroups"]:
            for tc in group["tests"]:
                if "ZeroLengthIv" not in tc.get("flags", []):
                    continue
                zero_iv_count += 1
                key = bytes.fromhex(tc["key"])
                iv = bytes.fromhex(tc["iv"])
                ct = bytes.fromhex(tc["ct"])
                tag = bytes.fromhex(tc["tag"])
                aad = bytes.fromhex(tc["aad"])
                with pytest.raises(Exception):
                    aes_gcm_decrypt(key, iv, ct, tag, aad)
        assert zero_iv_count > 0, "No ZeroLengthIv test vectors found in data"

    def test_invalid_vectors_rejected(self):
        """All invalid AES-GCM vectors (modified tags, etc.) must fail."""
        failures = []
        checked = 0
        for group in self.data["testGroups"]:
            for tc in group["tests"]:
                if tc["result"] != "invalid":
                    continue
                if "ZeroLengthIv" in tc.get("flags", []):
                    continue  # tested separately above
                key = bytes.fromhex(tc["key"])
                iv = bytes.fromhex(tc["iv"])
                ct = bytes.fromhex(tc["ct"])
                tag = bytes.fromhex(tc["tag"])
                aad = bytes.fromhex(tc["aad"])
                try:
                    aes_gcm_decrypt(key, iv, ct, tag, aad)
                    failures.append(
                        f"tcId={tc['tcId']}: accepted invalid vector "
                        f"(flags={tc.get('flags', [])})"
                    )
                except Exception:
                    pass
                checked += 1
        assert checked > 0, "No invalid AES-GCM vectors checked"
        assert not failures, "Accepted invalid vectors:\n" + "\n".join(failures[:15])


# ---- ECDSA Tests ----

class TestEcdsa:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_vectors("ecdsa_secp256r1_sha256_test.json")

    def test_valid_signatures_accepted(self):
        """All valid ECDSA signatures must verify successfully."""
        failures = []
        count = 0
        for group in self.data["testGroups"]:
            key_der = bytes.fromhex(group["publicKeyDer"])
            sha = group["sha"]
            for tc in group["tests"]:
                if tc["result"] != "valid":
                    continue
                msg = bytes.fromhex(tc["msg"])
                sig = bytes.fromhex(tc["sig"])
                if not ecdsa_verify(key_der, msg, sig, sha):
                    failures.append(f"tcId={tc['tcId']}: valid sig rejected")
                count += 1
        assert count > 0, "No valid ECDSA vectors found"
        assert not failures, "Rejected valid sigs:\n" + "\n".join(failures[:15])

    def test_invalid_signatures_rejected(self):
        """All invalid ECDSA signatures must be rejected."""
        failures = []
        checked = 0
        for group in self.data["testGroups"]:
            key_der = bytes.fromhex(group["publicKeyDer"])
            sha = group["sha"]
            for tc in group["tests"]:
                if tc["result"] != "invalid":
                    continue
                msg = bytes.fromhex(tc["msg"])
                sig = bytes.fromhex(tc["sig"])
                if ecdsa_verify(key_der, msg, sig, sha):
                    failures.append(
                        f"tcId={tc['tcId']} ({tc.get('comment', '')}): "
                        f"invalid sig accepted, flags={tc.get('flags', [])}"
                    )
                checked += 1
        assert checked > 0, "No invalid ECDSA vectors checked"
        assert not failures, "Accepted invalid sigs:\n" + "\n".join(failures[:20])

    def test_ber_encoding_must_be_rejected(self):
        """BER-encoded ECDSA signatures must not be silently accepted."""
        # Use the first valid test vector to construct a BER-encoded variant
        group = self.data["testGroups"][0]
        key_der = bytes.fromhex(group["publicKeyDer"])
        sha = group["sha"]

        tc = None
        for t in group["tests"]:
            if t["result"] == "valid":
                tc = t
                break
        assert tc is not None, "No valid ECDSA test vector found"

        msg = bytes.fromhex(tc["msg"])
        valid_sig = bytes.fromhex(tc["sig"])

        # Confirm the DER-encoded original is accepted
        assert ecdsa_verify(key_der, msg, valid_sig, sha), \
            "Valid DER signature should be accepted"

        # Create BER variant: replace short-form SEQUENCE length with long-form
        # DER:  30 <len_byte> <contents>
        # BER:  30 81 <len_byte> <contents>  (unnecessarily long length encoding)
        assert valid_sig[0] == 0x30, "Expected SEQUENCE tag at start of signature"
        seq_len_byte = valid_sig[1]
        assert seq_len_byte < 0x80, "Test expects short-form length in original"
        ber_sig = bytes([0x30, 0x81, seq_len_byte]) + valid_sig[2:]

        # The BER-encoded version must be rejected (strict DER required)
        assert not ecdsa_verify(key_der, msg, ber_sig, sha), \
            "BER-encoded signature was accepted; strict DER parsing required"


# ---- HMAC Tests ----

class TestHmac:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_vectors("hmac_sha256_test.json")

    def test_valid_hmac(self):
        """Valid HMAC vectors must verify correctly."""
        failures = []
        count = 0
        for group in self.data["testGroups"]:
            tag_size = group["tagSize"]
            for tc in group["tests"]:
                if tc["result"] != "valid":
                    continue
                key = bytes.fromhex(tc["key"])
                msg = bytes.fromhex(tc["msg"])
                expected_tag = bytes.fromhex(tc["tag"])
                if not hmac_verify(key, msg, expected_tag, "SHA-256",
                                   tag_size_bits=tag_size):
                    failures.append(f"tcId={tc['tcId']}: HMAC verification failed")
                count += 1
        assert count > 0, "No valid HMAC vectors found"
        assert not failures, "HMAC failures:\n" + "\n".join(failures[:10])

    def test_invalid_hmac_rejected(self):
        """Modified HMAC tags must be rejected."""
        failures = []
        checked = 0
        for group in self.data["testGroups"]:
            tag_size = group["tagSize"]
            for tc in group["tests"]:
                if tc["result"] != "invalid":
                    continue
                key = bytes.fromhex(tc["key"])
                msg = bytes.fromhex(tc["msg"])
                tag = bytes.fromhex(tc["tag"])
                if hmac_verify(key, msg, tag, "SHA-256", tag_size_bits=tag_size):
                    failures.append(f"tcId={tc['tcId']}: invalid tag accepted")
                checked += 1
        assert checked > 0, "No invalid HMAC vectors checked"
        assert not failures, "Accepted invalid tags:\n" + "\n".join(failures[:10])


# ---- HKDF Tests ----

class TestHkdf:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_vectors("hkdf_sha256_test.json")

    def test_valid_derivation(self):
        """Valid HKDF vectors must produce the expected output key material."""
        failures = []
        count = 0
        for group in self.data["testGroups"]:
            for tc in group["tests"]:
                if tc["result"] != "valid":
                    continue
                ikm = bytes.fromhex(tc["ikm"])
                salt = bytes.fromhex(tc["salt"]) if tc["salt"] else None
                info = bytes.fromhex(tc["info"])
                size = tc["size"]
                expected = bytes.fromhex(tc["okm"])
                try:
                    result = hkdf_derive(ikm, salt, info, size, "SHA-256")
                    if result != expected:
                        failures.append(f"tcId={tc['tcId']}: output mismatch")
                except Exception as e:
                    failures.append(f"tcId={tc['tcId']}: {type(e).__name__}: {e}")
                count += 1
        assert count > 0, "No valid HKDF vectors found"
        assert not failures, "HKDF failures:\n" + "\n".join(failures[:10])

    def test_size_too_large_must_raise(self):
        """Output sizes exceeding 255 * hash_length must raise, not silently clamp."""
        found = False
        for group in self.data["testGroups"]:
            for tc in group["tests"]:
                if "SizeTooLarge" not in tc.get("flags", []):
                    continue
                found = True
                ikm = bytes.fromhex(tc["ikm"])
                salt = bytes.fromhex(tc["salt"]) if tc["salt"] else None
                info = bytes.fromhex(tc["info"])
                size = tc["size"]
                with pytest.raises(Exception):
                    hkdf_derive(ikm, salt, info, size, "SHA-256")
        assert found, "No SizeTooLarge test vectors found in data"


# ---- Findings Report ----

class TestFindings:
    def test_findings_report_exists_and_valid(self):
        """findings.json must exist and correctly document all bugs."""
        path = "/app/findings.json"
        assert os.path.exists(path), "findings.json not found at /app/findings.json"

        with open(path) as f:
            data = json.load(f)

        assert "bugs" in data, "findings.json must contain a 'bugs' key"
        assert isinstance(data["bugs"], list), "'bugs' must be a list"
        assert len(data["bugs"]) >= 3, \
            f"Expected at least 3 bugs documented, found {len(data['bugs'])}"

        documented_functions = {b.get("function") for b in data["bugs"]}
        assert "aes_gcm_decrypt" in documented_functions, \
            "Must document the aes_gcm_decrypt bug"
        assert "ecdsa_verify" in documented_functions, \
            "Must document the ecdsa_verify bug"
        assert "hkdf_derive" in documented_functions, \
            "Must document the hkdf_derive bug"

        for bug in data["bugs"]:
            assert "function" in bug, "Each bug entry must have 'function'"
            assert "bug_type" in bug, "Each bug entry must have 'bug_type'"
            assert "description" in bug, "Each bug entry must have 'description'"
            assert len(bug["description"]) > 20, \
                f"Bug description too short for {bug['function']}"
