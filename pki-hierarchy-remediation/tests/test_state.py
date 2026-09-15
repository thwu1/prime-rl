
import os
import subprocess
import pytest
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtensionOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding as asym_padding
from datetime import datetime, timezone, timedelta

REMEDIATED = "/app/pki-remediated"
OLD_PKI = "/app/pki"


def load_cert(path):
    with open(path, "rb") as f:
        return x509.load_pem_x509_certificate(f.read())


def load_crl(path):
    with open(path, "rb") as f:
        return x509.load_pem_x509_crl(f.read())


# =====================================================================
# Root CA
# =====================================================================
class TestRootCA:
    @pytest.fixture
    def cert(self):
        return load_cert(f"{REMEDIATED}/root/root-ca.crt")

    def test_key_is_ecdsa_p384(self, cert):
        pub = cert.public_key()
        assert isinstance(pub, ec.EllipticCurvePublicKey), "Root key must be ECDSA"
        assert isinstance(pub.curve, ec.SECP384R1), "Root key must use P-384 curve"

    def test_signature_not_sha1(self, cert):
        assert not isinstance(cert.signature_hash_algorithm, hashes.SHA1)

    def test_signature_at_least_sha384(self, cert):
        assert isinstance(
            cert.signature_hash_algorithm, (hashes.SHA384, hashes.SHA512)
        )

    def test_basic_constraints(self, cert):
        bc = cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS)
        assert bc.critical
        assert bc.value.ca is True

    def test_key_usage(self, cert):
        ku = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE)
        assert ku.critical
        assert ku.value.key_cert_sign
        assert ku.value.crl_sign

    def test_subject_key_identifier(self, cert):
        cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_KEY_IDENTIFIER)

    def test_self_signed(self, cert):
        assert cert.issuer == cert.subject

    def test_validity(self, cert):
        now = datetime.now(timezone.utc)
        assert cert.not_valid_before_utc <= now
        assert cert.not_valid_after_utc > now


