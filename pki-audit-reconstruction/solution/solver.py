#!/usr/bin/env python3
"""Solve the PKI audit and reconstruction task.

Analyzes every certificate and CRL in /app/pki/, generates an audit report
at /app/audit.json, then rebuilds a compliant PKI at /app/pki-fixed/.
"""

import datetime
import json
import os

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

UTC = datetime.timezone.utc
PKI_DIR = "/app/pki"
FIXED_DIR = "/app/pki-fixed"
AUDIT_FILE = "/app/audit.json"

BANNED_SIG_OIDS = {
    "1.2.840.113549.1.1.5",  # sha1WithRSAEncryption
    "1.2.840.113549.1.1.4",  # md5WithRSAEncryption
    "1.2.840.113549.1.1.2",  # md2WithRSAEncryption
}


def load_cert(path):
    with open(path, "rb") as f:
        return x509.load_pem_x509_certificate(f.read())


def load_crl(path):
    with open(path, "rb") as f:
        return x509.load_pem_x509_crl(f.read())


def get_validity(cert):
    try:
        return cert.not_valid_before_utc, cert.not_valid_after_utc
    except AttributeError:
        nvb = cert.not_valid_before.replace(tzinfo=UTC)
        nva = cert.not_valid_after.replace(tzinfo=UTC)
        return nvb, nva


# -----------------------------------------------------------------------
# Phase 1: Audit
# -----------------------------------------------------------------------

