#!/usr/bin/env python3
"""Generate a broken PKI hierarchy with 8 deliberate security/compliance violations.

This script creates the starting state for the PKI audit task.
It is removed after execution during Docker build to prevent answer leakage.
"""

import datetime
import json
import os
import subprocess
import tempfile
import warnings

warnings.filterwarnings("ignore")

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

UTC = datetime.timezone.utc
OUTPUT_DIR = "/app/pki"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def write_pem(path, obj, is_key=False):
    with open(path, "wb") as f:
        if is_key:
            f.write(
                obj.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.TraditionalOpenSSL,
                    serialization.NoEncryption(),
                )
            )
        else:
            f.write(obj.public_bytes(serialization.Encoding.PEM))


def load_cert_from_file(path):
    with open(path, "rb") as f:
        return x509.load_pem_x509_certificate(f.read())


def write_ext_file(content):
    """Write extension config to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".cnf")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


# ========================= ROOT CA =========================
# ISSUE 1: Uses SHA-1 signature algorithm
# The Python cryptography library blocks SHA-1 signing, so we use openssl CLI.

root_key = rsa.generate_private_key(65537, 4096)
root_key_path = os.path.join(OUTPUT_DIR, "root-ca.key")
write_pem(root_key_path, root_key, is_key=True)

root_cnf_path = write_ext_file("""\
[req]
distinguished_name = req_dn
x509_extensions = v3_ca
prompt = no

[req_dn]
C = US
O = ExampleCorp
CN = ExampleCorp Root CA

