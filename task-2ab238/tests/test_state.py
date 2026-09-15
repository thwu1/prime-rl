
import json
import os
import re
import subprocess
import pytest


def run_openssl(args):
    """Run an openssl command and return (stdout, stderr, returncode)."""
    result = subprocess.run(
        ["openssl"] + args,
        capture_output=True, text=True
    )
    return result.stdout, result.stderr, result.returncode


# ============================================================
# AUDIT REPORT TESTS
# ============================================================

class TestAuditReport:
    """Verify the audit report correctly identifies all planted vulnerabilities."""

    @pytest.fixture(autouse=True)
    def load_report(self):
        path = "/app/audit_report.json"
        assert os.path.exists(path), "audit_report.json not found at /app/"
        with open(path) as f:
            self.report = json.load(f)
        assert "findings" in self.report, "Report must contain a 'findings' array"
        self.all_text = json.dumps(self.report["findings"]).lower()

    def _findings_for(self, file_pattern):
        """Get findings matching a file pattern."""
        matches = []
        for f in self.report["findings"]:
            f_str = json.dumps(f).lower()
            if file_pattern in f_str:
                matches.append(f_str)
        return matches

    def test_minimum_finding_count(self):
        """Must identify at least 11 distinct vulnerabilities."""
        assert len(self.report["findings"]) >= 11, \
            f"Expected at least 11 findings, got {len(self.report['findings'])}"

    def test_identifies_weak_root_key(self):
        """Root CA has 1024-bit RSA key."""
        root = self._findings_for("root")
        root_text = " ".join(root)
        assert any(kw in root_text for kw in [
            "1024", "weak key", "small key", "insufficient key",
            "key size", "key length", "short key", "insecure key"
        ]), "Report must identify weak 1024-bit root CA key"

    def test_identifies_missing_basic_constraints_on_root(self):
        """Root CA is missing basicConstraints CA:TRUE."""
        root = self._findings_for("root")
        root_text = " ".join(root)
        assert any(kw in root_text for kw in [
            "basicconstraint", "basic constraint", "basic_constraint",
            "ca:true", "ca: true", "ca flag", "not marked as ca",
            "missing ca", "no ca constraint", "ca extension",
            "not identified as a ca", "ca trust"
        ]), "Report must identify missing basicConstraints on root CA"

    def test_identifies_sha1_intermediate(self):
        """Intermediate CA signed with SHA-1."""
        inter = self._findings_for("intermediate")
        inter_text = " ".join(inter)
        assert any(kw in inter_text for kw in [
            "sha1", "sha-1", "weak hash", "weak signature",
            "deprecated hash", "deprecated algorithm",
            "deprecated signature", "insecure hash",
            "sha1withrsaencryption"
        ]), "Report must identify SHA-1 signature on intermediate CA"

    def test_identifies_server_ca_true(self):
        """Server cert has basicConstraints CA:TRUE."""
        server = self._findings_for("server")
        server_text = " ".join(server)
        assert any(kw in server_text for kw in [
            "ca:true", "ca: true", "ca flag", "marked as ca",
            "is a ca", "basicconstraint", "basic constraint",
            "should not be ca", "not be a ca", "leaf.*ca",
            "end.entity.*ca", "end entity.*ca", "ca=true"
        ]), "Report must identify CA:TRUE on server certificate"

    def test_identifies_missing_san(self):
        """Server cert missing Subject Alternative Name."""
        assert any(kw in self.all_text for kw in [
            "san", "subject alternative name", "subjectaltname",
            "subjectalternativename", "alternative name"
        ]), "Report must identify missing SAN on server certificate"

    def test_identifies_server_wrong_key_usage(self):
        """Server cert has keyCertSign in keyUsage."""
        server = self._findings_for("server")
        server_text = " ".join(server)
        assert any(kw in server_text for kw in [
            "keycertsign", "key cert sign", "key_cert_sign",
            "certificate sign", "wrong key usage",
            "inappropriate key usage", "incorrect key usage",
            "keyusage", "key usage"
        ]), "Report must identify wrong keyUsage on server cert"

    def test_identifies_client_wrong_eku(self):
        """Client cert has serverAuth instead of clientAuth EKU."""
        client = self._findings_for("client")
        client_text = " ".join(client)
        assert any(kw in client_text for kw in [
            "serverauth", "server auth", "server_auth",
            "wrong extended", "incorrect extended",
            "extendedkeyusage", "extended key usage", "eku",
            "wrong eku", "clientauth", "client auth"
        ]), "Report must identify wrong extKeyUsage on client certificate"

    def test_identifies_insecure_tls_protocols(self):
        """TLS config allows SSLv3/TLSv1.0/TLSv1.1."""
        assert any(kw in self.all_text for kw in [
            "sslv3", "ssl v3", "tlsv1.0", "tls 1.0", "tlsv1.1",
            "tls 1.1", "deprecated protocol", "insecure protocol",
            "old protocol", "outdated protocol", "legacy protocol"
        ]), "Report must identify insecure TLS protocols"

    def test_identifies_weak_ciphers_in_tls(self):
        """TLS config uses ALL ciphers including weak ones."""
        assert any(kw in self.all_text for kw in [
            "all cipher", "weak cipher", "insecure cipher",
            "rc4", "des", "null cipher", "cipher suite",
            "cipher selection", "ssl_ciphers all"
        ]), "Report must identify weak ciphers in TLS config"

    def test_identifies_key_reuse(self):
        """Server and client certs share the same private key."""
        assert any(kw in self.all_text for kw in [
            "key reuse", "reuse", "same key", "shared key",
            "identical key", "duplicate key", "common key",
            "key is shared", "key material", "same private key",
            "reused key", "reusing"
        ]), "Report must identify private key reuse between server and client certificates"

    def test_identifies_weak_dh_params(self):
        """DH parameters are only 1024-bit (vulnerable to Logjam)."""
        assert any(kw in self.all_text for kw in [
            "dh", "diffie", "dhparam", "dh param",
            "logjam", "dh parameter", "diffie-hellman",
            "diffie hellman", "dhe parameter"
        ]), "Report must identify weak Diffie-Hellman parameters"

    def test_identifies_path_length_violation(self):
        """Sub-CA signed by intermediate with pathlen:0 — constraint violation."""
        assert any(kw in self.all_text for kw in [
            "pathlen", "path len", "path length", "path constraint",
            "path_len", "pathlength", "path violation",
            "sub-ca", "sub ca", "subordinate",
            "pathlen:0", "pathlen 0", "pathlen=0"
        ]), "Report must identify path length constraint violation (sub-CA signed by pathlen:0 intermediate)"