def audit_pki():
    findings = []
    now = datetime.datetime.now(UTC)

    # Load manifest
    with open(os.path.join(PKI_DIR, "manifest.json")) as f:
        manifest = json.load(f)
    reqs = manifest["compliance_requirements"]

    # --- Root CA ---
    root = load_cert(os.path.join(PKI_DIR, "root-ca.pem"))

    if root.signature_algorithm_oid.dotted_string in BANNED_SIG_OIDS:
        findings.append({
            "certificate": "root-ca.pem",
            "issue": (
                "Root CA uses SHA-1 (sha1WithRSAEncryption) signature algorithm, "
                "which is cryptographically deprecated and vulnerable to collision attacks"
            ),
            "severity": "critical",
            "recommendation": "Re-issue root CA with SHA-256 or stronger signature algorithm",
        })

    # --- Intermediate CA ---
    intermediate = load_cert(os.path.join(PKI_DIR, "intermediate-ca.pem"))
    inter_key_size = intermediate.public_key().key_size

    if inter_key_size < reqs["minimum_rsa_key_bits"]:
        findings.append({
            "certificate": "intermediate-ca.pem",
            "issue": (
                f"Intermediate CA has a 1024-bit RSA key, below the "
                f"{reqs['minimum_rsa_key_bits']}-bit minimum requirement"
            ),
            "severity": "critical",
            "recommendation": (
                "Re-issue intermediate CA with at least "
                f"{reqs['minimum_rsa_key_bits']}-bit RSA key"
            ),
        })

    # --- Path length constraint ---
    inter_bc = intermediate.extensions.get_extension_for_class(
        x509.BasicConstraints
    )
    if inter_bc.value.path_length is not None and inter_bc.value.path_length == 0:
        sub_inter_path = os.path.join(PKI_DIR, "sub-intermediate-ca.pem")
        if os.path.exists(sub_inter_path):
            sub_inter = load_cert(sub_inter_path)
            sub_bc = sub_inter.extensions.get_extension_for_class(
                x509.BasicConstraints
            )
            if sub_bc.value.ca:
                findings.append({
                    "certificate": "sub-intermediate-ca.pem",
                    "issue": (
                        "Sub-intermediate CA violates path length constraint: "
                        "intermediate-ca.pem has pathlen=0 but issued this "
                        "subordinate CA certificate"
                    ),
                    "severity": "critical",
                    "recommendation": (
                        "Remove sub-intermediate tier or increase pathlen "
                        "on intermediate CA"
                    ),
                })

    # --- Server cert: missing SAN ---
    server = load_cert(os.path.join(PKI_DIR, "server.pem"))
    try:
        server.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        findings.append({
            "certificate": "server.pem",
            "issue": (
                "Server certificate lacks Subject Alternative Name (SAN) "
                "extension. Modern TLS clients and CA/Browser Forum Baseline "
                "Requirements mandate SAN for server certificates"
            ),
            "severity": "high",
            "recommendation": (
                "Re-issue with SAN containing all required domain names"
            ),
        })

    # --- Server cert: wrong EKU ---
    try:
        eku = server.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        if ExtendedKeyUsageOID.SERVER_AUTH not in eku.value:
            eku_names = [o.dotted_string for o in eku.value]
            findings.append({
                "certificate": "server.pem",
                "issue": (
                    "Server certificate Extended Key Usage contains clientAuth "
                    "instead of serverAuth — this will cause TLS handshake "
                    f"failures (current EKU OIDs: {eku_names})"
                ),
                "severity": "critical",
                "recommendation": "Re-issue with serverAuth Extended Key Usage",
            })
    except x509.ExtensionNotFound:
        findings.append({
            "certificate": "server.pem",
            "issue": "Server certificate missing Extended Key Usage extension",
            "severity": "high",
            "recommendation": "Add serverAuth EKU",
        })

    # --- Server cert: excessive validity ---
    s_nvb, s_nva = get_validity(server)
    server_validity_days = (s_nva - s_nvb).days
    max_days = reqs["maximum_end_entity_validity_days"]
    if server_validity_days > max_days:
        findings.append({
            "certificate": "server.pem",
            "issue": (
                f"Server certificate has a {server_validity_days}-day "
                f"({server_validity_days // 365}-year) validity period, "
                f"exceeding the {max_days}-day maximum"
            ),
            "severity": "high",
            "recommendation": (
                f"Re-issue with validity period of {max_days} days or less"
            ),
        })

    # --- Client cert: expired ---
    client = load_cert(os.path.join(PKI_DIR, "client.pem"))
    _, c_nva = get_validity(client)
    if c_nva < now:
        findings.append({
            "certificate": "client.pem",
            "issue": (
                f"Client certificate has expired "
                f"(not valid after {c_nva.isoformat()})"
            ),
            "severity": "critical",
            "recommendation": "Re-issue client certificate with valid dates",
        })

    # --- CRL: signed by wrong key ---
    crl_path = os.path.join(PKI_DIR, "intermediate-ca.crl")
    if os.path.exists(crl_path):
        crl = load_crl(crl_path)
        try:
            intermediate.public_key().verify(
                crl.signature,
                crl.tbs_certlist_bytes,
                asym_padding.PKCS1v15(),
                crl.signature_hash_algorithm,
            )
        except (InvalidSignature, Exception):
            findings.append({
                "certificate": "intermediate-ca.crl",
                "issue": (
                    "CRL signature verification fails — the CRL claims to be "
                    "issued by intermediate-ca but is signed by a different "
                    "private key"
                ),
                "severity": "critical",
                "recommendation": (
                    "Regenerate CRL using the intermediate CA's private key"
                ),
            })

    return findings


# -----------------------------------------------------------------------
# Phase 2: Rebuild
# -----------------------------------------------------------------------

def write_cert(name, cert_obj):
    with open(os.path.join(FIXED_DIR, name), "wb") as f:
        f.write(cert_obj.public_bytes(serialization.Encoding.PEM))


def write_key(name, key_obj):
    with open(os.path.join(FIXED_DIR, name), "wb") as f:
        f.write(
            key_obj.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )


