#!/usr/bin/env python3
"""
Full PKI security audit solution.

1. Load all certificates and extract RSA moduli
2. Batch pairwise GCD to find shared-prime-factor vulnerabilities
3. Fermat factoring to find close-primes vulnerabilities
4. Multi-hop decryption: outer RSA -> relay AES-GCM unwrap -> inner RSA -> payload AES-GCM
5. Write vulnerability assessment report
6. Generate remediated replacement certificates
"""

import datetime
import json
import math
import os
from math import isqrt

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import (
    RSAPrivateNumbers,
    RSAPublicNumbers,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import NameOID

CERT_DIR = "/app/pki_audit/certificates"
INCIDENT_DIR = "/app/pki_audit/incident"


# ──────────────────────────────────────────────────────────────────────
# Certificate loading
# ──────────────────────────────────────────────────────────────────────

def load_certificates():
    """Load all PEM certificates and extract RSA public-key material."""
    certs = {}
    for fname in sorted(os.listdir(CERT_DIR)):
        if not fname.endswith(".pem"):
            continue
        path = os.path.join(CERT_DIR, fname)
        with open(path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        pub = cert.public_key().public_numbers()
        fp = cert.fingerprint(hashes.SHA256()).hex()
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        certs[fname] = {
            "cert": cert, "n": pub.n, "e": pub.e, "fp": fp, "cn": cn,
        }
        print(f"  Loaded {fname}: CN={cn}, {pub.n.bit_length()}-bit modulus")
    return certs


# ──────────────────────────────────────────────────────────────────────
# Attack: Batch GCD for shared prime factors
# ──────────────────────────────────────────────────────────────────────

def find_shared_primes(certs):
    """Compute pairwise GCDs to discover shared prime factors."""
    names = list(certs.keys())
    shared = {}  # name -> [(peer_name, shared_prime), ...]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            g = math.gcd(certs[names[i]]["n"], certs[names[j]]["n"])
            if 1 < g < certs[names[i]]["n"]:
                print(f"  SHARED PRIME: {names[i]} <-> {names[j]}")
                shared.setdefault(names[i], []).append((names[j], g))
                shared.setdefault(names[j], []).append((names[i], g))
    return shared


# ──────────────────────────────────────────────────────────────────────
# Attack: Fermat factoring for close primes
# ──────────────────────────────────────────────────────────────────────

def fermat_factor(n, max_iter=1000000):
    """Factor n when its prime factors p, q are close together."""
    a = isqrt(n)
    if a * a < n:
        a += 1
    for _ in range(max_iter):
        b2 = a * a - n
        b = isqrt(b2)
        if b * b == b2:
            p = a + b
            q = a - b
            if p > 1 and q > 1 and p * q == n:
                return p, q
        a += 1
    return None


# ──────────────────────────────────────────────────────────────────────
# RSA key reconstruction
# ──────────────────────────────────────────────────────────────────────

def reconstruct_private_key(p, q, e=65537):
    """Build an RSA private key from two recovered prime factors."""
    if p < q:
        p, q = q, p
    n = p * q
    phi = (p - 1) * (q - 1)
    d = pow(e, -1, phi)
    dp = d % (p - 1)
    dq = d % (q - 1)
    iq = pow(q, -1, p)
    pub = RSAPublicNumbers(e, n)
    priv = RSAPrivateNumbers(
        p=p, q=q, d=d, dmp1=dp, dmq1=dq, iqmp=iq, public_numbers=pub,
    )
    return priv.private_key()


# ──────────────────────────────────────────────────────────────────────
# Main solution
# ──────────────────────────────────────────────────────────────────────

def main():
    # ── Step 1: Load certificates ────────────────────────────────────
    print("[*] Loading certificates...")
    certs = load_certificates()

    # ── Step 2: Read session metadata ────────────────────────────────
    print("\n[*] Reading incident metadata...")
    with open(os.path.join(INCIDENT_DIR, "captured_session.json")) as f:
        session = json.load(f)

    relay_chain = session["relay_chain"]
    outer_fp = relay_chain[0]["server_certificate_sha256_fingerprint"]
    inner_fp = relay_chain[1]["server_certificate_sha256_fingerprint"]

    # Map fingerprints to certificate filenames
    outer_name = inner_name = None
    for name, info in certs.items():
        if info["fp"] == outer_fp:
            outer_name = name
        if info["fp"] == inner_fp:
            inner_name = name
    assert outer_name, "Could not find outer relay certificate by fingerprint"
    assert inner_name, "Could not find inner endpoint certificate by fingerprint"
    print(f"  Outer relay cert  : {outer_name} ({certs[outer_name]['cn']})")
    print(f"  Inner endpoint cert: {inner_name} ({certs[inner_name]['cn']})")

    # ── Step 3: Batch GCD analysis ───────────────────────────────────
    print("\n[*] Performing pairwise GCD analysis...")
    shared = find_shared_primes(certs)

    # Factor GCD-vulnerable keys
    factored = {}  # name -> (p, q)
    vuln_report = {}

    for name, peers in shared.items():
        g = peers[0][1]
        n = certs[name]["n"]
        q = n // g
        assert g * q == n, f"Factorisation check failed for {name}"
        factored[name] = (g, q)
        vuln_report[name] = {
            "vulnerability_type": "shared_prime_factor",
            "severity": "critical",
        }
        print(f"  Factored {name} via GCD")

    # ── Step 4: Fermat factoring on remaining certificates ───────────
    print("\n[*] Attempting Fermat factoring on unfactored certificates...")
    for name, info in certs.items():
        if name in factored:
            continue
        result = fermat_factor(info["n"])
        if result is not None:
            p, q = result
            factored[name] = (p, q)
            vuln_report[name] = {
                "vulnerability_type": "close_primes",
                "severity": "critical",
            }
            print(f"  Factored {name} via Fermat (|p-q| = {abs(p - q)})")
        else:
            vuln_report[name] = {
                "vulnerability_type": "none",
                "severity": "none",
            }
            print(f"  {name}: no weakness found")

    # ── Step 5: Write vulnerability report ───────────────────────────
    print("\n[*] Writing vulnerability report...")
    report = {"certificates": vuln_report}
    with open("/app/vulnerability_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Written to /app/vulnerability_report.json")

    # ── Step 6: Multi-hop decryption ─────────────────────────────────
    print("\n[*] Beginning multi-hop decryption...")
    oaep = asym_padding.OAEP(
        mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None,
    )

    # 6a: Reconstruct outer relay private key and decrypt relay_key
    assert outer_name in factored, f"Cannot factor outer relay cert {outer_name}"
    p, q = factored[outer_name]
    outer_privkey = reconstruct_private_key(p, q, certs[outer_name]["e"])
    print(f"  Reconstructed private key for {outer_name}")

    with open(os.path.join(INCIDENT_DIR, "encrypted_relay_key.bin"), "rb") as f:
        enc_relay_key = f.read()
    relay_key = outer_privkey.decrypt(enc_relay_key, oaep)
    print(f"  Recovered relay key ({len(relay_key) * 8} bits)")

    # 6b: AES-GCM unwrap the inner RSA blob
    relay_wrap = session["relay_wrapping"]
    relay_nonce = bytes.fromhex(relay_wrap["nonce_hex"])
    relay_tag = bytes.fromhex(relay_wrap["tag_hex"])

    with open(os.path.join(INCIDENT_DIR, "encrypted_session_key.bin"), "rb") as f:
        relay_ct = f.read()

    relay_aesgcm = AESGCM(relay_key)
    inner_rsa_blob = relay_aesgcm.decrypt(relay_nonce, relay_ct + relay_tag, None)
    print(f"  Unwrapped inner RSA blob ({len(inner_rsa_blob)} bytes)")

    # 6c: Reconstruct inner endpoint private key and decrypt session_key
    assert inner_name in factored, f"Cannot factor inner endpoint cert {inner_name}"
    p, q = factored[inner_name]
    inner_privkey = reconstruct_private_key(p, q, certs[inner_name]["e"])
    print(f"  Reconstructed private key for {inner_name}")

    session_key = inner_privkey.decrypt(inner_rsa_blob, oaep)
    print(f"  Recovered session key ({len(session_key) * 8} bits)")

    # 6d: AES-GCM decrypt the payload
    payload_enc = session["payload_encryption"]
    payload_nonce = bytes.fromhex(payload_enc["nonce_hex"])
    payload_tag = bytes.fromhex(payload_enc["tag_hex"])

    with open(os.path.join(INCIDENT_DIR, "encrypted_payload.bin"), "rb") as f:
        payload_ct = f.read()

    payload_aesgcm = AESGCM(session_key)
    plaintext = payload_aesgcm.decrypt(payload_nonce, payload_ct + payload_tag, None)

    with open("/app/recovered_plaintext.txt", "wb") as f:
        f.write(plaintext)
    print(f"\n[+] Decrypted payload written to /app/recovered_plaintext.txt")

    # ── Step 7: Generate remediated certificates ─────────────────────
    print("\n[*] Generating remediated certificates...")
    os.makedirs("/app/remediated_certs", exist_ok=True)

    for name, vinfo in vuln_report.items():
        if vinfo["vulnerability_type"] == "none":
            continue

        cn = certs[name]["cn"]
        new_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048,
        )
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Acme Corp"),
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
        ])
        new_cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(new_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime(2024, 6, 1, 0, 0, 0))
            .not_valid_after(datetime.datetime(2026, 6, 1, 0, 0, 0))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(cn)]),
                critical=False,
            )
            .sign(new_key, hashes.SHA256())
        )
        out_path = f"/app/remediated_certs/{name}"
        with open(out_path, "wb") as f:
            f.write(new_cert.public_bytes(serialization.Encoding.PEM))
        print(f"  Generated {name}: CN={cn}, {new_key.key_size}-bit RSA, SHA-256")

    print("\n[+] PKI security audit complete.")


if __name__ == "__main__":
    main()