# ============================================================
# REMEDIATED ROOT CA TESTS
# ============================================================

class TestRemediatedRootCA:
    """Verify the remediated root CA meets security requirements."""

    def test_root_ca_files_exist(self):
        assert os.path.exists("/app/remediated/root-ca.pem"), "root-ca.pem missing"
        assert os.path.exists("/app/remediated/root-ca.key"), "root-ca.key missing"

    def test_root_ca_key_size(self):
        stdout, _, rc = run_openssl(["rsa", "-in", "/app/remediated/root-ca.key", "-text", "-noout"])
        if rc != 0:
            stdout, _, _ = run_openssl(["pkey", "-in", "/app/remediated/root-ca.key", "-text", "-noout"])
        match = re.search(r"(\d+)\s*bit", stdout, re.IGNORECASE)
        assert match, "Could not determine root CA key size"
        key_bits = int(match.group(1))
        assert key_bits >= 4096, f"Root CA key must be >= 4096 bits, got {key_bits}"

    def test_root_ca_is_self_signed(self):
        stdout, _, _ = run_openssl(["x509", "-in", "/app/remediated/root-ca.pem", "-text", "-noout"])
        issuer = re.search(r"Issuer:\s*(.+)", stdout)
        subject = re.search(r"Subject:\s*(.+)", stdout)
        assert issuer and subject, "Could not parse Issuer/Subject"
        assert issuer.group(1).strip() == subject.group(1).strip(), "Root CA must be self-signed"

    def test_root_ca_basic_constraints(self):
        stdout, _, _ = run_openssl(["x509", "-in", "/app/remediated/root-ca.pem", "-text", "-noout"])
        assert "CA:TRUE" in stdout, "Root CA must have basicConstraints CA:TRUE"

    def test_root_ca_key_usage(self):
        stdout, _, _ = run_openssl(["x509", "-in", "/app/remediated/root-ca.pem", "-text", "-noout"])
        assert "Certificate Sign" in stdout, "Root CA must have Certificate Sign key usage"
        assert "CRL Sign" in stdout, "Root CA must have CRL Sign key usage"

    def test_root_ca_signature_algorithm(self):
        stdout, _, _ = run_openssl(["x509", "-in", "/app/remediated/root-ca.pem", "-text", "-noout"])
        sig_match = re.search(r"Signature Algorithm:\s*(\S+)", stdout)
        assert sig_match, "Could not find signature algorithm"
        alg = sig_match.group(1).lower()
        assert "sha1" not in alg and "md5" not in alg, \
            f"Root CA must not use weak signature algorithm, got {alg}"