# =====================================================================
# TLS Intermediate CA
# =====================================================================
class TestTLSIntermediateCA:
    @pytest.fixture
    def cert(self):
        return load_cert(f"{REMEDIATED}/tls-intermediate/tls-intermediate.crt")

    @pytest.fixture
    def root(self):
        return load_cert(f"{REMEDIATED}/root/root-ca.crt")

    def test_not_sha1(self, cert):
        assert not isinstance(cert.signature_hash_algorithm, hashes.SHA1)

    def test_basic_constraints_pathlen_zero(self, cert):
        bc = cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS)
        assert bc.critical
        assert bc.value.ca is True
        assert bc.value.path_length == 0

    def test_key_usage(self, cert):
        ku = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE)
        assert ku.critical
        assert ku.value.key_cert_sign
        assert ku.value.crl_sign

    def test_name_constraints_present_and_critical(self, cert):
        nc = cert.extensions.get_extension_for_oid(ExtensionOID.NAME_CONSTRAINTS)
        assert nc.critical

    def test_name_constraints_permits_example_com(self, cert):
        nc = cert.extensions.get_extension_for_oid(ExtensionOID.NAME_CONSTRAINTS)
        permitted = nc.value.permitted_subtrees
        assert permitted is not None
        dns_names = [s.value for s in permitted if isinstance(s, x509.DNSName)]
        assert any(".example.com" in n for n in dns_names)

    def test_issuer_matches_root_subject(self, cert, root):
        assert cert.issuer == root.subject

    def test_authority_info_access_ocsp(self, cert):
        aia = cert.extensions.get_extension_for_oid(
            ExtensionOID.AUTHORITY_INFORMATION_ACCESS
        )
        ocsp_found = any(
            d.access_method == x509.oid.AuthorityInformationAccessOID.OCSP
            for d in aia.value
        )
        assert ocsp_found, "AIA must contain an OCSP responder URI"

    def test_crl_distribution_points(self, cert):
        cert.extensions.get_extension_for_oid(ExtensionOID.CRL_DISTRIBUTION_POINTS)

    def test_chain_validates(self):
        result = subprocess.run(
            [
                "openssl", "verify",
                "-CAfile", f"{REMEDIATED}/root/root-ca.crt",
                f"{REMEDIATED}/tls-intermediate/tls-intermediate.crt",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Chain validation failed: {result.stderr}"


# =====================================================================
# Code Signing Intermediate CA
# =====================================================================
class TestCSIntermediateCA:
    @pytest.fixture
    def cert(self):
        return load_cert(f"{REMEDIATED}/cs-intermediate/cs-intermediate.crt")

    def test_not_sha1(self, cert):
        assert not isinstance(cert.signature_hash_algorithm, hashes.SHA1)

    def test_basic_constraints_pathlen_zero(self, cert):
        bc = cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS)
        assert bc.critical
        assert bc.value.ca is True
        assert bc.value.path_length == 0

    def test_key_usage(self, cert):
        ku = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE)
        assert ku.critical
        assert ku.value.key_cert_sign
        assert ku.value.crl_sign

    def test_chain_validates(self):
        result = subprocess.run(
            [
                "openssl", "verify",
                "-CAfile", f"{REMEDIATED}/root/root-ca.crt",
                f"{REMEDIATED}/cs-intermediate/cs-intermediate.crt",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Chain validation failed: {result.stderr}"


# =====================================================================
# Server TLS Certificate
# =====================================================================
class TestServerCert:
    @pytest.fixture
    def cert(self):
        return load_cert(f"{REMEDIATED}/certs/server.crt")

    def test_has_san_with_www_example_com(self, cert):
        san = cert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        )
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert "www.example.com" in dns_names

    def test_has_at_least_two_san_dns_names(self, cert):
        san = cert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        )
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert len(dns_names) >= 2

    def test_key_usage_digital_signature(self, cert):
        ku = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE)
        assert ku.critical
        assert ku.value.digital_signature

    def test_eku_server_auth(self, cert):
        eku = cert.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE)
        assert ExtendedKeyUsageOID.SERVER_AUTH in eku.value

    def test_eku_no_code_signing(self, cert):
        eku = cert.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE)
        assert ExtendedKeyUsageOID.CODE_SIGNING not in eku.value

    def test_not_ca(self, cert):
        bc = cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS)
        assert bc.value.ca is False

    def test_not_sha1(self, cert):
        assert not isinstance(cert.signature_hash_algorithm, hashes.SHA1)

    def test_key_is_ecc(self, cert):
        assert isinstance(cert.public_key(), ec.EllipticCurvePublicKey)

    def test_chain_validates(self):
        result = subprocess.run(
            [
                "openssl", "verify",
                "-CAfile", f"{REMEDIATED}/root/root-ca.crt",
                "-untrusted", f"{REMEDIATED}/tls-intermediate/tls-intermediate.crt",
                f"{REMEDIATED}/certs/server.crt",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Chain validation failed: {result.stderr}"

    def test_fullchain_exists_with_multiple_certs(self):
        path = f"{REMEDIATED}/certs/server-fullchain.pem"
        assert os.path.isfile(path)
        with open(path, "rb") as f:
            data = f.read()
        certs = [
            c for c in data.split(b"-----END CERTIFICATE-----")
            if b"-----BEGIN CERTIFICATE-----" in c
        ]
        assert len(certs) >= 2, "Fullchain must contain at least leaf + intermediate"


# =====================================================================
# Code Signing Certificate
# =====================================================================
class TestCodeSigningCert:
    @pytest.fixture
    def cert(self):
        return load_cert(f"{REMEDIATED}/certs/codesign.crt")

    def test_eku_code_signing(self, cert):
        eku = cert.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE)
        assert ExtendedKeyUsageOID.CODE_SIGNING in eku.value

    def test_eku_no_server_auth(self, cert):
        eku = cert.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE)
        assert ExtendedKeyUsageOID.SERVER_AUTH not in eku.value

    def test_key_usage_digital_signature(self, cert):
        ku = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE)
        assert ku.value.digital_signature

    def test_issuer_is_cs_intermediate(self):
        cert = load_cert(f"{REMEDIATED}/certs/codesign.crt")
        ca = load_cert(f"{REMEDIATED}/cs-intermediate/cs-intermediate.crt")
        assert cert.issuer == ca.subject

    def test_chain_validates(self):
        result = subprocess.run(
            [
                "openssl", "verify",
                "-CAfile", f"{REMEDIATED}/root/root-ca.crt",
                "-untrusted", f"{REMEDIATED}/cs-intermediate/cs-intermediate.crt",
                f"{REMEDIATED}/certs/codesign.crt",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Chain validation failed: {result.stderr}"

    def test_fullchain_exists(self):
        assert os.path.isfile(f"{REMEDIATED}/certs/codesign-fullchain.pem")


# =====================================================================
# Client Authentication Certificate
# =====================================================================
class TestClientCert:
    @pytest.fixture
    def cert(self):
        return load_cert(f"{REMEDIATED}/certs/client.crt")

    def test_eku_client_auth(self, cert):
        eku = cert.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE)
        assert ExtendedKeyUsageOID.CLIENT_AUTH in eku.value

    def test_has_email_san(self, cert):
        san = cert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        )
        emails = san.value.get_values_for_type(x509.RFC822Name)
        assert len(emails) >= 1, "Client cert must have an RFC822Name (email) SAN"

    def test_not_expired(self, cert):
        now = datetime.now(timezone.utc)
        assert cert.not_valid_before_utc <= now
        assert cert.not_valid_after_utc > now

    def test_sufficient_validity(self, cert):
        remaining = cert.not_valid_after_utc - datetime.now(timezone.utc)
        assert remaining > timedelta(days=90), "Client cert must have reasonable validity"

    def test_chain_validates(self):
        result = subprocess.run(
            [
                "openssl", "verify",
                "-CAfile", f"{REMEDIATED}/root/root-ca.crt",
                "-untrusted", f"{REMEDIATED}/tls-intermediate/tls-intermediate.crt",
                f"{REMEDIATED}/certs/client.crt",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Chain validation failed: {result.stderr}"

    def test_fullchain_exists(self):
        assert os.path.isfile(f"{REMEDIATED}/certs/client-fullchain.pem")


# =====================================================================
# CRLs
# =====================================================================
class TestCRLs:
    def test_root_crl_exists_and_matches_issuer(self):
        crl = load_crl(f"{REMEDIATED}/root/root-ca.crl")
        root = load_cert(f"{REMEDIATED}/root/root-ca.crt")
        assert crl.issuer == root.subject

    def test_tls_intermediate_crl_exists_and_matches_issuer(self):
        crl = load_crl(f"{REMEDIATED}/tls-intermediate/tls-intermediate.crl")
        ca = load_cert(f"{REMEDIATED}/tls-intermediate/tls-intermediate.crt")
        assert crl.issuer == ca.subject

    def test_cs_intermediate_crl_exists_and_matches_issuer(self):
        crl = load_crl(f"{REMEDIATED}/cs-intermediate/cs-intermediate.crl")
        ca = load_cert(f"{REMEDIATED}/cs-intermediate/cs-intermediate.crt")
        assert crl.issuer == ca.subject


# =====================================================================
# OCSP Signing Certificate
# =====================================================================
class TestOCSPSigningCert:
    @pytest.fixture
    def cert(self):
        return load_cert(f"{REMEDIATED}/tls-intermediate/ocsp-signing.crt")

    def test_eku_ocsp_signing(self, cert):
        eku = cert.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE)
        assert ExtendedKeyUsageOID.OCSP_SIGNING in eku.value

    def test_ocsp_no_check(self, cert):
        cert.extensions.get_extension_for_oid(ExtensionOID.OCSP_NO_CHECK)

    def test_issuer_is_tls_intermediate(self):
        cert = load_cert(f"{REMEDIATED}/tls-intermediate/ocsp-signing.crt")
        ca = load_cert(f"{REMEDIATED}/tls-intermediate/tls-intermediate.crt")
        assert cert.issuer == ca.subject

    def test_not_ca(self, cert):
        bc = cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS)
        assert bc.value.ca is False


