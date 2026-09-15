#!/usr/bin/env python3
"""
Generate PKI audit challenge materials.
Creates X.509 certificates with multiple classes of RSA key weakness:
- Shared prime factors (GCD-vulnerable pairs)
- Close primes (Fermat-factorable)
- Secure keys (no weakness)

Encrypts incident data using a multi-hop relay scheme:
  relay_key encrypted with RSA-OAEP (outer server)
  session_key encrypted with RSA-OAEP (inner server), then wrapped with AES-GCM(relay_key)
  payload encrypted with AES-256-GCM(session_key)

Multi-stage Docker build ensures this script and all private keys are absent
from the final image.
"""

import json
import hashlib
import os
import sys
import random
import datetime
from cryptography.hazmat.primitives.asymmetric import rsa, padding as asym_padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateNumbers, RSAPublicNumbers
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography import x509
from cryptography.x509.oid import NameOID


def is_probable_prime(n, k=40):
    """Miller-Rabin primality test with k rounds."""
    if n < 2:
        return False
    if n == 2 or n == 3:
        return True
    if n % 2 == 0:
        return False
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2
    for _ in range(k):
        a = random.randrange(2, n - 1)
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def next_prime_after(n):
    """Find the smallest prime strictly greater than n."""
    candidate = n + 1 if n % 2 == 0 else n + 2
    while not is_probable_prime(candidate):
        candidate += 2
    return candidate


def make_rsa_key(p, q, e=65537):
    """Construct an RSA private key from two prime factors."""
    if p < q:
        p, q = q, p
    n = p * q
    phi = (p - 1) * (q - 1)
    d = pow(e, -1, phi)
    dp = d % (p - 1)
    dq = d % (q - 1)
    iq = pow(q, -1, p)
    pub_numbers = RSAPublicNumbers(e, n)
    priv_numbers = RSAPrivateNumbers(
        p=p, q=q, d=d, dmp1=dp, dmq1=dq, iqmp=iq,
        public_numbers=pub_numbers
    )
    return priv_numbers.private_key()


