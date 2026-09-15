#!/usr/bin/env python3
"""Tests for the PKI audit and reconstruction task."""

import datetime
import json
import os
import subprocess

import pytest
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID

PKI_FIXED_DIR = "/app/pki-fixed"
AUDIT_FILE = "/app/audit.json"

# Signature algorithm OIDs that are considered insecure
BANNED_SIG_OIDS = {
    "1.2.840.113549.1.1.5",   # sha1WithRSAEncryption
    "1.2.840.113549.1.1.4",   # md5WithRSAEncryption
    "1.2.840.113549.1.1.2",   # md2WithRSAEncryption
    "1.3.14.3.2.29",          # sha1WithRSA (alt OID)
}


def load_cert(path):
    """Load a PEM certificate from disk."""
    with open(path, "rb") as f:
        return x509.load_pem_x509_certificate(f.read())


def _get_validity(cert):
    """Get not_valid_before and not_valid_after as UTC-aware datetimes."""
    try:
        return cert.not_valid_before_utc, cert.not_valid_after_utc
    except AttributeError:
        nvb = cert.not_valid_before.replace(tzinfo=datetime.timezone.utc)
        nva = cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
        return nvb, nva


def _openssl_text(cert_path):
    """Get openssl x509 -text output for a certificate file."""
    result = subprocess.run(
        ["openssl", "x509", "-in", cert_path, "-noout", "-text"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"openssl failed on {cert_path}: {result.stderr}"
    return result.stdout


# ---------------------------------------------------------------------------
# Audit report tests
# ---------------------------------------------------------------------------

class TestAuditReport:
    """Verify the audit report identifies the key PKI violations."""

    def _load_audit_text(self):
        with open(AUDIT_FILE) as f:
            return json.dumps(json.load(f)).lower()

    def test_audit_file_exists(self):
        assert os.path.exists(AUDIT_FILE), "audit.json not found at /app/audit.json"

    def test_audit_valid_json_with_findings(self):
        with open(AUDIT_FILE) as f:
            data = json.load(f)
        assert "findings" in data, "audit.json must contain a 'findings' key"
        assert isinstance(data["findings"], list), "'findings' must be a list"
        assert len(data["findings"]) >= 5, (
            f"Expected at least 5 findings, got {len(data['findings'])}"
        )

    def test_audit_identifies_sha1_root(self):
        text = self._load_audit_text()
        assert any(kw in text for kw in ["sha-1", "sha1", "sha 1"]), (
            "Audit should identify SHA-1 signature algorithm on root CA"
        )

    def test_audit_identifies_weak_key(self):
        text = self._load_audit_text()
        assert "1024" in text, (
            "Audit should identify 1024-bit weak key on intermediate CA"
        )

    def test_audit_identifies_pathlen_violation(self):
        text = self._load_audit_text()
        assert any(kw in text for kw in [
            "pathlen", "path length", "path_length",
            "path constraint", "pathlength", "path len",
        ]), "Audit should identify path length constraint violation"

    def test_audit_identifies_san_issue(self):
        text = self._load_audit_text()
        assert any(kw in text for kw in [
            "subject alternative", "san ",
            "subjectaltname", "subject_alternative",
            "subjectalternativename", "\"san\"",
            "san\\", "'san'",
        ]), "Audit should identify missing SAN on server certificate"

    def test_audit_identifies_eku_issue(self):
        text = self._load_audit_text()
        assert any(kw in text for kw in [
            "extended key usage", "extendedkeyusage", "eku",
            "serverauth", "server_auth", "server auth",
            "clientauth", "client_auth", "client auth",
            "key usage",
        ]), "Audit should identify EKU issue on server certificate"

    def test_audit_identifies_expiry_issues(self):
        text = self._load_audit_text()
        assert any(kw in text for kw in [
            "expired", "expiration", "validity",
            "lifetime", "20 year", "too long",
            "excessive", "7305", "not valid",
        ]), "Audit should identify certificate validity/expiry issues"


# ---------------------------------------------------------------------------
# Fixed PKI structure tests
# ---------------------------------------------------------------------------

class TestFixedPKIStructure:
    """Verify all required files exist in the rebuilt PKI."""

    REQUIRED_FILES = [
        "root-ca.pem", "root-ca.key",
        "intermediate-ca.pem", "intermediate-ca.key",
        "server.pem", "server.key",
        "client.pem", "client.key",
    ]

    def test_pki_directory_exists(self):
        assert os.path.isdir(PKI_FIXED_DIR), (
            f"Fixed PKI directory {PKI_FIXED_DIR} does not exist"
        )

    @pytest.mark.parametrize("filename", REQUIRED_FILES)
    def test_required_file_exists(self, filename):
        path = os.path.join(PKI_FIXED_DIR, filename)
        assert os.path.exists(path), f"Missing required file: {filename}"


# ---------------------------------------------------------------------------
# Root CA tests
# ---------------------------------------------------------------------------

class TestFixedRootCA:
    """Verify the rebuilt root CA meets compliance requirements."""

    def _load(self):
        return load_cert(os.path.join(PKI_FIXED_DIR, "root-ca.pem"))

    def test_is_self_signed_ca(self):
        cert = self._load()
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        assert bc.value.ca is True, "Root CA must have CA:TRUE"
        assert cert.issuer == cert.subject, "Root CA must be self-signed"

    def test_strong_signature_algorithm(self):
        cert = self._load()
        oid = cert.signature_algorithm_oid.dotted_string
        assert oid not in BANNED_SIG_OIDS, (
            f"Root CA uses banned signature algorithm OID {oid}"
        )

    def test_key_size_at_least_4096(self):
        cert = self._load()
        size = cert.public_key().key_size
        assert size >= 4096, f"Root CA key size {size} bits < required 4096"

    def test_has_key_usage(self):
        cert = self._load()
        ku = cert.extensions.get_extension_for_class(x509.KeyUsage)
        assert ku.value.key_cert_sign, "Root CA must have keyCertSign"
        assert ku.value.crl_sign, "Root CA must have cRLSign"


# ---------------------------------------------------------------------------
# Intermediate CA tests
# ---------------------------------------------------------------------------

class TestFixedIntermediateCA:
    """Verify the rebuilt intermediate CA meets compliance requirements."""

    def _load(self):
        return load_cert(os.path.join(PKI_FIXED_DIR, "intermediate-ca.pem"))

    def test_is_ca(self):
        cert = self._load()
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        assert bc.value.ca is True, "Intermediate CA must have CA:TRUE"

    def test_strong_signature_algorithm(self):
        cert = self._load()
        oid = cert.signature_algorithm_oid.dotted_string
        assert oid not in BANNED_SIG_OIDS, (
            f"Intermediate CA uses banned signature algorithm OID {oid}"
        )

    def test_key_size_at_least_2048(self):
        cert = self._load()
        size = cert.public_key().key_size
        assert size >= 2048, (
            f"Intermediate CA key size {size} bits < required 2048"
        )

    def test_signed_by_root_ca(self):
        root = load_cert(os.path.join(PKI_FIXED_DIR, "root-ca.pem"))
        inter = self._load()
        assert inter.issuer == root.subject, (
            "Intermediate CA issuer must match root CA subject"
        )


# ---------------------------------------------------------------------------
# Server certificate tests
# ---------------------------------------------------------------------------

class TestFixedServerCert:
    """Verify the rebuilt server certificate meets compliance requirements."""

    def _load(self):
        return load_cert(os.path.join(PKI_FIXED_DIR, "server.pem"))

    def _cert_text(self):
        return _openssl_text(os.path.join(PKI_FIXED_DIR, "server.pem"))

    def test_has_san_extension(self):
        """Verify server cert has SAN with at least one DNS name (via openssl)."""
        text = self._cert_text()
        assert "Subject Alternative Name" in text, (
            "Server certificate is missing SAN extension"
        )
        assert "DNS:" in text, (
            "SAN must contain at least one DNS name"
        )

    def test_san_contains_primary_domain(self):
        """Verify SAN includes server.examplecorp.com (via openssl)."""
        text = self._cert_text().lower()
        assert "dns:server.examplecorp.com" in text, (
            "SAN must include server.examplecorp.com"
        )

    def test_has_server_auth_eku(self):
        cert = self._load()
        try:
            eku = cert.extensions.get_extension_for_class(
                x509.ExtendedKeyUsage
            )
            assert ExtendedKeyUsageOID.SERVER_AUTH in eku.value, (
                "Server cert must have serverAuth EKU"
            )
        except x509.ExtensionNotFound:
            pytest.fail("Server certificate is missing EKU extension")

    def test_not_a_ca(self):
        cert = self._load()
        try:
            bc = cert.extensions.get_extension_for_class(
                x509.BasicConstraints
            )
            assert bc.value.ca is False, "Server cert must not be a CA"
        except x509.ExtensionNotFound:
            pass  # acceptable -- end-entity without BasicConstraints

    def test_validity_within_825_days(self):
        cert = self._load()
        nvb, nva = _get_validity(cert)
        validity_days = (nva - nvb).days
        assert validity_days <= 825, (
            f"Server cert validity {validity_days} days exceeds 825-day limit"
        )

    def test_strong_signature_algorithm(self):
        cert = self._load()
        oid = cert.signature_algorithm_oid.dotted_string
        assert oid not in BANNED_SIG_OIDS, (
            f"Server cert uses banned signature algorithm OID {oid}"
        )

    def test_not_expired(self):
        cert = self._load()
        _, nva = _get_validity(cert)
        now = datetime.datetime.now(datetime.timezone.utc)
        assert nva > now, "Server certificate is expired"


# ---------------------------------------------------------------------------
# Client certificate tests
# ---------------------------------------------------------------------------

class TestFixedClientCert:
    """Verify the rebuilt client certificate meets compliance requirements."""

    def _load(self):
        return load_cert(os.path.join(PKI_FIXED_DIR, "client.pem"))

    def test_has_client_auth_eku(self):
        cert = self._load()
        try:
            eku = cert.extensions.get_extension_for_class(
                x509.ExtendedKeyUsage
            )
            assert ExtendedKeyUsageOID.CLIENT_AUTH in eku.value, (
                "Client cert must have clientAuth EKU"
            )
        except x509.ExtensionNotFound:
            pytest.fail("Client certificate is missing EKU extension")

    def test_not_expired(self):
        cert = self._load()
        _, nva = _get_validity(cert)
        now = datetime.datetime.now(datetime.timezone.utc)
        assert nva > now, "Client certificate is expired"

    def test_strong_signature_algorithm(self):
        cert = self._load()
        oid = cert.signature_algorithm_oid.dotted_string
        assert oid not in BANNED_SIG_OIDS, (
            f"Client cert uses banned signature algorithm OID {oid}"
        )

    def test_key_size_at_least_2048(self):
        cert = self._load()
        size = cert.public_key().key_size
        assert size >= 2048, (
            f"Client cert key size {size} bits < required 2048"
        )


# ---------------------------------------------------------------------------
# Chain validation tests
# ---------------------------------------------------------------------------

class TestChainValidation:
    """Verify certificate chains validate via openssl."""

    def _build_intermediates_file(self):
        """Concatenate all CA certs (except root) into a temp file."""
        intermediates = []
        for fname in sorted(os.listdir(PKI_FIXED_DIR)):
            if not fname.endswith(".pem") or "key" in fname:
                continue
            if fname in ("root-ca.pem", "server.pem", "client.pem"):
                continue
            if "chain" in fname:
                continue
            path = os.path.join(PKI_FIXED_DIR, fname)
            try:
                cert = load_cert(path)
                bc = cert.extensions.get_extension_for_class(
                    x509.BasicConstraints
                )
                if bc.value.ca:
                    intermediates.append(path)
            except Exception:
                pass

        if not intermediates:
            return None

        combined = "/tmp/test_intermediates.pem"
        with open(combined, "wb") as out:
            for ipath in intermediates:
                with open(ipath, "rb") as inp:
                    out.write(inp.read())
        return combined

    def _verify_chain(self, end_entity_name):
        root = os.path.join(PKI_FIXED_DIR, "root-ca.pem")
        ee = os.path.join(PKI_FIXED_DIR, end_entity_name)
        intermediates = self._build_intermediates_file()

        cmd = ["openssl", "verify", "-CAfile", root]
        if intermediates:
            cmd.extend(["-untrusted", intermediates])
        cmd.append(ee)

        result = subprocess.run(cmd, capture_output=True, text=True)
        return result

    def test_server_chain_validates(self):
        result = self._verify_chain("server.pem")
        assert result.returncode == 0, (
            f"Server certificate chain validation failed:\n{result.stderr}"
        )

    def test_client_chain_validates(self):
        result = self._verify_chain("client.pem")
        assert result.returncode == 0, (
            f"Client certificate chain validation failed:\n{result.stderr}"
        )
