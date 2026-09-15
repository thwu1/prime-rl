
"""
Tests for ECC signing service security audit.
Verifies audit report correctness, private key recovery,
OpenSSL PEM key validity, and OpenSSL signature verification.
"""

import json
import os
import subprocess
import tempfile

import pytest


EXPECTED_PRIVATE_KEY = 0xA3AA6B3BA0FE8DF8D4790F46B42CB2DE2F45A0632C153F8551D704FD079FB27F
CHALLENGE_MESSAGE = b"ANSSI security audit completed for system CYBELE-7"


def load_report():
    with open("/app/audit_report.json") as f:
        return json.load(f)


# -- Audit Report Tests ------------------------------------------------------


class TestAuditReport:
    """Verify the vulnerability assessment is correct."""

    def test_report_file_exists(self):
        assert os.path.exists("/app/audit_report.json"), \
            "audit_report.json not found"

    def test_exploited_pair_identified(self):
        """Must identify signatures 0 and 3 as the exploited pair."""
        report = load_report()
        assert "exploited_pair" in report, "Missing exploited_pair field"
        pair = sorted(report["exploited_pair"])
        assert pair == [0, 3], \
            f"Expected exploited pair [0, 3], got {pair}"

    def test_sig0_classified_vulnerable(self):
        report = load_report()
        findings = {f["sig_index"]: f for f in report["findings"]}
        assert 0 in findings, "Missing finding for sig_index 0"
        assert findings[0]["status"] == "vulnerable", \
            f"Sig 0 should be vulnerable, got {findings[0]['status']}"
        assert findings[0]["vulnerability_type"] == "nonce_reuse", \
            f"Sig 0 vulnerability should be nonce_reuse, got {findings[0]['vulnerability_type']}"

    def test_sig3_classified_vulnerable(self):
        report = load_report()
        findings = {f["sig_index"]: f for f in report["findings"]}
        assert 3 in findings, "Missing finding for sig_index 3"
        assert findings[3]["status"] == "vulnerable", \
            f"Sig 3 should be vulnerable, got {findings[3]['status']}"
        assert findings[3]["vulnerability_type"] == "nonce_reuse", \
            f"Sig 3 vulnerability should be nonce_reuse, got {findings[3]['vulnerability_type']}"

    def test_safe_signatures_classified(self):
        """Signatures 1, 2, 4, 5 must be classified as safe."""
        report = load_report()
        findings = {f["sig_index"]: f for f in report["findings"]}
        for idx in [1, 2, 4, 5]:
            assert idx in findings, f"Missing finding for sig_index {idx}"
            assert findings[idx]["status"] == "safe", \
                f"Sig {idx} should be safe, got {findings[idx]['status']}"

    def test_all_six_signatures_covered(self):
        report = load_report()
        indices = sorted(f["sig_index"] for f in report["findings"])
        assert indices == [0, 1, 2, 3, 4, 5], \
            f"Expected findings for indices 0-5, got {indices}"

    def test_ecrdsa_sig2_convention_is_iso(self):
        """Signature 2 uses ISO 14888-3 (big-endian hash)."""
        report = load_report()
        convs = {c["sig_index"]: c["convention"] for c in report["ecrdsa_conventions"]}
        assert 2 in convs, "Missing ECRDSA convention for sig_index 2"
        assert convs[2] == "iso", \
            f"Sig 2 convention should be 'iso', got '{convs[2]}'"

    def test_ecrdsa_sig4_convention_is_rfc(self):
        """Signature 4 uses RFC 7091 (byte-reversed hash)."""
        report = load_report()
        convs = {c["sig_index"]: c["convention"] for c in report["ecrdsa_conventions"]}
        assert 4 in convs, "Missing ECRDSA convention for sig_index 4"
        assert convs[4] == "rfc", \
            f"Sig 4 convention should be 'rfc', got '{convs[4]}'"


# -- Private Key Recovery Tests -----------------------------------------------


class TestKeyRecovery:
    """Verify the recovered private key is correct and in valid PEM format."""

    def test_pem_key_file_exists(self):
        assert os.path.exists("/app/recovered_key.pem"), \
            "recovered_key.pem not found"

    def test_private_key_correct_value(self):
        """Extract private key integer from PEM and compare to expected."""
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        with open("/app/recovered_key.pem", "rb") as f:
            pem_data = f.read()
        key = load_pem_private_key(pem_data, password=None)
        pk_int = key.private_numbers().private_value
        assert pk_int == EXPECTED_PRIVATE_KEY, \
            f"Private key mismatch: got {hex(pk_int)}, expected {hex(EXPECTED_PRIVATE_KEY)}"

    def test_openssl_recognizes_key(self):
        """OpenSSL must accept the PEM key without errors."""
        result = subprocess.run(
            ["openssl", "ec", "-in", "/app/recovered_key.pem", "-noout"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, \
            f"OpenSSL rejected key: {result.stderr.strip()}"

    def test_key_is_on_prime256v1(self):
        """Verify the key is on the P-256 curve."""
        result = subprocess.run(
            ["openssl", "ec", "-in", "/app/recovered_key.pem", "-text", "-noout"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        output = result.stdout + result.stderr
        assert "prime256v1" in output or "P-256" in output or "secp256r1" in output, \
            f"Key is not on prime256v1 curve. Output: {output[:300]}"


# -- OpenSSL Signature Tests --------------------------------------------------


class TestOpenSSLSignature:
    """Verify the DER signature was produced correctly and validates with OpenSSL."""

    def test_public_key_file_exists(self):
        assert os.path.exists("/app/public_key.pem"), \
            "public_key.pem not found"

    def test_signature_file_exists(self):
        assert os.path.exists("/app/challenge_sig.der"), \
            "challenge_sig.der not found"

    def test_signature_is_valid_der(self):
        """The signature file must be valid ASN.1 DER."""
        result = subprocess.run(
            ["openssl", "asn1parse", "-in", "/app/challenge_sig.der",
             "-inform", "DER"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, \
            f"Signature is not valid DER: {result.stderr.strip()}"
        assert "INTEGER" in result.stdout, \
            "DER signature should contain INTEGER fields (r, s)"

    def test_openssl_signature_verifies(self):
        """OpenSSL dgst -verify must accept the signature on the challenge message."""
        msg_file = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
        try:
            msg_file.write(CHALLENGE_MESSAGE)
            msg_file.close()
            result = subprocess.run(
                ["openssl", "dgst", "-sha256",
                 "-verify", "/app/public_key.pem",
                 "-signature", "/app/challenge_sig.der",
                 msg_file.name],
                capture_output=True, text=True
            )
            combined = result.stdout + result.stderr
            assert result.returncode == 0, \
                f"OpenSSL signature verification failed: {combined.strip()}"
        finally:
            os.unlink(msg_file.name)

    def test_public_key_matches_private_key(self):
        """Public key PEM must correspond to the private key PEM."""
        result = subprocess.run(
            ["openssl", "pkey", "-in", "/app/recovered_key.pem",
             "-pubout", "-outform", "PEM"],
            capture_output=True
        )
        assert result.returncode == 0
        derived_pubkey = result.stdout.strip()

        with open("/app/public_key.pem", "rb") as f:
            provided_pubkey = f.read().strip()

        assert derived_pubkey == provided_pubkey, \
            "public_key.pem does not match the public key derived from recovered_key.pem"
