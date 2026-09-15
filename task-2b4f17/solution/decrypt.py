#!/usr/bin/env python3
"""
Solve the FWPK firmware crypto assessment and hardening.

Phase 1 -- Cryptanalysis:
  1. Parse the proprietary FWPK binary container format.
  2. Extract the RSA-1024 public key and analyse the modulus.
  3. Factor n via Fermat's method (close primes).
  4. Reconstruct the RSA private key (including CRT parameters).
  5. RSA-decrypt the wrapped key material (masked session key).
  6. Unmask the session key: XOR with SHA-256 of the RSA public key DER.
  7. Decompress the embedded key-management module to learn IV derivation.
  8. Decrypt three AES-256-CBC partitions using HMAC-derived IVs.
  9. Reassemble plaintext and extract the auth token.

Phase 2 -- Hardened Re-encryption:
  10. Derive a new AES-256 key from the recovered data's SHA-256 hash.
  11. Re-encrypt data with AES-256-GCM and RSA-OAEP key wrapping.
  12. Build a new FWPK container with hardened cryptography.
"""

import binascii
import gzip
import hashlib
import hmac as hmac_mod
import json
import math
import struct

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding as asym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend


# ============================================================
# FWPK Binary Format
# ============================================================

FWPK_MAGIC = b"FWPK"
FWPK_VERSION = 0x0102
SEC_ENTRY_SZ = 32


def parse_fwpk(data: bytes) -> dict:
    """Parse FWPK header and section table, return {name: section_info}."""
    magic = data[:4]
    assert magic == FWPK_MAGIC, f"Bad magic: {magic}"

    version, num_sections = struct.unpack_from("<HH", data, 4)

    sections = {}
    for i in range(num_sections):
        base = 12 + i * SEC_ENTRY_SZ
        raw_name = data[base:base + 16]
        name = raw_name.rstrip(b"\x00").decode("ascii")
        offset, size, flags = struct.unpack_from("<III", data, base + 16)
        sections[name] = {
            "offset": offset,
            "size": size,
            "flags": flags,
            "data": data[offset:offset + size],
        }
    return sections


def mk_section_entry(name, offset, size, flags):
    """Build a 32-byte section table entry."""
    name_b = name.encode("ascii")[:16].ljust(16, b"\x00")
    return struct.pack("<16sIIII", name_b, offset, size, flags, 0)


def build_fwpk(sections):
    """Build FWPK container from [(name, data, flags), ...]."""
    num = len(sections)
    hdr_sz = 12 + num * SEC_ENTRY_SZ

    entries = []
    cur = hdr_sz
    for name, data, flags in sections:
        entries.append((name, cur, len(data), flags))
        cur += len(data)

    table = b""
    for name, off, sz, fl in entries:
        table += mk_section_entry(name, off, sz, fl)

    pre = struct.pack("<4sHH", FWPK_MAGIC, FWPK_VERSION, num)
    crc = binascii.crc32(pre + table) & 0xFFFFFFFF
    hdr = pre + struct.pack("<I", crc)

    blob = hdr + table
    for _, data, _ in sections:
        blob += data
    return blob


# ============================================================
# Fermat factorisation
# ============================================================

def fermat_factor(n: int) -> tuple:
    """Factor n assuming p ~ q (close primes)."""
    a = math.isqrt(n)
    if a * a < n:
        a += 1
    while True:
        b_sq = a * a - n
        b = math.isqrt(b_sq)
        if b * b == b_sq:
            p, q = a + b, a - b
            assert p * q == n
            return p, q
        a += 1


# ============================================================
# RSA private-key reconstruction
# ============================================================

def build_rsa_privkey(n, e, p, q):
    """Construct an RSA private key from factors."""
    if p < q:
        p, q = q, p
    phi = (p - 1) * (q - 1)
    d = pow(e, -1, phi)
    dp = d % (p - 1)
    dq = d % (q - 1)
    qi = pow(q, -1, p)
    pub = rsa.RSAPublicNumbers(e, n)
    priv = rsa.RSAPrivateNumbers(p, q, d, dp, dq, qi, pub)
    return priv.private_key(default_backend())


# ============================================================
# Phase 2: Hardened firmware creation
# ============================================================

