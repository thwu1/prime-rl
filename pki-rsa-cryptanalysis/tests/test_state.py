"""
Verify the PKI security audit solution.

Tests:
1. Vulnerability report: correct classification of all 8 certificates
2. Decrypted payload: SHA-256 hash match and valid manifest structure
3. Remediated certificates: key size, signature, CN, no shared primes
"""

import hashlib
import json
import math
import os
import pytest

# Ground truth: which certificates have which vulnerability class
GCD_VULNERABLE = {
    "api-gateway.pem", "database-primary.pem",
    "mail-relay.pem", "monitoring.pem",
}
FERMAT_VULNERABLE = {"vpn-gateway.pem"}
ALL_VULNERABLE = GCD_VULNERABLE | FERMAT_VULNERABLE
CLEAN_CERTS = {
    "webserver-prod.pem", "backup-server.pem", "log-aggregator.pem",
}
ALL_CERTS = ALL_VULNERABLE | CLEAN_CERTS

# Flexible keyword matching for vulnerability type strings
GCD_KEYWORDS = ["shared", "gcd", "common_factor", "prime_factor", "factor"]
FERMAT_KEYWORDS = ["close", "fermat", "adjacent", "near", "proximity"]


def _matches_any(value, keywords):
    """Check if value (case-insensitive, normalized) contains any keyword."""
    v = value.lower().replace("-", "_").replace(" ", "_")
    return any(kw in v for kw in keywords)


def _load_report():
    with open("/app/vulnerability_report.json") as f:
        report = json.load(f)
    # Accept both {"certificates": {...}} and flat dict
    return report.get("certificates", report)


# ──────────────────────────────────────────────────────────────────────
# Vulnerability Report Tests
# ──────────────────────────────────────────────────────────────────────

class TestVulnerabilityReport:
    """Verify the vulnerability assessment classifies all certificates."""

    def test_report_file_exists(self):
        assert os.path.isfile("/app/vulnerability_report.json"), \
            "/app/vulnerability_report.json does not exist"

    def test_all_certificates_present(self):
        certs = _load_report()
        for name in ALL_CERTS:
            assert name in certs, f"Missing classification for {name}"

    def test_gcd_vulnerable_identified(self):
        certs = _load_report()
        for name in GCD_VULNERABLE:
            entry = certs[name]
            vtype = entry.get("vulnerability_type", "")
            assert _matches_any(vtype, GCD_KEYWORDS), (
                f"{name}: expected shared-prime vulnerability, got '{vtype}'"
            )

    def test_fermat_vulnerable_identified(self):
        certs = _load_report()
        for name in FERMAT_VULNERABLE:
            entry = certs[name]
            vtype = entry.get("vulnerability_type", "")
            assert _matches_any(vtype, FERMAT_KEYWORDS), (
                f"{name}: expected close-primes vulnerability, got '{vtype}'"
            )

    def test_clean_certs_identified(self):
        certs = _load_report()
        for name in CLEAN_CERTS:
            entry = certs[name]
            vtype = entry.get("vulnerability_type", "").lower()
            assert vtype in ("none", "secure", "safe", "clean", "no_vulnerability"), (
                f"{name}: expected 'none' vulnerability, got '{vtype}'"
            )

    def test_vulnerable_severity_is_critical(self):
        certs = _load_report()
        for name in ALL_VULNERABLE:
            entry = certs[name]
            sev = entry.get("severity", "").lower()
            assert sev in ("critical", "high"), (
                f"{name}: expected critical/high severity, got '{sev}'"
            )

    def test_clean_severity_is_none(self):
        certs = _load_report()
        for name in CLEAN_CERTS:
            entry = certs[name]
            sev = entry.get("severity", "").lower()
            assert sev in ("none", "low", "n/a", "informational"), (
                f"{name}: expected none/low severity, got '{sev}'"
            )


# ──────────────────────────────────────────────────────────────────────
# Decrypted Payload Tests
# ──────────────────────────────────────────────────────────────────────

