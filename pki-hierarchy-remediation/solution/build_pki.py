#!/usr/bin/env python3
"""Build a properly configured enterprise PKI hierarchy at /app/pki-remediated/."""

import os
import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID, ExtensionOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

BASE = "/app/pki-remediated"
OLD_PKI = "/app/pki"

now = datetime.datetime.now(datetime.timezone.utc)


def write_pem(obj, path, kind="cert"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        if kind == "key":
            f.write(obj.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))
        elif kind == "cert":
            f.write(obj.public_bytes(serialization.Encoding.PEM))
        elif kind == "crl":
            f.write(obj.public_bytes(serialization.Encoding.PEM))


def read_pem(path):
    with open(path, "rb") as f:
        return f.read()


# ====================================================================
# 1. Root CA — ECDSA P-384, SHA-384
# ====================================================================
root_key = ec.generate_private_key(ec.SECP384R1())
root_name = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, "Acme Root CA v2"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Acme Corp"),
    x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
])
root_cert = (
    x509.CertificateBuilder()
    .subject_name(root_name)
    .issuer_name(root_name)
    .public_key(root_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now)
    .not_valid_after(now + datetime.timedelta(days=7300))
    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    .add_extension(x509.KeyUsage(
        digital_signature=False, content_commitment=False,
        key_encipherment=False, data_encipherment=False,
        key_agreement=False, key_cert_sign=True, crl_sign=True,
        encipher_only=False, decipher_only=False,
    ), critical=True)
    .add_extension(
        x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()),
        critical=False,
    )
    .sign(root_key, hashes.SHA384())
)
write_pem(root_key, f"{BASE}/root/root-ca.key", "key")
write_pem(root_cert, f"{BASE}/root/root-ca.crt")

# ====================================================================
# 2. TLS Intermediate CA — ECDSA P-256, pathlen:0, nameConstraints
# ====================================================================
tls_key = ec.generate_private_key(ec.SECP256R1())
tls_name = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, "Acme TLS Intermediate CA"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Acme Corp"),
    x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
])
tls_cert = (
    x509.CertificateBuilder()
    .subject_name(tls_name)
    .issuer_name(root_name)
    .public_key(tls_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now)
    .not_valid_after(now + datetime.timedelta(days=3650))
    .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
    .add_extension(x509.KeyUsage(
        digital_signature=False, content_commitment=False,
        key_encipherment=False, data_encipherment=False,
        key_agreement=False, key_cert_sign=True, crl_sign=True,
        encipher_only=False, decipher_only=False,
    ), critical=True)
    .add_extension(x509.NameConstraints(
        permitted_subtrees=[
            x509.DNSName(".example.com"),
            x509.DNSName(".example.org"),
        ],
        excluded_subtrees=None,
    ), critical=True)
    .add_extension(
        x509.SubjectKeyIdentifier.from_public_key(tls_key.public_key()),
        critical=False,
    )
    .add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
        critical=False,
    )
    .add_extension(x509.AuthorityInformationAccess([
        x509.AccessDescription(
            x509.oid.AuthorityInformationAccessOID.OCSP,
            x509.UniformResourceIdentifier("http://ocsp.acme-corp.example.com"),
        ),
    ]), critical=False)
    .add_extension(x509.CRLDistributionPoints([
        x509.DistributionPoint(
            full_name=[x509.UniformResourceIdentifier(
                "http://crl.acme-corp.example.com/root-ca.crl"
            )],
            relative_name=None, crl_issuer=None, reasons=None,
        ),
    ]), critical=False)
    .sign(root_key, hashes.SHA256())
)
write_pem(tls_key, f"{BASE}/tls-intermediate/tls-intermediate.key", "key")
write_pem(tls_cert, f"{BASE}/tls-intermediate/tls-intermediate.crt")

# ====================================================================
# 3. Code Signing Intermediate CA — ECDSA P-256, pathlen:0
# ====================================================================
cs_key = ec.generate_private_key(ec.SECP256R1())
cs_name = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, "Acme Code Signing CA"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Acme Corp"),
    x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
])
cs_cert = (
    x509.CertificateBuilder()
    .subject_name(cs_name)
    .issuer_name(root_name)
    .public_key(cs_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now)
    .not_valid_after(now + datetime.timedelta(days=3650))
    .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
    .add_extension(x509.KeyUsage(
        digital_signature=False, content_commitment=False,
        key_encipherment=False, data_encipherment=False,
        key_agreement=False, key_cert_sign=True, crl_sign=True,
        encipher_only=False, decipher_only=False,
    ), critical=True)
    .add_extension(
        x509.SubjectKeyIdentifier.from_public_key(cs_key.public_key()),
        critical=False,
    )
    .add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
        critical=False,
    )
    .add_extension(x509.CRLDistributionPoints([
        x509.DistributionPoint(
            full_name=[x509.UniformResourceIdentifier(
                "http://crl.acme-corp.example.com/root-ca.crl"
            )],
            relative_name=None, crl_issuer=None, reasons=None,
        ),
    ]), critical=False)
    .sign(root_key, hashes.SHA256())
)
write_pem(cs_key, f"{BASE}/cs-intermediate/cs-intermediate.key", "key")
write_pem(cs_cert, f"{BASE}/cs-intermediate/cs-intermediate.crt")