def make_certificate(priv_key, cn, org_unit):
    """Create a self-signed X.509 certificate."""
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Acme Corp"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, org_unit),
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(priv_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime(2024, 1, 15, 0, 0, 0))
        .not_valid_after(datetime.datetime(2026, 1, 15, 0, 0, 0))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(cn)]),
            critical=False,
        )
        .sign(priv_key, hashes.SHA256())
    )
    return cert


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <output_dir>")
        sys.exit(1)

    output_dir = sys.argv[1]

    # ------------------------------------------------------------------
    # Step 1: Generate RSA-2048 keys to harvest distinct 1024-bit primes
    # ------------------------------------------------------------------
    print("[*] Generating RSA-2048 keys to harvest primes...")
    all_primes = []
    for _ in range(7):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pn = key.private_numbers()
        all_primes.append(pn.p)
        all_primes.append(pn.q)
    # 14 primes harvested; we use 12 for normal/GCD certs + 1 as base for Fermat

    assert len(set(all_primes)) == 14, "Prime collision (astronomically unlikely)"

    # ------------------------------------------------------------------
    # Step 2: Generate close primes for Fermat-vulnerable certificate
    # The next prime after an existing prime is very close, making n = p*q
    # trivially factorable via Fermat's method.
    # ------------------------------------------------------------------
    print("[*] Generating close primes for Fermat-vulnerable key...")
    fermat_p = all_primes[12]
    fermat_q = next_prime_after(fermat_p)
    gap = abs(fermat_p - fermat_q)
    print(f"    Fermat prime gap: {gap}")

    # ------------------------------------------------------------------
    # Step 3: Assign primes to 8 server certificates
    #
    # GCD-vulnerable pairs (shared prime factor):
    #   api-gateway       <-> mail-relay       share all_primes[2]
    #   database-primary  <-> monitoring       share all_primes[4]
    #
    # Fermat-vulnerable (close primes):
    #   vpn-gateway
    #
    # Clean (no weakness):
    #   webserver-prod, backup-server, log-aggregator
    #
    # Multi-hop encryption targets:
    #   OUTER relay: database-primary (GCD-vulnerable)
    #   INNER endpoint: vpn-gateway (Fermat-vulnerable)
    # ------------------------------------------------------------------

    server_configs = [
        {"name": "webserver-prod",   "cn": "webserver-prod.acmecorp.internal",   "ou": "Web Services",     "p": all_primes[0],  "q": all_primes[1]},
        {"name": "api-gateway",      "cn": "api-gateway.acmecorp.internal",      "ou": "API Services",     "p": all_primes[2],  "q": all_primes[3]},
        {"name": "database-primary", "cn": "database-primary.acmecorp.internal", "ou": "Data Services",    "p": all_primes[4],  "q": all_primes[5]},
        {"name": "mail-relay",       "cn": "mail-relay.acmecorp.internal",       "ou": "Mail Services",    "p": all_primes[2],  "q": all_primes[6]},
        {"name": "monitoring",       "cn": "monitoring.acmecorp.internal",       "ou": "Operations",       "p": all_primes[4],  "q": all_primes[7]},
        {"name": "vpn-gateway",      "cn": "vpn-gateway.acmecorp.internal",      "ou": "Network Services", "p": fermat_p,       "q": fermat_q},
        {"name": "backup-server",    "cn": "backup-server.acmecorp.internal",    "ou": "Backup Services",  "p": all_primes[8],  "q": all_primes[9]},
        {"name": "log-aggregator",   "cn": "log-aggregator.acmecorp.internal",   "ou": "Logging Services", "p": all_primes[10], "q": all_primes[11]},
    ]

    OUTER_IDX = 2  # database-primary
    INNER_IDX = 5  # vpn-gateway

    # ------------------------------------------------------------------
    # Step 4: Build RSA keys and X.509 certificates
    # ------------------------------------------------------------------
    print("[*] Building certificates...")
    keys = []
    certs = []
    for cfg in server_configs:
        priv_key = make_rsa_key(cfg["p"], cfg["q"])
        cert = make_certificate(priv_key, cfg["cn"], cfg["ou"])
        keys.append(priv_key)
        certs.append(cert)
        n_bits = priv_key.public_key().public_numbers().n.bit_length()
        print(f"    {cfg['name']:20s}  {n_bits}-bit modulus")

    # ------------------------------------------------------------------
    # Step 5: Create output directories
    # ------------------------------------------------------------------
    cert_dir = os.path.join(output_dir, "pki_audit", "certificates")
    incident_dir = os.path.join(output_dir, "pki_audit", "incident")
    os.makedirs(cert_dir, exist_ok=True)
    os.makedirs(incident_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 6: Write certificates (public material only)
    # ------------------------------------------------------------------
    for cfg, cert in zip(server_configs, certs):
        path = os.path.join(cert_dir, f"{cfg['name']}.pem")
        with open(path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

    # ------------------------------------------------------------------
    # Step 7: Multi-hop encrypted exfiltration data
    #
    # The attacker relayed through two compromised servers:
    #   Attacker -> database-primary (outer) -> vpn-gateway (inner) -> C2
    #
    # Encryption scheme:
    #   1. session_key (32 bytes) encrypted with vpn-gateway's RSA pubkey (inner layer)
    #   2. That 256-byte RSA blob wrapped with AES-256-GCM using relay_key
    #   3. relay_key (32 bytes) encrypted with database-primary's RSA pubkey (outer layer)
    #   4. Actual payload encrypted with AES-256-GCM using session_key
    # ------------------------------------------------------------------
    print("[*] Building multi-hop encrypted payload...")
    outer_pub = keys[OUTER_IDX].public_key()
    inner_pub = keys[INNER_IDX].public_key()
    outer_cert = certs[OUTER_IDX]
    inner_cert = certs[INNER_IDX]

    plaintext = json.dumps({
        "exfil_manifest": {
            "campaign_id": "APT-2024-WHISPERGATE",
            "operator": "THREAT_ACTOR_COBALT",
            "targets": ["financial_records", "employee_pii", "source_code"],
            "exfil_volume_gb": 47.3,
            "c2_domains": [
                "update-service.example.com",
                "cdn-static.example.net",
                "api-telemetry.example.org"
            ],
            "encryption_key_id": "op-key-7f3a9b2e",
            "canary_token": "d8f4a2e1-9b3c-4f7d-a5e8-6c2b1d0f3e9a"
        }
    }, indent=2).encode("utf-8")

    oaep_padding = asym_padding.OAEP(
        mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None,
    )

    # Generate cryptographic material
    session_key = os.urandom(32)
    relay_key = os.urandom(32)
    relay_nonce = os.urandom(12)
    payload_nonce = os.urandom(12)

    # Inner layer: RSA-OAEP encrypt session_key with vpn-gateway's pubkey
    inner_rsa_blob = inner_pub.encrypt(session_key, oaep_padding)

    # Relay wrapping: AES-256-GCM encrypt inner RSA blob with relay_key
    relay_aesgcm = AESGCM(relay_key)
    relay_ct_with_tag = relay_aesgcm.encrypt(relay_nonce, inner_rsa_blob, None)
    relay_ciphertext = relay_ct_with_tag[:-16]
    relay_tag = relay_ct_with_tag[-16:]

    # Outer layer: RSA-OAEP encrypt relay_key with database-primary's pubkey
    outer_rsa_blob = outer_pub.encrypt(relay_key, oaep_padding)

    # Payload: AES-256-GCM encrypt data with session_key
    payload_aesgcm = AESGCM(session_key)
    payload_ct_with_tag = payload_aesgcm.encrypt(payload_nonce, plaintext, None)
    payload_ciphertext = payload_ct_with_tag[:-16]
    payload_tag = payload_ct_with_tag[-16:]

    # Write encrypted blobs
    with open(os.path.join(incident_dir, "encrypted_relay_key.bin"), "wb") as f:
        f.write(outer_rsa_blob)
    with open(os.path.join(incident_dir, "encrypted_session_key.bin"), "wb") as f:
        f.write(relay_ciphertext)
    with open(os.path.join(incident_dir, "encrypted_payload.bin"), "wb") as f:
        f.write(payload_ciphertext)

    # Write session metadata
    outer_fp = outer_cert.fingerprint(hashes.SHA256()).hex()
    inner_fp = inner_cert.fingerprint(hashes.SHA256()).hex()

    session_meta = {
        "timestamp": "2024-03-15T02:47:33Z",
        "source_ip": "10.0.5.23",
        "destination_ip": "10.0.1.100",
        "relay_chain": [
            {
                "hop": 1,
                "role": "outer_relay",
                "server_certificate_sha256_fingerprint": outer_fp,
                "key_transport": "RSA-OAEP-SHA256",
                "note": "Encrypts a 32-byte relay key used to wrap the inner layer"
            },
            {
                "hop": 2,
                "role": "inner_endpoint",
                "server_certificate_sha256_fingerprint": inner_fp,
                "key_transport": "RSA-OAEP-SHA256",
                "note": "Encrypts the 32-byte AES session key for payload decryption"
            }
        ],
        "relay_wrapping": {
            "description": "Inner RSA-OAEP blob wrapped with AES-256-GCM using the relay key",
            "cipher": "AES-256-GCM",
            "nonce_hex": relay_nonce.hex(),
            "tag_hex": relay_tag.hex(),
            "wrapped_file": "encrypted_session_key.bin"
        },
        "payload_encryption": {
            "cipher": "AES-256-GCM",
            "nonce_hex": payload_nonce.hex(),
            "tag_hex": payload_tag.hex()
        },
        "analyst_notes": (
            "Multi-hop encrypted exfiltration intercepted. Traffic was relayed "
            "through two internal servers before reaching external C2 infrastructure. "
            "The session key was nested inside two encryption layers. The outer relay "
            "server's certificate was used to encrypt a relay key, which in turn "
            "protects the inner RSA-encrypted session key. Reverse the layers in "
            "order: outer RSA first to obtain relay key, then AES unwrap to get "
            "inner RSA blob, then inner RSA to recover session key, finally "
            "AES-GCM decrypt the payload."
        )
    }
    with open(os.path.join(incident_dir, "captured_session.json"), "w") as f:
        json.dump(session_meta, f, indent=2)

    # ------------------------------------------------------------------
    # Step 8: Write verification hash (SHA-256 of plaintext)
    # ------------------------------------------------------------------
    verification_hash = hashlib.sha256(plaintext).hexdigest()
    with open(os.path.join(output_dir, "pki_audit", ".verification"), "w") as f:
        f.write(verification_hash)

    # ------------------------------------------------------------------
    # Step 9: Write scenario README
    # ------------------------------------------------------------------
    readme = (
        "INCIDENT RESPONSE - PKI INFRASTRUCTURE AUDIT\n"
        "=============================================\n"
        "\n"
        "CLASSIFICATION: CONFIDENTIAL\n"
        "\n"
        "BACKGROUND:\n"
        "On 2024-03-15, the Security Operations Center detected anomalous encrypted\n"
        "traffic leaving the corporate network via a multi-hop relay through internal\n"
        "servers. Network forensics captured the encrypted session data before the\n"
        "connection was terminated.\n"
        "\n"
        "Analysis indicates the threat actor compromised two internal servers to\n"
        "establish a multi-layer encrypted relay for data exfiltration. The session\n"
        "key was protected by nested encryption using certificates from servers in\n"
        "the relay chain.\n"
        "\n"
        "AVAILABLE EVIDENCE:\n"
        "  certificates/                       TLS certificates for all internal servers\n"
        "  incident/captured_session.json      Relay chain metadata and encryption parameters\n"
        "  incident/encrypted_relay_key.bin    Outer-layer encrypted relay key (RSA-OAEP)\n"
        "  incident/encrypted_session_key.bin  AES-GCM wrapped inner RSA blob\n"
        "  incident/encrypted_payload.bin      Encrypted exfiltration payload (AES-256-GCM)\n"
        "\n"
        "PRIOR AUDIT FINDINGS:\n"
        "The certificate generation tool was developed in-house and used a custom\n"
        "random number generator for RSA key generation. All eight server certificates\n"
        "were generated in a single batch session. Quality assurance flagged two\n"
        "distinct categories of entropy concern before the tool was decommissioned:\n"
        "\n"
        "  1. The PRNG state was not properly reseeded between some key generation\n"
        "     operations, potentially causing entropy overlap across multiple keys.\n"
        "\n"
        "  2. At least one key generation used a PRNG state with severely collapsed\n"
        "     internal entropy, potentially producing prime factors with anomalous\n"
        "     proximity characteristics.\n"
        "\n"
        "Neither issue was fully investigated before deployment. The number of\n"
        "affected certificates is unknown. Some certificates may be unaffected.\n"
    )
    with open(os.path.join(output_dir, "pki_audit", "README.txt"), "w") as f:
        f.write(readme)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n[+] Challenge generated in {output_dir}/pki_audit/")
    print(f"    Outer relay     : {server_configs[OUTER_IDX]['name']} (GCD-vulnerable)")
    print(f"    Inner endpoint  : {server_configs[INNER_IDX]['name']} (Fermat-vulnerable)")
    print(f"    Outer SHA-256   : {outer_fp}")
    print(f"    Inner SHA-256   : {inner_fp}")
    print(f"    Verification    : {verification_hash}")
    print(f"    GCD pairs       : api-gateway/mail-relay, database-primary/monitoring")
    print(f"    Fermat-factorable: vpn-gateway (gap={gap})")
    print(f"    Clean           : webserver-prod, backup-server, log-aggregator")


if __name__ == "__main__":
    main()
