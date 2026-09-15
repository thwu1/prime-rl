"""Tests for PKI Chain Rebuild task.

Validates the complete PKI hierarchy: Root CA, Intermediate CA,
server certificate, client certificate, chain file, CRL, and
file permissions. Deployment-specific values (audit stamp, server IP)
are loaded from deploy_params.json generated at build time.
"""

import json
import os
import re
import stat
import subprocess


BASE = "/app/pki"

with open(f"{BASE}/deploy_params.json") as _f:
    _PARAMS = json.load(_f)
AUDIT_STAMP = _PARAMS["audit_stamp"]
SERVER_SAN_IP = _PARAMS["server_san_ip"]


def run(cmd):
    """Execute a shell command and return the CompletedProcess."""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


# -- Root CA -----------------------------------------------------------

class TestRootCA:

    def test_root_cert_exists(self):
        assert os.path.isfile(f"{BASE}/root-ca/certs/root-ca.crt"), \
            "Root CA certificate not found"

    def test_root_key_permissions(self):
        st = os.stat(f"{BASE}/root-ca/private/root-ca.key")
        mode = stat.S_IMODE(st.st_mode)
        assert mode == 0o400, f"Root key mode {oct(mode)}, expected 0400"

    def test_root_is_self_signed(self):
        r = run(f"openssl x509 -in {BASE}/root-ca/certs/root-ca.crt "
                "-noout -issuer -subject")
        assert r.returncode == 0
        lines = r.stdout.strip().split("\n")
        issuer = lines[0].split("=", 1)[1].strip()
        subject = lines[1].split("=", 1)[1].strip()
        assert issuer == subject, "Root CA is not self-signed"

    def test_root_is_ca_true(self):
        r = run(f"openssl x509 -in {BASE}/root-ca/certs/root-ca.crt "
                "-noout -text")
        assert "CA:TRUE" in r.stdout, "Root CA basicConstraints must be CA:TRUE"

    def test_root_key_usage_cert_sign(self):
        r = run(f"openssl x509 -in {BASE}/root-ca/certs/root-ca.crt "
                "-noout -text")
        assert "Certificate Sign" in r.stdout, "Root CA must have keyCertSign"

    def test_root_key_usage_crl_sign(self):
        r = run(f"openssl x509 -in {BASE}/root-ca/certs/root-ca.crt "
                "-noout -text")
        assert "CRL Sign" in r.stdout, "Root CA must have cRLSign"

    def test_root_signature_strong_hash(self):
        r = run(f"openssl x509 -in {BASE}/root-ca/certs/root-ca.crt "
                "-noout -text")
        sig_lines = [l.strip() for l in r.stdout.split("\n")
                     if "Signature Algorithm" in l]
        assert len(sig_lines) > 0, "No Signature Algorithm line found"
        for line in sig_lines:
            low = line.lower()
            assert "md5" not in low, f"Weak hash MD5: {line}"
            assert "sha1with" not in low, f"Weak hash SHA-1: {line}"

    def test_root_self_verify(self):
        r = run(f"openssl verify -CAfile {BASE}/root-ca/certs/root-ca.crt "
                f"{BASE}/root-ca/certs/root-ca.crt")
        assert r.returncode == 0 and "OK" in r.stdout, \
            f"Root self-verification failed: {r.stdout} {r.stderr}"

    def test_root_ou_contains_stamp(self):
        r = run(f"openssl x509 -in {BASE}/root-ca/certs/root-ca.crt "
                "-noout -subject")
        assert AUDIT_STAMP in r.stdout, \
            f"Root CA subject must contain audit stamp '{AUDIT_STAMP}'"


# -- Intermediate CA ---------------------------------------------------