class TestDecryptedPayload:
    """Verify the recovered plaintext matches the original exfiltrated data."""

    def test_plaintext_file_exists(self):
        assert os.path.isfile("/app/recovered_plaintext.txt"), \
            "/app/recovered_plaintext.txt does not exist"

    def test_plaintext_hash_matches(self):
        with open("/app/recovered_plaintext.txt", "rb") as f:
            content = f.read()
        actual = hashlib.sha256(content).hexdigest()
        with open("/app/pki_audit/.verification") as f:
            expected = f.read().strip()
        assert actual == expected, (
            f"SHA-256 mismatch: got {actual}, expected {expected}"
        )

    def test_plaintext_valid_json(self):
        with open("/app/recovered_plaintext.txt") as f:
            data = json.load(f)
        assert isinstance(data, dict), "Top-level value must be a JSON object"

    def test_manifest_structure(self):
        with open("/app/recovered_plaintext.txt") as f:
            data = json.load(f)
        assert "exfil_manifest" in data, "Missing 'exfil_manifest' key"
        manifest = data["exfil_manifest"]
        for field in ("campaign_id", "operator", "c2_domains", "encryption_key_id"):
            assert field in manifest, f"Missing field '{field}' in exfil_manifest"
        assert isinstance(manifest["c2_domains"], list), "'c2_domains' must be a list"
        assert len(manifest["c2_domains"]) >= 1, "'c2_domains' must not be empty"


# ──────────────────────────────────────────────────────────────────────
# Remediated Certificate Tests
# ──────────────────────────────────────────────────────────────────────

class TestRemediatedCertificates:
    """Verify replacement certificates meet security requirements."""

    def test_remediated_dir_exists(self):
        assert os.path.isdir("/app/remediated_certs"), \
            "/app/remediated_certs/ directory does not exist"

    def test_all_vulnerable_certs_replaced(self):
        for name in ALL_VULNERABLE:
            path = f"/app/remediated_certs/{name}"
            assert os.path.isfile(path), f"Missing remediated cert: {name}"

    def test_minimum_key_size(self):
        from cryptography import x509 as cx509
        for name in ALL_VULNERABLE:
            with open(f"/app/remediated_certs/{name}", "rb") as f:
                cert = cx509.load_pem_x509_certificate(f.read())
            key_size = cert.public_key().key_size
            assert key_size >= 2048, (
                f"{name}: key size {key_size} < 2048 minimum"
            )

    def test_signature_algorithm(self):
        from cryptography import x509 as cx509
        from cryptography.hazmat.primitives import hashes
        for name in ALL_VULNERABLE:
            with open(f"/app/remediated_certs/{name}", "rb") as f:
                cert = cx509.load_pem_x509_certificate(f.read())
            sig_alg = cert.signature_hash_algorithm
            assert isinstance(sig_alg, (hashes.SHA256, hashes.SHA384, hashes.SHA512)), (
                f"{name}: weak signature algorithm {type(sig_alg).__name__}"
            )

    def test_common_name_preserved(self):
        from cryptography import x509 as cx509
        from cryptography.x509.oid import NameOID
        cert_dir = "/app/pki_audit/certificates"
        for name in ALL_VULNERABLE:
            with open(f"{cert_dir}/{name}", "rb") as f:
                orig = cx509.load_pem_x509_certificate(f.read())
            orig_cn = orig.subject.get_attributes_for_oid(
                NameOID.COMMON_NAME
            )[0].value

            with open(f"/app/remediated_certs/{name}", "rb") as f:
                new = cx509.load_pem_x509_certificate(f.read())
            new_cn = new.subject.get_attributes_for_oid(
                NameOID.COMMON_NAME
            )[0].value

            assert new_cn == orig_cn, (
                f"{name}: CN mismatch — got '{new_cn}', expected '{orig_cn}'"
            )

    def test_no_shared_primes_among_remediated(self):
        from cryptography import x509 as cx509
        moduli = []
        for name in ALL_VULNERABLE:
            with open(f"/app/remediated_certs/{name}", "rb") as f:
                cert = cx509.load_pem_x509_certificate(f.read())
            moduli.append((name, cert.public_key().public_numbers().n))
        for i in range(len(moduli)):
            for j in range(i + 1, len(moduli)):
                g = math.gcd(moduli[i][1], moduli[j][1])
                assert g == 1, (
                    f"Shared prime factor between remediated "
                    f"{moduli[i][0]} and {moduli[j][0]}"
                )

    def test_keys_differ_from_originals(self):
        from cryptography import x509 as cx509
        cert_dir = "/app/pki_audit/certificates"
        for name in ALL_VULNERABLE:
            with open(f"{cert_dir}/{name}", "rb") as f:
                orig = cx509.load_pem_x509_certificate(f.read())
            orig_n = orig.public_key().public_numbers().n

            with open(f"/app/remediated_certs/{name}", "rb") as f:
                new = cx509.load_pem_x509_certificate(f.read())
            new_n = new.public_key().public_numbers().n

            assert new_n != orig_n, (
                f"{name}: remediated cert reuses the original key"
            )