# =====================================================================
# Cross-Certification Bridge Certificate
# =====================================================================
class TestCrossCertification:
    def test_cross_cert_subject_matches_new_root(self):
        cross = load_cert(f"{REMEDIATED}/cross-cert/cross-cert.crt")
        new_root = load_cert(f"{REMEDIATED}/root/root-ca.crt")
        assert cross.subject == new_root.subject

    def test_cross_cert_issuer_matches_old_root(self):
        cross = load_cert(f"{REMEDIATED}/cross-cert/cross-cert.crt")
        old_root = load_cert(f"{OLD_PKI}/root-ca.crt")
        assert cross.issuer == old_root.subject

    def test_cross_cert_public_key_matches_new_root(self):
        cross = load_cert(f"{REMEDIATED}/cross-cert/cross-cert.crt")
        new_root = load_cert(f"{REMEDIATED}/root/root-ca.crt")
        cross_pub = cross.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        root_pub = new_root.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        assert cross_pub == root_pub

    def test_cross_cert_is_ca(self):
        cross = load_cert(f"{REMEDIATED}/cross-cert/cross-cert.crt")
        bc = cross.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS)
        assert bc.value.ca is True

    def test_cross_cert_signature_valid(self):
        """Verify the cross-cert signature using the old root's RSA public key."""
        cross = load_cert(f"{REMEDIATED}/cross-cert/cross-cert.crt")
        old_root = load_cert(f"{OLD_PKI}/root-ca.crt")
        old_pub = old_root.public_key()
        # RSA PKCS#1 v1.5 signature verification
        old_pub.verify(
            cross.signature,
            cross.tbs_certificate_bytes,
            asym_padding.PKCS1v15(),
            cross.signature_hash_algorithm,
        )