# ====================================================================
# 4. Server TLS Certificate — ECDSA P-256, SAN, proper extensions
# ====================================================================
srv_key = ec.generate_private_key(ec.SECP256R1())
srv_name = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, "www.example.com"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Acme Corp"),
])
srv_cert = (
    x509.CertificateBuilder()
    .subject_name(srv_name)
    .issuer_name(tls_name)
    .public_key(srv_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now)
    .not_valid_after(now + datetime.timedelta(days=365))
    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    .add_extension(x509.KeyUsage(
        digital_signature=True, content_commitment=False,
        key_encipherment=False, data_encipherment=False,
        key_agreement=False, key_cert_sign=False, crl_sign=False,
        encipher_only=False, decipher_only=False,
    ), critical=True)
    .add_extension(
        x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
        critical=False,
    )
    .add_extension(x509.SubjectAlternativeName([
        x509.DNSName("www.example.com"),
        x509.DNSName("api.example.com"),
        x509.DNSName("mail.example.com"),
    ]), critical=False)
    .add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(tls_key.public_key()),
        critical=False,
    )
    .add_extension(x509.AuthorityInformationAccess([
        x509.AccessDescription(
            x509.oid.AuthorityInformationAccessOID.OCSP,
            x509.UniformResourceIdentifier("http://ocsp.acme-corp.example.com/tls"),
        ),
    ]), critical=False)
    .add_extension(x509.CRLDistributionPoints([
        x509.DistributionPoint(
            full_name=[x509.UniformResourceIdentifier(
                "http://crl.acme-corp.example.com/tls-intermediate.crl"
            )],
            relative_name=None, crl_issuer=None, reasons=None,
        ),
    ]), critical=False)
    .sign(tls_key, hashes.SHA256())
)
write_pem(srv_key, f"{BASE}/certs/server.key", "key")
write_pem(srv_cert, f"{BASE}/certs/server.crt")

# ====================================================================
# 5. Code Signing Certificate — codeSigning EKU only
# ====================================================================
csign_key = ec.generate_private_key(ec.SECP256R1())
csign_name = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, "Acme Code Signing"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Acme Corp"),
])
csign_cert = (
    x509.CertificateBuilder()
    .subject_name(csign_name)
    .issuer_name(cs_name)
    .public_key(csign_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now)
    .not_valid_after(now + datetime.timedelta(days=1095))
    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    .add_extension(x509.KeyUsage(
        digital_signature=True, content_commitment=False,
        key_encipherment=False, data_encipherment=False,
        key_agreement=False, key_cert_sign=False, crl_sign=False,
        encipher_only=False, decipher_only=False,
    ), critical=True)
    .add_extension(
        x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]),
        critical=True,
    )
    .add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(cs_key.public_key()),
        critical=False,
    )
    .sign(cs_key, hashes.SHA256())
)
write_pem(csign_key, f"{BASE}/certs/codesign.key", "key")
write_pem(csign_cert, f"{BASE}/certs/codesign.crt")

# ====================================================================
# 6. Client Authentication Certificate — clientAuth, email SAN
# ====================================================================
cli_key = ec.generate_private_key(ec.SECP256R1())
cli_name = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, "Alice Engineer"),
    x509.NameAttribute(NameOID.EMAIL_ADDRESS, "alice@example.com"),
])
cli_cert = (
    x509.CertificateBuilder()
    .subject_name(cli_name)
    .issuer_name(tls_name)
    .public_key(cli_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now)
    .not_valid_after(now + datetime.timedelta(days=365))
    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    .add_extension(x509.KeyUsage(
        digital_signature=True, content_commitment=False,
        key_encipherment=False, data_encipherment=False,
        key_agreement=False, key_cert_sign=False, crl_sign=False,
        encipher_only=False, decipher_only=False,
    ), critical=True)
    .add_extension(
        x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
        critical=False,
    )
    .add_extension(x509.SubjectAlternativeName([
        x509.RFC822Name("alice@example.com"),
    ]), critical=False)
    .add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(tls_key.public_key()),
        critical=False,
    )
    .add_extension(x509.CRLDistributionPoints([
        x509.DistributionPoint(
            full_name=[x509.UniformResourceIdentifier(
                "http://crl.acme-corp.example.com/tls-intermediate.crl"
            )],
            relative_name=None, crl_issuer=None, reasons=None,
        ),
    ]), critical=False)
    .sign(tls_key, hashes.SHA256())
)
write_pem(cli_key, f"{BASE}/certs/client.key", "key")
write_pem(cli_cert, f"{BASE}/certs/client.crt")