# ============================================================
# REMEDIATED INTERMEDIATE CA TESTS
# ============================================================

class TestRemediatedIntermediateCA:
    """Verify the remediated intermediate CA meets security requirements."""

    def test_intermediate_ca_files_exist(self):
        assert os.path.exists("/app/remediated/intermediate-ca.pem")
        assert os.path.exists("/app/remediated/intermediate-ca.key")

    def test_intermediate_signed_by_root(self):
        _, _, rc = run_openssl([
            "verify", "-CAfile", "/app/remediated/root-ca.pem",
            "/app/remediated/intermediate-ca.pem"
        ])
        assert rc == 0, "Intermediate CA must be verifiable against root CA"

    def test_intermediate_uses_sha256_or_better(self):
        stdout, _, _ = run_openssl(["x509", "-in", "/app/remediated/intermediate-ca.pem", "-text", "-noout"])
        sig_match = re.search(r"Signature Algorithm:\s*(\S+)", stdout)
        assert sig_match, "Could not find signature algorithm"
        alg = sig_match.group(1).lower()
        assert any(h in alg for h in ["sha256", "sha384", "sha512"]), \
            f"Intermediate CA must use SHA-256 or better, got {alg}"

    def test_intermediate_basic_constraints(self):
        stdout, _, _ = run_openssl(["x509", "-in", "/app/remediated/intermediate-ca.pem", "-text", "-noout"])
        assert "CA:TRUE" in stdout, "Intermediate CA must have CA:TRUE"

    def test_intermediate_key_size(self):
        stdout, _, rc = run_openssl(["rsa", "-in", "/app/remediated/intermediate-ca.key", "-text", "-noout"])
        if rc != 0:
            stdout, _, _ = run_openssl(["pkey", "-in", "/app/remediated/intermediate-ca.key", "-text", "-noout"])
        match = re.search(r"(\d+)\s*bit", stdout, re.IGNORECASE)
        assert match, "Could not determine intermediate CA key size"
        key_bits = int(match.group(1))
        assert key_bits >= 2048, f"Intermediate CA key must be >= 2048 bits, got {key_bits}"

    def test_intermediate_key_usage(self):
        stdout, _, _ = run_openssl(["x509", "-in", "/app/remediated/intermediate-ca.pem", "-text", "-noout"])
        assert "Certificate Sign" in stdout, "Intermediate CA must have Certificate Sign key usage"


# ============================================================
# REMEDIATED SERVER CERTIFICATE TESTS
# ============================================================