class TestIntermediateCA:

    def test_intermediate_cert_exists(self):
        assert os.path.isfile(
            f"{BASE}/intermediate-ca/certs/intermediate-ca.crt")

    def test_intermediate_key_exists(self):
        assert os.path.isfile(
            f"{BASE}/intermediate-ca/private/intermediate-ca.key")

    def test_intermediate_key_permissions(self):
        st = os.stat(f"{BASE}/intermediate-ca/private/intermediate-ca.key")
        mode = stat.S_IMODE(st.st_mode)
        assert mode == 0o400, \
            f"Intermediate key mode {oct(mode)}, expected 0400"

    def test_intermediate_chains_to_root(self):
        r = run(f"openssl verify "
                f"-CAfile {BASE}/root-ca/certs/root-ca.crt "
                f"{BASE}/intermediate-ca/certs/intermediate-ca.crt")
        assert r.returncode == 0 and "OK" in r.stdout, \
            f"Intermediate chain failed: {r.stdout} {r.stderr}"

    def test_intermediate_is_ca_true(self):
        r = run(f"openssl x509 "
                f"-in {BASE}/intermediate-ca/certs/intermediate-ca.crt "
                "-noout -text")
        assert "CA:TRUE" in r.stdout

    def test_intermediate_pathlen_zero(self):
        r = run(f"openssl x509 "
                f"-in {BASE}/intermediate-ca/certs/intermediate-ca.crt "
                "-noout -text")
        assert "pathlen:0" in r.stdout, \
            "Intermediate CA must have pathlen:0"

    def test_intermediate_key_usage(self):
        r = run(f"openssl x509 "
                f"-in {BASE}/intermediate-ca/certs/intermediate-ca.crt "
                "-noout -text")
        assert "Certificate Sign" in r.stdout
        assert "CRL Sign" in r.stdout

    def test_intermediate_signature_strong_hash(self):
        r = run(f"openssl x509 "
                f"-in {BASE}/intermediate-ca/certs/intermediate-ca.crt "
                "-noout -text")
        sig_lines = [l.strip() for l in r.stdout.split("\n")
                     if "Signature Algorithm" in l]
        for line in sig_lines:
            low = line.lower()
            assert "md5" not in low, f"Weak hash MD5: {line}"
            assert "sha1with" not in low, f"Weak hash SHA-1: {line}"

    def test_intermediate_ou_contains_stamp(self):
        r = run(f"openssl x509 "
                f"-in {BASE}/intermediate-ca/certs/intermediate-ca.crt "
                "-noout -subject")
        assert AUDIT_STAMP in r.stdout, \
            f"Intermediate CA subject must contain audit stamp '{AUDIT_STAMP}'"


# -- Chain File --------------------------------------------------------

class TestChainFile:

    def test_chain_file_exists(self):
        assert os.path.isfile(
            f"{BASE}/intermediate-ca/certs/ca-chain.crt")

    def test_chain_contains_two_certs(self):
        with open(f"{BASE}/intermediate-ca/certs/ca-chain.crt") as f:
            content = f.read()
        count = content.count("BEGIN CERTIFICATE")
        assert count == 2, \
            f"Chain should contain 2 certificates, found {count}"

    def test_chain_validates_intermediate(self):
        r = run(f"openssl verify "
                f"-CAfile {BASE}/intermediate-ca/certs/ca-chain.crt "
                f"{BASE}/intermediate-ca/certs/intermediate-ca.crt")
        assert "OK" in r.stdout


# -- Server Certificate ------------------------------------------------

class TestServerCert:

    CERT = f"{BASE}/intermediate-ca/certs/server/web.securecorp.lab.crt"
    KEY = f"{BASE}/intermediate-ca/private/server/web.securecorp.lab.key"

    def test_server_cert_exists(self):
        assert os.path.isfile(self.CERT)

    def test_server_key_permissions(self):
        assert os.path.isfile(self.KEY), "Server key not found"
        mode = stat.S_IMODE(os.stat(self.KEY).st_mode)
        assert mode == 0o400, f"Server key mode {oct(mode)}, expected 0400"

    def test_server_cert_chain_validates(self):
        r = run(f"openssl verify "
                f"-CAfile {BASE}/intermediate-ca/certs/ca-chain.crt "
                f"{self.CERT}")
        assert r.returncode == 0 and "OK" in r.stdout, \
            f"Server cert chain validation failed: {r.stdout} {r.stderr}"

    def test_server_cert_not_ca(self):
        r = run(f"openssl x509 -in {self.CERT} -noout -text")
        assert "CA:FALSE" in r.stdout

    def test_server_cert_san_dns_web(self):
        r = run(f"openssl x509 -in {self.CERT} -noout -text")
        assert "DNS:web.securecorp.lab" in r.stdout

    def test_server_cert_san_dns_www(self):
        r = run(f"openssl x509 -in {self.CERT} -noout -text")
        assert "DNS:www.securecorp.lab" in r.stdout

    def test_server_cert_san_ip(self):
        r = run(f"openssl x509 -in {self.CERT} -noout -text")
        assert f"IP Address:{SERVER_SAN_IP}" in r.stdout, \
            f"Server cert SAN must contain IP {SERVER_SAN_IP}"

    def test_server_cert_eku_server_auth(self):
        r = run(f"openssl x509 -in {self.CERT} -noout -text")
        assert "TLS Web Server Authentication" in r.stdout, \
            "Server cert must have serverAuth EKU"

    def test_server_cert_permissions(self):
        mode = stat.S_IMODE(os.stat(self.CERT).st_mode)
        assert mode == 0o444, f"Server cert mode {oct(mode)}, expected 0444"

    def test_server_ou_contains_stamp(self):
        r = run(f"openssl x509 -in {self.CERT} -noout -subject")
        assert AUDIT_STAMP in r.stdout, \
            f"Server cert subject must contain audit stamp '{AUDIT_STAMP}'"