def rebuild_pki():
    os.makedirs(FIXED_DIR, exist_ok=True)
    now = datetime.datetime.now(UTC)

    # Load manifest for domain list
    with open(os.path.join(PKI_DIR, "manifest.json")) as f:
        manifest = json.load(f)

    domains = []
    for ee in manifest["hierarchy"]["end_entity"]:
        if "expected_domains" in ee:
            domains = ee["expected_domains"]
            break

    # --- Root CA: 4096-bit, SHA-256, 20-year validity ---
    root_key = rsa.generate_private_key(65537, 4096)
    root_name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ExampleCorp"),
        x509.NameAttribute(NameOID.COMMON_NAME, "ExampleCorp Root CA"),
    ])
    root_cert = (
        x509.CertificateBuilder()
        .subject_name(root_name)
        .issuer_name(root_name)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=7300))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()),
            critical=False,
        )
        .sign(root_key, hashes.SHA256())
    )

    # --- Intermediate CA: 4096-bit, SHA-256, 10-year validity, pathlen=0 ---
    inter_key = rsa.generate_private_key(65537, 4096)
    inter_name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ExampleCorp"),
        x509.NameAttribute(NameOID.COMMON_NAME, "ExampleCorp Intermediate CA"),
    ])
    inter_cert = (
        x509.CertificateBuilder()
        .subject_name(inter_name)
        .issuer_name(root_name)
        .public_key(inter_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=0), critical=True
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(inter_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                root_key.public_key()
            ),
            critical=False,
        )
        .sign(root_key, hashes.SHA256())
    )

    # --- Server cert: 2048-bit, SHA-256, SAN, serverAuth, <=365 days ---
    server_key = rsa.generate_private_key(65537, 2048)
    server_name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ExampleCorp"),
        x509.NameAttribute(NameOID.COMMON_NAME, domains[0] if domains else "server.examplecorp.com"),
    ])
    san_entries = [x509.DNSName(d) for d in domains] if domains else [
        x509.DNSName("server.examplecorp.com"),
    ]
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(inter_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName(san_entries), critical=False
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=True,
                content_commitment=False, key_cert_sign=False,
                crl_sign=False, data_encipherment=False,
                key_agreement=False, encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                inter_key.public_key()
            ),
            critical=False,
        )
        .sign(inter_key, hashes.SHA256())
    )

    # --- Client cert: 2048-bit, SHA-256, clientAuth, <=365 days ---
    client_key = rsa.generate_private_key(65537, 2048)
    client_name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ExampleCorp"),
        x509.NameAttribute(NameOID.COMMON_NAME, "admin@examplecorp.com"),
    ])
    client_cert = (
        x509.CertificateBuilder()
        .subject_name(client_name)
        .issuer_name(inter_name)
        .public_key(client_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.RFC822Name("admin@examplecorp.com")]
            ),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=False,
                content_commitment=True, key_cert_sign=False,
                crl_sign=False, data_encipherment=False,
                key_agreement=False, encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                inter_key.public_key()
            ),
            critical=False,
        )
        .sign(inter_key, hashes.SHA256())
    )

    # --- Write everything ---
    write_cert("root-ca.pem", root_cert)
    write_key("root-ca.key", root_key)
    write_cert("intermediate-ca.pem", inter_cert)
    write_key("intermediate-ca.key", inter_key)
    write_cert("server.pem", server_cert)
    write_key("server.key", server_key)
    write_cert("client.pem", client_cert)
    write_key("client.key", client_key)

    print(f"Fixed PKI written to {FIXED_DIR}")


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Phase 1: Auditing PKI ===")
    findings = audit_pki()
    with open(AUDIT_FILE, "w") as f:
        json.dump({"findings": findings}, f, indent=2, default=str)
    print(f"Audit complete: {len(findings)} findings -> {AUDIT_FILE}")

    print("\n=== Phase 2: Rebuilding PKI ===")
    rebuild_pki()

    # Quick verification
    import subprocess
    root_path = os.path.join(FIXED_DIR, "root-ca.pem")
    inter_path = os.path.join(FIXED_DIR, "intermediate-ca.pem")
    for ee in ("server.pem", "client.pem"):
        result = subprocess.run(
            ["openssl", "verify", "-CAfile", root_path,
             "-untrusted", inter_path,
             os.path.join(FIXED_DIR, ee)],
            capture_output=True, text=True,
        )
        status = "OK" if result.returncode == 0 else "FAIL"
        print(f"  Chain validation for {ee}: {status}")
        if result.returncode != 0:
            print(f"    {result.stderr.strip()}")