[v3_ca]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign, digitalSignature
subjectKeyIdentifier = hash
""")

root_cert_path = os.path.join(OUTPUT_DIR, "root-ca.pem")
result = subprocess.run(
    [
        "openssl", "req", "-new", "-x509", "-sha1",
        "-key", root_key_path,
        "-out", root_cert_path,
        "-days", "7305",
        "-config", root_cnf_path,
    ],
    capture_output=True, text=True,
)
if result.returncode != 0:
    raise RuntimeError(f"Failed to generate SHA-1 root CA: {result.stderr}")
os.unlink(root_cnf_path)

root_cert = load_cert_from_file(root_cert_path)
root_name = root_cert.subject


# ========================= INTERMEDIATE CA =========================
# ISSUE 2: 1024-bit RSA key (too weak)
# The cert itself is signed by root_key (4096-bit, SHA-256) -- no library issue.
intermediate_key = rsa.generate_private_key(65537, 1024)
intermediate_name = x509.Name(
    [
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ExampleCorp"),
        x509.NameAttribute(NameOID.COMMON_NAME, "ExampleCorp Server CA"),
    ]
)
intermediate_cert = (
    x509.CertificateBuilder()
    .subject_name(intermediate_name)
    .issuer_name(root_name)
    .public_key(intermediate_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime(2020, 1, 1, tzinfo=UTC))
    .not_valid_after(datetime.datetime(2035, 1, 1, tzinfo=UTC))
    .add_extension(
        x509.BasicConstraints(ca=True, path_length=0), critical=True
    )
    .add_extension(
        x509.KeyUsage(
            digital_signature=True,
            key_cert_sign=True,
            crl_sign=True,
            content_commitment=False,
            key_encipherment=False,
            data_encipherment=False,
            key_agreement=False,
            encipher_only=False,
            decipher_only=False,
        ),
        critical=True,
    )
    .add_extension(
        x509.SubjectKeyIdentifier.from_public_key(intermediate_key.public_key()),
        critical=False,
    )
    .add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
        critical=False,
    )
    .sign(root_key, hashes.SHA256())
)

inter_cert_path = os.path.join(OUTPUT_DIR, "intermediate-ca.pem")
inter_key_path = os.path.join(OUTPUT_DIR, "intermediate-ca.key")
write_pem(inter_cert_path, intermediate_cert)
write_pem(inter_key_path, intermediate_key, is_key=True)


# ========================= SUB-INTERMEDIATE CA =========================
# ISSUE 3: Violates path length constraint (intermediate has pathlen=0
#           but issued this subordinate CA).
# Use openssl CLI for signing because the 1024-bit intermediate key may
# be rejected by newer cryptography library versions.

sub_intermediate_key = rsa.generate_private_key(65537, 2048)
sub_inter_key_path = os.path.join(OUTPUT_DIR, "sub-intermediate-ca.key")
write_pem(sub_inter_key_path, sub_intermediate_key, is_key=True)

sub_inter_csr_path = "/tmp/sub-inter.csr"
subprocess.run(
    [
        "openssl", "req", "-new",
        "-key", sub_inter_key_path,
        "-out", sub_inter_csr_path,
        "-subj", "/C=US/O=ExampleCorp/CN=ExampleCorp Web Services CA",
    ],
    check=True, capture_output=True,
)

sub_inter_ext_path = write_ext_file("""\
[v3_sub_ca]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign, digitalSignature
subjectKeyIdentifier = hash
""")

sub_inter_cert_path = os.path.join(OUTPUT_DIR, "sub-intermediate-ca.pem")
result = subprocess.run(
    [
        "openssl", "x509", "-req",
        "-in", sub_inter_csr_path,
        "-CA", inter_cert_path,
        "-CAkey", inter_key_path,
        "-out", sub_inter_cert_path,
        "-sha256", "-days", "3650",
        "-CAcreateserial",
        "-extfile", sub_inter_ext_path,
        "-extensions", "v3_sub_ca",
    ],
    capture_output=True, text=True,
)
if result.returncode != 0:
    raise RuntimeError(f"Failed to sign sub-intermediate CA: {result.stderr}")

os.unlink(sub_inter_csr_path)
os.unlink(sub_inter_ext_path)

sub_intermediate_cert = load_cert_from_file(sub_inter_cert_path)
sub_intermediate_name = sub_intermediate_cert.subject


# ========================= SERVER CERTIFICATE =========================
# ISSUE 4: Missing SAN extension
# ISSUE 5: Wrong EKU (clientAuth instead of serverAuth)
# ISSUE 6: 20-year validity period
server_key = rsa.generate_private_key(65537, 2048)
server_name = x509.Name(
    [
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ExampleCorp"),
        x509.NameAttribute(NameOID.COMMON_NAME, "server.examplecorp.com"),
    ]
)
server_cert = (
    x509.CertificateBuilder()
    .subject_name(server_name)
    .issuer_name(sub_intermediate_name)
    .public_key(server_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime(2021, 6, 1, tzinfo=UTC))
    .not_valid_after(datetime.datetime(2041, 6, 1, tzinfo=UTC))  # ISSUE 6
    .add_extension(
        x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),  # ISSUE 5
        critical=False,
    )
    # NO SAN extension -- ISSUE 4
    .add_extension(
        x509.KeyUsage(
            digital_signature=True,
            key_encipherment=True,
            content_commitment=False,
            key_cert_sign=False,
            crl_sign=False,
            data_encipherment=False,
            key_agreement=False,
            encipher_only=False,
            decipher_only=False,
        ),
        critical=True,
    )
    .add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(
            sub_intermediate_key.public_key()
        ),
        critical=False,
    )
    .sign(sub_intermediate_key, hashes.SHA256())
)

write_pem(os.path.join(OUTPUT_DIR, "server.pem"), server_cert)
write_pem(os.path.join(OUTPUT_DIR, "server.key"), server_key, is_key=True)


# ========================= CLIENT CA =========================
client_ca_key = rsa.generate_private_key(65537, 2048)
client_ca_name = x509.Name(
    [
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ExampleCorp"),
        x509.NameAttribute(NameOID.COMMON_NAME, "ExampleCorp Client CA"),
    ]
)
client_ca_cert = (
    x509.CertificateBuilder()
    .subject_name(client_ca_name)
    .issuer_name(root_name)
    .public_key(client_ca_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime(2020, 1, 1, tzinfo=UTC))
    .not_valid_after(datetime.datetime(2035, 1, 1, tzinfo=UTC))
    .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
    .add_extension(
        x509.KeyUsage(
            digital_signature=True,
            key_cert_sign=True,
            crl_sign=True,
            content_commitment=False,
            key_encipherment=False,
            data_encipherment=False,
            key_agreement=False,
            encipher_only=False,
            decipher_only=False,
        ),
        critical=True,
    )
    .add_extension(
        x509.SubjectKeyIdentifier.from_public_key(client_ca_key.public_key()),
        critical=False,
    )
    .add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
        critical=False,
    )
    .sign(root_key, hashes.SHA256())
)

write_pem(os.path.join(OUTPUT_DIR, "client-ca.pem"), client_ca_cert)
write_pem(os.path.join(OUTPUT_DIR, "client-ca.key"), client_ca_key, is_key=True)


# ========================= CLIENT CERTIFICATE =========================
# ISSUE 7: Expired (valid until 2023-01-01)
client_key = rsa.generate_private_key(65537, 2048)
client_name = x509.Name(
    [
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ExampleCorp"),
        x509.NameAttribute(NameOID.COMMON_NAME, "admin@examplecorp.com"),
    ]
)
client_cert = (
    x509.CertificateBuilder()
    .subject_name(client_name)
    .issuer_name(client_ca_name)
    .public_key(client_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime(2022, 1, 1, tzinfo=UTC))
    .not_valid_after(datetime.datetime(2023, 1, 1, tzinfo=UTC))  # ISSUE 7
    .add_extension(
        x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False
    )
    .add_extension(
        x509.SubjectAlternativeName([x509.RFC822Name("admin@examplecorp.com")]),
        critical=False,
    )
    .add_extension(
        x509.KeyUsage(
            digital_signature=True,
            key_encipherment=False,
            content_commitment=True,
            key_cert_sign=False,
            crl_sign=False,
            data_encipherment=False,
            key_agreement=False,
            encipher_only=False,
            decipher_only=False,
        ),
        critical=True,
    )
    .add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(
            client_ca_key.public_key()
        ),
        critical=False,
    )
    .sign(client_ca_key, hashes.SHA256())
)

write_pem(os.path.join(OUTPUT_DIR, "client.pem"), client_cert)
write_pem(os.path.join(OUTPUT_DIR, "client.key"), client_key, is_key=True)


# ========================= CRL =========================
# ISSUE 8: Signed by a different key than the issuing CA
crl_wrong_key = rsa.generate_private_key(65537, 2048)
crl = (
    x509.CertificateRevocationListBuilder()
    .issuer_name(intermediate_name)
    .last_update(datetime.datetime(2023, 1, 1, tzinfo=UTC))
    .next_update(datetime.datetime(2025, 1, 1, tzinfo=UTC))
    .sign(crl_wrong_key, hashes.SHA256())  # Wrong key!
)

write_pem(os.path.join(OUTPUT_DIR, "intermediate-ca.crl"), crl)


# ========================= CHAIN FILE =========================
with open(os.path.join(OUTPUT_DIR, "server-chain.pem"), "wb") as f:
    f.write(server_cert.public_bytes(serialization.Encoding.PEM))
    f.write(sub_intermediate_cert.public_bytes(serialization.Encoding.PEM))
    f.write(intermediate_cert.public_bytes(serialization.Encoding.PEM))


# ========================= MANIFEST =========================
manifest = {
    "organization": "ExampleCorp",
    "description": "Enterprise PKI for ExampleCorp internal and external services",
    "hierarchy": {
        "root_ca": {
            "file": "root-ca.pem",
            "purpose": "Trust anchor for all ExampleCorp certificates",
        },
        "intermediate_cas": [
            {
                "file": "intermediate-ca.pem",
                "parent": "root-ca.pem",
                "purpose": "Issues server-side certificates",
            },
            {
                "file": "sub-intermediate-ca.pem",
                "parent": "intermediate-ca.pem",
                "purpose": "Issues web service endpoint certificates",
            },
            {
                "file": "client-ca.pem",
                "parent": "root-ca.pem",
                "purpose": "Issues client authentication certificates",
            },
        ],
        "end_entity": [
            {
                "file": "server.pem",
                "issuer": "sub-intermediate-ca.pem",
                "purpose": "TLS server certificate for examplecorp.com services",
                "expected_domains": [
                    "server.examplecorp.com",
                    "www.examplecorp.com",
                    "api.examplecorp.com",
                ],
            },
            {
                "file": "client.pem",
                "issuer": "client-ca.pem",
                "purpose": "mTLS client certificate for admin@examplecorp.com",
            },
        ],
        "crl": {"file": "intermediate-ca.crl", "issuer": "intermediate-ca.pem"},
    },
    "compliance_requirements": {
        "minimum_rsa_key_bits": 2048,
        "minimum_root_ca_key_bits": 4096,
        "maximum_end_entity_validity_days": 825,
        "required_signature_algorithms": [
            "sha256WithRSAEncryption",
            "sha384WithRSAEncryption",
            "sha512WithRSAEncryption",
            "ecdsa-with-SHA256",
            "ecdsa-with-SHA384",
        ],
        "prohibited_signature_algorithms": [
            "sha1WithRSAEncryption",
            "md5WithRSAEncryption",
        ],
        "server_certificates_require_san": True,
        "server_certificates_require_server_auth_eku": True,
        "client_certificates_require_client_auth_eku": True,
        "enforce_path_length_constraints": True,
        "crl_must_be_signed_by_issuing_ca": True,
    },
}

with open(os.path.join(OUTPUT_DIR, "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)

print("Broken PKI hierarchy generated at", OUTPUT_DIR)