class TestRemediatedServerCert:
    """Verify the remediated server certificate meets security requirements."""

    def test_server_cert_files_exist(self):
        assert os.path.exists("/app/remediated/server.pem")
        assert os.path.exists("/app/remediated/server.key")

    def test_server_cert_chain_validates(self):
        _, _, rc = run_openssl([
            "verify",
            "-CAfile", "/app/remediated/root-ca.pem",
            "-untrusted", "/app/remediated/intermediate-ca.pem",
            "/app/remediated/server.pem"
        ])
        assert rc == 0, "Server certificate chain must validate"

    def test_server_cert_not_ca(self):
        stdout, _, _ = run_openssl(["x509", "-in", "/app/remediated/server.pem", "-text", "-noout"])
        assert "CA:TRUE" not in stdout, "Server cert must NOT have CA:TRUE"

    def test_server_cert_has_san(self):
        stdout, _, _ = run_openssl(["x509", "-in", "/app/remediated/server.pem", "-text", "-noout"])
        assert "Subject Alternative Name" in stdout, "Server cert must have SAN extension"
        assert "acmecorp" in stdout.lower(), "Server cert SAN must include acmecorp domain"

    def test_server_cert_key_usage_correct(self):
        stdout, _, _ = run_openssl(["x509", "-in", "/app/remediated/server.pem", "-text", "-noout"])
        assert "Digital Signature" in stdout, "Server cert must have Digital Signature key usage"
        lines = stdout.split('\n')
        for i, line in enumerate(lines):
            if 'X509v3 Key Usage' in line and i + 1 < len(lines):
                ku_line = lines[i + 1].strip()
                assert "Certificate Sign" not in ku_line, \
                    "Server cert must NOT have Certificate Sign key usage"
                break

    def test_server_cert_extended_key_usage(self):
        stdout, _, _ = run_openssl(["x509", "-in", "/app/remediated/server.pem", "-text", "-noout"])
        assert "TLS Web Server Authentication" in stdout, \
            "Server cert must have serverAuth extended key usage"

    def test_server_cert_signature_algorithm(self):
        stdout, _, _ = run_openssl(["x509", "-in", "/app/remediated/server.pem", "-text", "-noout"])
        sig_match = re.search(r"Signature Algorithm:\s*(\S+)", stdout)
        assert sig_match, "Could not find signature algorithm"
        alg = sig_match.group(1).lower()
        assert "sha1" not in alg and "md5" not in alg, \
            f"Server cert must not use weak signature algorithm, got {alg}"


# ============================================================
# REMEDIATED CLIENT CERTIFICATE TESTS
# ============================================================

class TestRemediatedClientCert:
    """Verify the remediated client certificate meets security requirements."""

    def test_client_cert_files_exist(self):
        assert os.path.exists("/app/remediated/client.pem")
        assert os.path.exists("/app/remediated/client.key")

    def test_client_cert_chain_validates(self):
        _, _, rc = run_openssl([
            "verify",
            "-CAfile", "/app/remediated/root-ca.pem",
            "-untrusted", "/app/remediated/intermediate-ca.pem",
            "/app/remediated/client.pem"
        ])
        assert rc == 0, "Client certificate chain must validate"

    def test_client_cert_not_ca(self):
        stdout, _, _ = run_openssl(["x509", "-in", "/app/remediated/client.pem", "-text", "-noout"])
        assert "CA:TRUE" not in stdout, "Client cert must NOT have CA:TRUE"

    def test_client_cert_key_usage(self):
        stdout, _, _ = run_openssl(["x509", "-in", "/app/remediated/client.pem", "-text", "-noout"])
        assert "Digital Signature" in stdout, "Client cert must have Digital Signature key usage"

    def test_client_cert_extended_key_usage_correct(self):
        stdout, _, _ = run_openssl(["x509", "-in", "/app/remediated/client.pem", "-text", "-noout"])
        assert "TLS Web Client Authentication" in stdout, \
            "Client cert must have clientAuth extended key usage"
        assert "TLS Web Server Authentication" not in stdout, \
            "Client cert must NOT have serverAuth extended key usage"

    def test_no_key_reuse_between_server_and_client(self):
        """Remediated server and client must use distinct private keys."""
        server_out, _, _ = run_openssl(["pkey", "-in", "/app/remediated/server.key", "-pubout"])
        client_out, _, _ = run_openssl(["pkey", "-in", "/app/remediated/client.key", "-pubout"])
        assert server_out != client_out, \
            "Remediated server and client must NOT share the same private key"


# ============================================================
# CHAIN FILE TESTS
# ============================================================