# ====================================================================
# 7. OCSP Signing Certificate — OCSPSigning EKU + noCheck
# ====================================================================
ocsp_key = ec.generate_private_key(ec.SECP256R1())
ocsp_name = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, "Acme TLS OCSP Responder"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Acme Corp"),
])
ocsp_cert = (
    x509.CertificateBuilder()
    .subject_name(ocsp_name)
    .issuer_name(tls_name)
    .public_key(ocsp_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now)
    .not_valid_after(now + datetime.timedelta(days=365))
    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    .add_extension(x509.KeyUsage(
        digital_signature=True, content_commitment=False,
        key_encipherment=False, data_encipherment=False,
        key_agreement=False, key_cert_sign=False, crl_sign=False,
        encipher_only=False, decipher_only=False,
    ), critical=True)
    .add_extension(
        x509.ExtendedKeyUsage([ExtendedKeyUsageOID.OCSP_SIGNING]),
        critical=True,
    )
    .add_extension(x509.OCSPNoCheck(), critical=False)
    .add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(tls_key.public_key()),
        critical=False,
    )
    .sign(tls_key, hashes.SHA256())
)
write_pem(ocsp_key, f"{BASE}/tls-intermediate/ocsp-signing.key", "key")
write_pem(ocsp_cert, f"{BASE}/tls-intermediate/ocsp-signing.crt")

# ====================================================================
# 8. CRLs — one per CA tier
# ====================================================================
root_crl = (
    x509.CertificateRevocationListBuilder()
    .issuer_name(root_name)
    .last_update(now)
    .next_update(now + datetime.timedelta(days=30))
    .sign(root_key, hashes.SHA384())
)
write_pem(root_crl, f"{BASE}/root/root-ca.crl", "crl")

tls_crl = (
    x509.CertificateRevocationListBuilder()
    .issuer_name(tls_name)
    .last_update(now)
    .next_update(now + datetime.timedelta(days=7))
    .sign(tls_key, hashes.SHA256())
)
write_pem(tls_crl, f"{BASE}/tls-intermediate/tls-intermediate.crl", "crl")

cs_crl = (
    x509.CertificateRevocationListBuilder()
    .issuer_name(cs_name)
    .last_update(now)
    .next_update(now + datetime.timedelta(days=7))
    .sign(cs_key, hashes.SHA256())
)
write_pem(cs_crl, f"{BASE}/cs-intermediate/cs-intermediate.crl", "crl")

# ====================================================================
# 9. Cross-certification — old root signs new root public key
# ====================================================================
old_root_key = serialization.load_pem_private_key(
    read_pem(f"{OLD_PKI}/root-ca.key"), password=None,
)
old_root_cert = x509.load_pem_x509_certificate(read_pem(f"{OLD_PKI}/root-ca.crt"))

cross_cert = (
    x509.CertificateBuilder()
    .subject_name(root_cert.subject)
    .issuer_name(old_root_cert.subject)
    .public_key(root_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now)
    .not_valid_after(now + datetime.timedelta(days=1825))
    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    .add_extension(x509.KeyUsage(
        digital_signature=False, content_commitment=False,
        key_encipherment=False, data_encipherment=False,
        key_agreement=False, key_cert_sign=True, crl_sign=True,
        encipher_only=False, decipher_only=False,
    ), critical=True)
    .add_extension(
        x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()),
        critical=False,
    )
    .add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(old_root_key.public_key()),
        critical=False,
    )
    .sign(old_root_key, hashes.SHA256())
)
write_pem(cross_cert, f"{BASE}/cross-cert/cross-cert.crt")

# ====================================================================
# 10. Full chain bundles
# ====================================================================
# server-fullchain: leaf + tls-intermediate + root
with open(f"{BASE}/certs/server-fullchain.pem", "wb") as f:
    f.write(read_pem(f"{BASE}/certs/server.crt"))
    f.write(read_pem(f"{BASE}/tls-intermediate/tls-intermediate.crt"))
    f.write(read_pem(f"{BASE}/root/root-ca.crt"))

# codesign-fullchain: leaf + cs-intermediate + root
with open(f"{BASE}/certs/codesign-fullchain.pem", "wb") as f:
    f.write(read_pem(f"{BASE}/certs/codesign.crt"))
    f.write(read_pem(f"{BASE}/cs-intermediate/cs-intermediate.crt"))
    f.write(read_pem(f"{BASE}/root/root-ca.crt"))

# client-fullchain: leaf + tls-intermediate + root
with open(f"{BASE}/certs/client-fullchain.pem", "wb") as f:
    f.write(read_pem(f"{BASE}/certs/client.crt"))
    f.write(read_pem(f"{BASE}/tls-intermediate/tls-intermediate.crt"))
    f.write(read_pem(f"{BASE}/root/root-ca.crt"))

print("Remediated PKI hierarchy built successfully at", BASE)