def create_hardened_firmware(diagnostic_data: bytes) -> bytes:
    """Build a FWPK container with hardened cryptography."""
    # Load RSA-2048 public key
    with open("/app/hardened_pubkey.pem", "rb") as f:
        hardened_pub = serialization.load_pem_public_key(f.read())

    # Derive AES-256 session key deterministically from diagnostic data hash
    diag_hash = hashlib.sha256(diagnostic_data).hexdigest()
    aes_key = hashlib.sha256(
        ("hardened-session-key-" + diag_hash).encode()
    ).digest()

    # Wrap AES key with RSA-OAEP SHA-256 (no masking -- OAEP is secure)
    wrapped_key = hardened_pub.encrypt(
        aes_key,
        asym_padding.OAEP(
            mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    # RSA-2048 public key in DER format for embedding
    pubkey_der = hardened_pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    # Split data into 3 partitions (same boundaries as original)
    part_sz = len(diagnostic_data) // 3
    parts = [
        diagnostic_data[:part_sz],
        diagnostic_data[part_sz:2 * part_sz],
        diagnostic_data[2 * part_sz:],
    ]

    # Encrypt with AES-256-GCM
    aesgcm = AESGCM(aes_key)
    enc_parts = []
    for i, pt in enumerate(parts):
        nonce = hashlib.sha256(f"gcm-nonce-{i}".encode()).digest()[:12]
        ct_tag = aesgcm.encrypt(nonce, pt, None)  # returns ciphertext || tag
        enc_parts.append(nonce + ct_tag)

    # Manifest reflecting hardened crypto
    manifest = json.dumps({
        "firmware_id": "IVI-ECU-R7-4.8.2-HARDENED",
        "build_date": "2024-11-01T00:00:00Z",
        "target": "IVI-ECU-R7-C3",
        "crypto": {
            "key_wrap": "RSA-OAEP-SHA256",
            "data_cipher": "AES-256-GCM",
            "nonce_method": "SHA256-derived",
            "key_derivation": "SHA256-deterministic",
        },
        "partitions": ["partition_0", "partition_1", "partition_2"],
    }, indent=2).encode("utf-8")

    # Build hardened FWPK container
    # flags: 0x00=plain, 0x02=encrypted, 0x06=encrypted+authenticated
    sections = [
        ("manifest",       manifest,       0x00),
        ("rsa_pubkey",     pubkey_der,     0x00),
        ("wrapped_aeskey", wrapped_key,    0x02),
        ("partition_0",    enc_parts[0],   0x06),
        ("partition_1",    enc_parts[1],   0x06),
        ("partition_2",    enc_parts[2],   0x06),
    ]

    return build_fwpk(sections)


# ============================================================
# Main
# ============================================================

def main():
    # ===================== Phase 1: Cryptanalysis =====================

    with open("/app/firmware.bin", "rb") as f:
        fw = f.read()

    sections = parse_fwpk(fw)
    print(f"Parsed FWPK: {list(sections.keys())}")

    # --- Extract RSA public key ---
    pubkey_der = sections["rsa_pubkey"]["data"]
    pubkey = serialization.load_der_public_key(pubkey_der)
    pub_numbers = pubkey.public_numbers()
    n = pub_numbers.n
    e = pub_numbers.e
    print(f"RSA modulus: {n.bit_length()} bits, e={e}")

    # --- Factor modulus ---
    p, q = fermat_factor(n)
    print(f"Factored: p has {p.bit_length()} bits, q has {q.bit_length()} bits")
    print(f"|p-q| = {abs(p - q)}")

    # --- Reconstruct private key ---
    privkey = build_rsa_privkey(n, e, p, q)

    # Write PEM
    pem = privkey.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with open("/app/rsa_private.pem", "wb") as f:
        f.write(pem)
    print("Wrote /app/rsa_private.pem")

    # --- Unwrap and unmask AES session key ---
    masked_key = privkey.decrypt(
        sections["wrapped_aeskey"]["data"],
        asym_padding.PKCS1v15(),
    )
    # The session key is XOR-masked with SHA-256(pubkey_der) before wrapping.
    # Reverse the masking to recover the actual AES key.
    key_mask = hashlib.sha256(pubkey_der).digest()
    aes_key = bytes(a ^ b for a, b in zip(masked_key, key_mask))
    print(f"AES session key recovered: {len(aes_key)} bytes")

    # --- Read key-management module for IV derivation scheme ---
    keymgmt_src = gzip.decompress(sections["key_mgmt"]["data"]).decode("utf-8")
    # Confirms: IV = HMAC-SHA256(key, pack('>I', partition_index))[:16]

    # --- Decrypt partitions ---
    plaintext_parts = []
    for i in range(3):
        name = f"partition_{i}"
        ct = sections[name]["data"]

        iv = hmac_mod.new(
            aes_key, struct.pack(">I", i), hashlib.sha256
        ).digest()[:16]

        dec = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
        padded = dec.update(ct) + dec.finalize()

        # Strip PKCS#7 padding
        pad_len = padded[-1]
        plaintext_parts.append(padded[:-pad_len])

    full_plaintext = b"".join(plaintext_parts)
    print(f"Recovered {len(full_plaintext)} bytes of diagnostic data")

    # --- Write recovered data ---
    with open("/app/recovered_data.txt", "wb") as f:
        f.write(full_plaintext)

    # --- Extract auth token ---
    text = full_plaintext.decode("utf-8")
    for line in text.split("\n"):
        if "Auth Token:" in line:
            token = line.split("Auth Token:")[1].strip()
            with open("/app/security_token.txt", "w", newline="") as f:
                f.write(token)
            print(f"Token: {token}")
            break

    # ===================== Phase 2: Hardened Re-encryption =====================

    print("\n--- Phase 2: Building hardened firmware ---")
    hardened = create_hardened_firmware(full_plaintext)
    with open("/app/hardened_firmware.bin", "wb") as f:
        f.write(hardened)
    print(f"Wrote /app/hardened_firmware.bin ({len(hardened)} bytes)")

    print("Done.")


if __name__ == "__main__":
    main()