class TestChainFile:
    """Verify the full certificate chain file."""

    def test_chain_file_exists(self):
        assert os.path.exists("/app/remediated/chain.pem"), "chain.pem must exist"

    def test_chain_contains_multiple_certs(self):
        with open("/app/remediated/chain.pem") as f:
            content = f.read()
        cert_count = content.count("BEGIN CERTIFICATE")
        assert cert_count >= 3, \
            f"Chain file must contain at least 3 certificates, found {cert_count}"

    def test_chain_enables_verification(self):
        """Server cert must be verifiable using the chain."""
        _, _, rc = run_openssl([
            "verify", "-CAfile", "/app/remediated/chain.pem",
            "/app/remediated/server.pem"
        ])
        if rc != 0:
            _, _, rc = run_openssl([
                "verify",
                "-CAfile", "/app/remediated/root-ca.pem",
                "-untrusted", "/app/remediated/chain.pem",
                "/app/remediated/server.pem"
            ])
        assert rc == 0, "Server cert must be verifiable using chain.pem"


# ============================================================
# TLS CONFIGURATION TESTS
# ============================================================

class TestTLSConfig:
    """Verify the hardened TLS configuration."""

    @pytest.fixture(autouse=True)
    def load_config(self):
        path = "/app/remediated/tls.conf"
        assert os.path.exists(path), "tls.conf must exist at /app/remediated/"
        with open(path) as f:
            self.config = f.read()
        self.config_lower = self.config.lower()

    def test_no_sslv3(self):
        """Must not allow SSLv3."""
        proto = re.search(r'(?:ssl_protocols?|sslprotocol)\s+([^;]+)', self.config_lower)
        if proto:
            assert "sslv3" not in proto.group(1), "TLS config must not allow SSLv3"

    def test_no_old_tls(self):
        """Must not allow TLSv1.0 or TLSv1.1."""
        proto = re.search(r'(?:ssl_protocols?|sslprotocol)\s+([^;]+)', self.config_lower)
        if proto:
            protocols = proto.group(1)
            assert not re.search(r'tlsv1(?!\.[23])', protocols), \
                "TLS config must not allow TLSv1.0 or TLSv1.1"

    def test_modern_protocols_enabled(self):
        """Must enable TLSv1.2 or TLSv1.3."""
        assert "tlsv1.2" in self.config_lower or "tls1.2" in self.config_lower or \
               "tlsv1.3" in self.config_lower or "tls1.3" in self.config_lower, \
            "TLS config must enable TLSv1.2 or TLSv1.3"

    def test_pfs_cipher_suites(self):
        """Must use PFS cipher suites (ECDHE/DHE)."""
        assert any(kw in self.config_lower for kw in [
            "ecdhe", "dhe", "eecdh", "edh", "chacha",
            "tls_aes", "tls13", "forward secrecy"
        ]), "TLS config must use PFS cipher suites (ECDHE/DHE)"

    def test_no_all_ciphers(self):
        """Must not use ALL as cipher selector."""
        cipher = re.search(r'(?:ssl_ciphers?|sslciphersuite)\s+["\']?([^;"\']+)', self.config_lower)
        if cipher:
            ciphers_val = cipher.group(1).strip()
            assert not re.match(r'^all\b', ciphers_val), \
                "TLS config must not use 'ALL' cipher selector"

    def test_ocsp_stapling_enabled(self):
        """Must have OCSP stapling configuration."""
        assert "stapling" in self.config_lower or "ocsp" in self.config_lower, \
            "TLS config must include OCSP stapling configuration"


# ============================================================
# OCSP SETUP TESTS
# ============================================================

class TestOCSPSetup:
    """Verify the OCSP responder setup script."""

    def test_ocsp_script_exists(self):
        assert os.path.exists("/app/remediated/ocsp_setup.sh"), \
            "ocsp_setup.sh must exist"

    def test_ocsp_script_executable(self):
        assert os.access("/app/remediated/ocsp_setup.sh", os.X_OK), \
            "ocsp_setup.sh must be executable"

    def test_ocsp_script_uses_openssl(self):
        with open("/app/remediated/ocsp_setup.sh") as f:
            content = f.read().lower()
        assert "openssl" in content, "OCSP setup script must use openssl"
        assert "ocsp" in content, "OCSP setup script must reference OCSP"