# -- Client Certificate ------------------------------------------------

class TestClientCert:

    CERT = f"{BASE}/intermediate-ca/certs/client/alice.crt"
    KEY = f"{BASE}/intermediate-ca/private/client/alice.key"

    def test_client_cert_exists(self):
        assert os.path.isfile(self.CERT)

    def test_client_key_permissions(self):
        assert os.path.isfile(self.KEY), "Client key not found"
        mode = stat.S_IMODE(os.stat(self.KEY).st_mode)
        assert mode == 0o400

    def test_client_cert_eku_client_auth(self):
        r = run(f"openssl x509 -in {self.CERT} -noout -text")
        assert "TLS Web Client Authentication" in r.stdout

    def test_client_cert_eku_email_protection(self):
        r = run(f"openssl x509 -in {self.CERT} -noout -text")
        assert "E-mail Protection" in r.stdout

    def test_client_cert_email_san(self):
        r = run(f"openssl x509 -in {self.CERT} -noout -text")
        assert "alice@securecorp.lab" in r.stdout

    def test_client_cert_permissions(self):
        mode = stat.S_IMODE(os.stat(self.CERT).st_mode)
        assert mode == 0o444

    def test_client_ou_contains_stamp(self):
        r = run(f"openssl x509 -in {self.CERT} -noout -subject")
        assert AUDIT_STAMP in r.stdout, \
            f"Client cert subject must contain audit stamp '{AUDIT_STAMP}'"


# -- Revocation / CRL -------------------------------------------------

class TestRevocation:

    CRL = f"{BASE}/intermediate-ca/crl/intermediate-ca.crl"

    def test_crl_exists(self):
        assert os.path.isfile(self.CRL)

    def test_crl_is_valid(self):
        r = run(f"openssl crl -in {self.CRL} -noout -text")
        assert r.returncode == 0, f"CRL parse failed: {r.stderr}"

    def test_client_cert_serial_in_crl(self):
        r1 = run(f"openssl x509 "
                 f"-in {BASE}/intermediate-ca/certs/client/alice.crt "
                 "-noout -serial")
        serial = r1.stdout.strip().split("=")[1].upper()
        r2 = run(f"openssl crl -in {self.CRL} -noout -text")
        revoked = re.findall(
            r"Serial Number:\s*([0-9A-Fa-f]+)", r2.stdout)
        revoked_upper = [s.upper() for s in revoked]
        assert serial in revoked_upper, \
            f"Client serial {serial} not in CRL revoked list: {revoked_upper}"

    def test_server_cert_serial_not_in_crl(self):
        r1 = run(
            f"openssl x509 -in "
            f"{BASE}/intermediate-ca/certs/server/web.securecorp.lab.crt "
            "-noout -serial")
        serial = r1.stdout.strip().split("=")[1].upper()
        r2 = run(f"openssl crl -in {self.CRL} -noout -text")
        revoked = re.findall(
            r"Serial Number:\s*([0-9A-Fa-f]+)", r2.stdout)
        revoked_upper = [s.upper() for s in revoked]
        assert serial not in revoked_upper, \
            f"Server serial {serial} should NOT be in CRL"

    def test_client_cert_revoked_in_index(self):
        r = run(f"openssl x509 "
                f"-in {BASE}/intermediate-ca/certs/client/alice.crt "
                "-noout -serial")
        serial = r.stdout.strip().split("=")[1].upper()
        with open(f"{BASE}/intermediate-ca/index.txt") as f:
            for line in f:
                if serial in line.upper():
                    assert line.strip().startswith("R"), \
                        f"Client cert should be Revoked in index.txt: {line}"
                    return
        assert False, f"Serial {serial} not found in index.txt"
