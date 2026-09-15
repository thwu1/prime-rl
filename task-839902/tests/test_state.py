
import subprocess
import os
import re
import time
import socket

OPENSSL = "/usr/local/bin/openssl"
PKI = "/app/pki"


def openssl_run(*args, timeout=30):
    result = subprocess.run(
        [OPENSSL] + list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


def cert_text(cert_path):
    r = openssl_run("x509", "-in", cert_path, "-noout", "-text")
    assert r.returncode == 0, f"Failed to parse certificate {cert_path}: {r.stderr}"
    return r.stdout


def has_mldsa87(text):
    return bool(re.search(r"(?i)(mldsa87|ml-dsa-87)", text))


def has_mldsa65(text):
    return bool(re.search(r"(?i)(mldsa65|ml-dsa-65)", text))


def get_signature_algorithms(text):
    return re.findall(r"Signature Algorithm:\s*(\S+)", text)


def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# File structure tests
# ---------------------------------------------------------------------------
class TestFileStructure:
    def test_root_ca_key_exists(self):
        assert os.path.isfile(f"{PKI}/root-ca/private/root-ca.key")

    def test_root_ca_cert_exists(self):
        assert os.path.isfile(f"{PKI}/root-ca/certs/root-ca.crt")

    def test_root_ca_config_exists(self):
        assert os.path.isfile(f"{PKI}/root-ca/openssl.cnf")

    def test_intermediate_ca_key_exists(self):
        assert os.path.isfile(f"{PKI}/intermediate-ca/private/intermediate-ca.key")

    def test_intermediate_ca_cert_exists(self):
        assert os.path.isfile(f"{PKI}/intermediate-ca/certs/intermediate-ca.crt")

    def test_intermediate_ca_config_exists(self):
        assert os.path.isfile(f"{PKI}/intermediate-ca/openssl.cnf")

    def test_server_cert_exists(self):
        assert os.path.isfile(f"{PKI}/intermediate-ca/certs/server.crt")

    def test_server_key_exists(self):
        assert os.path.isfile(f"{PKI}/intermediate-ca/private/server.key")

    def test_client_cert_exists(self):
        assert os.path.isfile(f"{PKI}/intermediate-ca/certs/client.crt")

    def test_ocsp_cert_exists(self):
        assert os.path.isfile(f"{PKI}/intermediate-ca/certs/ocsp.crt")

    def test_ca_chain_exists(self):
        assert os.path.isfile(f"{PKI}/certs/ca-chain.crt")

    def test_crl_exists(self):
        assert os.path.isfile(f"{PKI}/intermediate-ca/crl/intermediate-ca.crl")

    def test_tls_result_exists(self):
        assert os.path.isfile(f"{PKI}/tls-test-result.txt")

    def test_audit_report_exists(self):
        assert os.path.isfile(f"{PKI}/audit-report.txt")


# ---------------------------------------------------------------------------
# Root CA certificate tests — must use ML-DSA-87, NOT ML-DSA-65
# ---------------------------------------------------------------------------
class TestRootCA:
    def test_mldsa87_signature(self):
        text = cert_text(f"{PKI}/root-ca/certs/root-ca.crt")
        assert has_mldsa87(text), \
            "Root CA certificate must use ML-DSA-87 signature algorithm"

    def test_not_mldsa65(self):
        text = cert_text(f"{PKI}/root-ca/certs/root-ca.crt")
        assert not has_mldsa65(text), \
            "Root CA must NOT use ML-DSA-65 (not CNSA 2.0 compliant)"

    def test_signature_algorithm_lines(self):
        text = cert_text(f"{PKI}/root-ca/certs/root-ca.crt")
        sig_algos = get_signature_algorithms(text)
        assert len(sig_algos) >= 1, "Could not find Signature Algorithm in Root CA cert"
        for algo in sig_algos:
            assert re.search(r"(?i)mldsa87|ml-dsa-87", algo), \
                f"Root CA Signature Algorithm must be ML-DSA-87, found: {algo}"

    def test_basic_constraints_ca_true(self):
        text = cert_text(f"{PKI}/root-ca/certs/root-ca.crt")
        assert "CA:TRUE" in text

    def test_no_pathlen(self):
        text = cert_text(f"{PKI}/root-ca/certs/root-ca.crt")
        bc_match = re.search(
            r"X509v3 Basic Constraints.*?critical.*?\n\s*(.*)", text
        )
        if bc_match:
            assert "pathlen" not in bc_match.group(1).lower(), \
                "Root CA must NOT have a pathlen constraint"

    def test_key_usage(self):
        text = cert_text(f"{PKI}/root-ca/certs/root-ca.crt")
        assert "Certificate Sign" in text
        assert "CRL Sign" in text

    def test_subject_cn(self):
        r = openssl_run("x509", "-in", f"{PKI}/root-ca/certs/root-ca.crt",
                        "-noout", "-subject")
        assert "PQC Root CA" in r.stdout

    def test_self_signed_verify(self):
        r = openssl_run("verify", "-CAfile",
                        f"{PKI}/root-ca/certs/root-ca.crt",
                        f"{PKI}/root-ca/certs/root-ca.crt")
        combined = r.stdout + r.stderr
        assert r.returncode == 0 or "OK" in combined, \
            f"Root CA self-verification failed: {combined}"


# ---------------------------------------------------------------------------
# Intermediate CA — signature must be ML-DSA-87 (fixed from ML-DSA-65)
# ---------------------------------------------------------------------------
class TestIntermediateCA:
    def test_mldsa87_present(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/intermediate-ca.crt")
        assert has_mldsa87(text), \
            "Intermediate CA cert must contain ML-DSA-87 references"

    def test_not_mldsa65(self):
        """The broken PKI had ML-DSA-65 signing. After fix, no ML-DSA-65 should remain."""
        text = cert_text(f"{PKI}/intermediate-ca/certs/intermediate-ca.crt")
        assert not has_mldsa65(text), \
            "Intermediate CA cert must NOT contain ML-DSA-65 (was signed by non-compliant Root)"

    def test_signature_algorithm_is_mldsa87(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/intermediate-ca.crt")
        sig_algos = get_signature_algorithms(text)
        for algo in sig_algos:
            assert re.search(r"(?i)mldsa87|ml-dsa-87", algo), \
                f"Intermediate CA Signature Algorithm must be ML-DSA-87, found: {algo}"

    def test_basic_constraints_ca_true(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/intermediate-ca.crt")
        assert "CA:TRUE" in text

    def test_pathlen_zero(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/intermediate-ca.crt")
        assert re.search(r"pathlen\s*:\s*0", text), \
            "Intermediate CA must have pathlen:0"

    def test_key_usage(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/intermediate-ca.crt")
        assert "Certificate Sign" in text
        assert "CRL Sign" in text

    def test_chain_validates_against_root(self):
        r = openssl_run("verify", "-CAfile",
                        f"{PKI}/root-ca/certs/root-ca.crt",
                        f"{PKI}/intermediate-ca/certs/intermediate-ca.crt")
        combined = r.stdout + r.stderr
        assert r.returncode == 0 or "OK" in combined, \
            f"Intermediate CA chain validation failed: {combined}"

    def test_issuer_is_root(self):
        r = openssl_run("x509", "-in",
                        f"{PKI}/intermediate-ca/certs/intermediate-ca.crt",
                        "-noout", "-issuer")
        assert "PQC Root CA" in r.stdout


# ---------------------------------------------------------------------------
# Server certificate tests — must NOT have keyEncipherment
# ---------------------------------------------------------------------------
class TestServerCert:
    def test_mldsa87_signature(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/server.crt")
        assert has_mldsa87(text)

    def test_not_ca(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/server.crt")
        assert "CA:FALSE" in text

    def test_extended_key_usage_server_auth(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/server.crt")
        assert ("TLS Web Server Authentication" in text
                or "serverAuth" in text)

    def test_no_key_encipherment(self):
        """ML-DSA is a pure signature algorithm — keyEncipherment is semantically invalid."""
        text = cert_text(f"{PKI}/intermediate-ca/certs/server.crt")
        assert "Key Encipherment" not in text, \
            "Server cert keyUsage must NOT include Key Encipherment (invalid for PQC signature keys)"

    def test_san_dns_server(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/server.crt")
        assert "server.pqc.lab" in text

    def test_san_dns_wildcard(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/server.crt")
        assert "*.pqc.lab" in text, \
            "Server cert SAN must include DNS:*.pqc.lab"

    def test_san_ip(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/server.crt")
        assert "10.0.0.1" in text, \
            "Server cert SAN must include IP:10.0.0.1"

    def test_subject_cn(self):
        r = openssl_run("x509", "-in", f"{PKI}/intermediate-ca/certs/server.crt",
                        "-noout", "-subject")
        assert "server.pqc.lab" in r.stdout

    def test_chain_validates(self):
        r = openssl_run("verify", "-CAfile",
                        f"{PKI}/certs/ca-chain.crt",
                        f"{PKI}/intermediate-ca/certs/server.crt")
        combined = r.stdout + r.stderr
        assert r.returncode == 0 or "OK" in combined, \
            f"Server cert chain validation failed: {combined}"

    def test_issuer_is_intermediate(self):
        r = openssl_run("x509", "-in", f"{PKI}/intermediate-ca/certs/server.crt",
                        "-noout", "-issuer")
        assert "PQC Intermediate CA" in r.stdout


# ---------------------------------------------------------------------------
# Client certificate tests — must have clientAuth + emailProtection
# ---------------------------------------------------------------------------
class TestClientCert:
    def test_mldsa87_signature(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/client.crt")
        assert has_mldsa87(text)

    def test_not_ca(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/client.crt")
        assert "CA:FALSE" in text

    def test_client_auth(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/client.crt")
        assert ("TLS Web Client Authentication" in text
                or "clientAuth" in text), \
            "Client cert must have extendedKeyUsage clientAuth"

    def test_email_protection(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/client.crt")
        assert ("E-mail Protection" in text
                or "emailProtection" in text), \
            "Client cert must have extendedKeyUsage emailProtection"

    def test_no_server_auth_only(self):
        """The broken PKI had serverAuth as the only EKU. Verify clientAuth is present."""
        text = cert_text(f"{PKI}/intermediate-ca/certs/client.crt")
        has_client = ("TLS Web Client Authentication" in text or "clientAuth" in text)
        assert has_client, \
            "Client cert EKU must include clientAuth (was incorrectly serverAuth in broken PKI)"

    def test_subject_cn(self):
        r = openssl_run("x509", "-in", f"{PKI}/intermediate-ca/certs/client.crt",
                        "-noout", "-subject")
        assert "client@pqc.lab" in r.stdout


# ---------------------------------------------------------------------------
# OCSP signing certificate tests
# ---------------------------------------------------------------------------
class TestOCSPCert:
    def test_mldsa87_signature(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/ocsp.crt")
        assert has_mldsa87(text)

    def test_not_ca(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/ocsp.crt")
        assert "CA:FALSE" in text

    def test_ocsp_signing(self):
        text = cert_text(f"{PKI}/intermediate-ca/certs/ocsp.crt")
        assert "OCSP Signing" in text

    def test_subject_cn(self):
        r = openssl_run("x509", "-in", f"{PKI}/intermediate-ca/certs/ocsp.crt",
                        "-noout", "-subject")
        assert "OCSP Responder" in r.stdout


# ---------------------------------------------------------------------------
# CRL tests — must contain at least one revoked serial
# ---------------------------------------------------------------------------
class TestCRL:
    def test_crl_parseable(self):
        r = openssl_run("crl", "-in",
                        f"{PKI}/intermediate-ca/crl/intermediate-ca.crl",
                        "-noout", "-text")
        assert r.returncode == 0, f"CRL parse failed: {r.stderr}"

    def test_crl_has_revoked_certificates(self):
        r = openssl_run("crl", "-in",
                        f"{PKI}/intermediate-ca/crl/intermediate-ca.crl",
                        "-noout", "-text")
        assert "Revoked Certificates" in r.stdout, \
            "CRL must contain a 'Revoked Certificates' section (was empty in broken PKI)"

    def test_crl_has_serial_number(self):
        r = openssl_run("crl", "-in",
                        f"{PKI}/intermediate-ca/crl/intermediate-ca.crl",
                        "-noout", "-text")
        assert re.search(r"Serial Number:\s*[0-9A-Fa-f]+", r.stdout), \
            "CRL must contain at least one revoked certificate serial number"


# ---------------------------------------------------------------------------
# Chain bundle tests
# ---------------------------------------------------------------------------
class TestChainBundle:
    def test_chain_contains_two_certs(self):
        with open(f"{PKI}/certs/ca-chain.crt") as f:
            content = f.read()
        cert_count = content.count("BEGIN CERTIFICATE")
        assert cert_count >= 2, \
            f"Chain bundle must contain at least 2 certificates, found {cert_count}"

    def test_chain_includes_both_cas(self):
        r = openssl_run("crl2pkcs7", "-nocrl", "-certfile",
                        f"{PKI}/certs/ca-chain.crt")
        if r.returncode != 0:
            with open(f"{PKI}/certs/ca-chain.crt") as f:
                content = f.read()
            assert "CERTIFICATE" in content
            return
        r2 = subprocess.run(
            [OPENSSL, "pkcs7", "-print_certs", "-noout"],
            input=r.stdout, capture_output=True, text=True
        )
        combined = r2.stdout + r2.stderr
        assert "PQC Intermediate CA" in combined or "PQC Root CA" in combined


# ---------------------------------------------------------------------------
# TLS test output verification
# ---------------------------------------------------------------------------
class TestTLSOutput:
    def test_tls_shows_tls13(self):
        with open(f"{PKI}/tls-test-result.txt") as f:
            content = f.read()
        assert "TLSv1.3" in content

    def test_tls_shows_hybrid_kex(self):
        with open(f"{PKI}/tls-test-result.txt") as f:
            content = f.read()
        assert re.search(
            r"(?i)x25519.?mlkem.?768|X25519MLKEM768", content
        ), "TLS test output must show X25519MLKEM768 hybrid key exchange"

    def test_tls_verify_ok(self):
        with open(f"{PKI}/tls-test-result.txt") as f:
            content = f.read()
        assert "Verify return code: 0" in content


# ---------------------------------------------------------------------------
# Audit report verification — must mention discovered defects
# ---------------------------------------------------------------------------
class TestAuditReport:
    def test_report_substantial(self):
        with open(f"{PKI}/audit-report.txt") as f:
            content = f.read()
        assert len(content) > 200, \
            f"Audit report should be substantial (found {len(content)} chars)"

    def test_report_mentions_mldsa65(self):
        """Agent must have inspected Root CA and discovered ML-DSA-65 usage."""
        with open(f"{PKI}/audit-report.txt") as f:
            content = f.read().lower()
        assert "mldsa65" in content or "ml-dsa-65" in content or "dsa-65" in content, \
            "Audit report must identify the ML-DSA-65 algorithm compliance issue"

    def test_report_mentions_key_encipherment(self):
        """Agent must have inspected server cert and found keyEncipherment issue."""
        with open(f"{PKI}/audit-report.txt") as f:
            content = f.read().lower()
        assert "keyencipherment" in content or "key encipherment" in content, \
            "Audit report must identify the keyEncipherment issue on server cert"


# ---------------------------------------------------------------------------
# Live TLS handshake test
# ---------------------------------------------------------------------------
class TestLiveTLS:
    def test_live_tls_handshake(self):
        server_cert = f"{PKI}/intermediate-ca/certs/server.crt"
        server_key = f"{PKI}/intermediate-ca/private/server.key"
        ca_chain = f"{PKI}/certs/ca-chain.crt"

        for path in [server_cert, server_key, ca_chain]:
            assert os.path.isfile(path), f"Required file missing: {path}"

        port = get_free_port()

        server = subprocess.Popen(
            [OPENSSL, "s_server",
             "-cert", server_cert,
             "-key", server_key,
             "-CAfile", ca_chain,
             "-port", str(port),
             "-tls1_3",
             "-groups", "X25519MLKEM768:X25519",
             "-www"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        time.sleep(3)

        try:
            assert server.poll() is None, \
                f"s_server exited prematurely: {server.stderr.read().decode()}"

            client = subprocess.run(
                [OPENSSL, "s_client",
                 "-connect", f"localhost:{port}",
                 "-tls1_3",
                 "-groups", "X25519MLKEM768",
                 "-CAfile", ca_chain],
                input=b"Q\n",
                capture_output=True,
                timeout=15,
            )

            output = client.stdout.decode() + client.stderr.decode()
            success = (
                "Verify return code: 0" in output
                or ("TLSv1.3" in output and "CONNECTED" in output)
            )
            assert success, \
                f"Live TLS handshake failed. Output excerpt:\n{output[:2000]}"

        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
