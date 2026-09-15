#!/usr/bin/env python3
"""
Generate a TUF repository with two RSA signing keys, each with different
cryptographic weaknesses:
  - Key T (root/targets/snapshot): consecutive primes (Fermat-factorable)
  - Key S (timestamp): shares a prime factor with Key T (GCD-vulnerable)

Public keys use different PEM formats:
  - Key T: SubjectPublicKeyInfo PEM (BEGIN PUBLIC KEY)
  - Key S: PKCS#1 RSAPublicKey PEM (BEGIN RSA PUBLIC KEY)
"""

import json
import hashlib
import os
import sys
import math
import base64

# ---------- Primality testing ----------

SMALL_PRIMES = [
    2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47,
    53, 59, 61, 67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113,
    127, 131, 137, 139, 149, 151, 157, 163, 167, 173, 179, 181, 191,
    193, 197, 199, 211, 223, 227, 229, 233, 239, 241, 251
]


def is_prime(n):
    """Deterministic Miller-Rabin primality test."""
    if n < 2:
        return False
    for p in SMALL_PRIMES:
        if n == p:
            return True
        if n % p == 0:
            return False
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2
    for a in [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]:
        if a >= n:
            continue
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


def next_prime(n):
    if n <= 2:
        return 2
    if n % 2 == 0:
        n += 1
    while not is_prime(n):
        n += 2
    return n


# ---------- RSA key generation ----------

def generate_key_T():
    """Key T: consecutive primes -> Fermat-factorable."""
    start = (1 << 511) + (1 << 255) + (1 << 127) + 999983
    p = next_prime(start)
    q = next_prime(p + 2)
    e = 65537
    n = p * q
    phi = (p - 1) * (q - 1)
    d = pow(e, -1, phi)
    return n, e, d, p, q


def generate_key_S(shared_prime):
    """Key S: shares shared_prime with Key T -> GCD-vulnerable."""
    start = (1 << 511) + (1 << 400) + (1 << 300) + 1234567
    r = next_prime(start)
    e = 65537
    n = shared_prime * r
    phi = (shared_prime - 1) * (r - 1)
    d = pow(e, -1, phi)
    return n, e, d, shared_prime, r


# ---------- DER / PEM encoding ----------

def int_to_bytes_unsigned(n):
    if n == 0:
        return b'\x00'
    length = (n.bit_length() + 7) // 8
    return n.to_bytes(length, 'big')


def encode_der_length(length):
    if length < 0x80:
        return bytes([length])
    elif length < 0x100:
        return b'\x81' + bytes([length])
    elif length < 0x10000:
        return b'\x82' + length.to_bytes(2, 'big')
    else:
        return b'\x83' + length.to_bytes(3, 'big')


def encode_der_integer(value):
    b = int_to_bytes_unsigned(value)
    if b[0] & 0x80:
        b = b'\x00' + b
    return b'\x02' + encode_der_length(len(b)) + b


def encode_der_sequence(contents):
    return b'\x30' + encode_der_length(len(contents)) + contents


def encode_der_bitstring(contents):
    return b'\x03' + encode_der_length(len(contents) + 1) + b'\x00' + contents


def rsa_spki_der(n, e):
    """SubjectPublicKeyInfo DER (BEGIN PUBLIC KEY)."""
    rsa_key = encode_der_sequence(encode_der_integer(n) + encode_der_integer(e))
    oid_rsa = b'\x06\x09\x2a\x86\x48\x86\xf7\x0d\x01\x01\x01'
    alg_id = encode_der_sequence(oid_rsa + b'\x05\x00')
    return encode_der_sequence(alg_id + encode_der_bitstring(rsa_key))


def rsa_pkcs1_pubkey_der(n, e):
    """PKCS#1 RSAPublicKey DER (BEGIN RSA PUBLIC KEY)."""
    return encode_der_sequence(encode_der_integer(n) + encode_der_integer(e))


def to_pem(der_bytes, label):
    b64 = base64.b64encode(der_bytes).decode('ascii')
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    return '-----BEGIN ' + label + '-----\n' + '\n'.join(lines) + '\n-----END ' + label + '-----'


# ---------- TUF utilities ----------

def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':')).encode('utf-8')


def sha256_hex(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def rsa_sign_pkcs1v15_sha256(message, n, d):
    h = hashlib.sha256(message).digest()
    digest_info = (
        b'\x30\x31\x30\x0d\x06\x09\x60\x86\x48\x01'
        b'\x65\x03\x04\x02\x01\x05\x00\x04\x20'
    ) + h
    k = (n.bit_length() + 7) // 8
    ps_len = k - len(digest_info) - 3
    assert ps_len >= 8
    em = b'\x00\x01' + b'\xff' * ps_len + b'\x00' + digest_info
    m_int = int.from_bytes(em, 'big')
    s_int = pow(m_int, d, n)
    return s_int.to_bytes(k, 'big').hex()


def compute_keyid(key_obj):
    return sha256_hex(canonical_json(key_obj))


# ---------- Main ----------

def main():
    output_dir = sys.argv[1] if len(sys.argv) > 1 else '/output'

    print("Generating Key T (targets/snapshot - Fermat-factorable)...")
    n_T, e_T, d_T, p_T, q_T = generate_key_T()
    print(f"  Modulus: {n_T.bit_length()} bits, gap(q-p): {q_T - p_T}")

    print("Generating Key S (timestamp - GCD-vulnerable via shared prime)...")
    n_S, e_S, d_S, p_S, r_S = generate_key_S(p_T)
    print(f"  Modulus: {n_S.bit_length()} bits, shared factor: {p_T.bit_length()} bits")

    # Key T: SubjectPublicKeyInfo PEM format
    key_T_spki_der = rsa_spki_der(n_T, e_T)
    key_T_pem = to_pem(key_T_spki_der, "PUBLIC KEY")

    # Key S: PKCS#1 RSAPublicKey PEM format (different from Key T!)
    key_S_pkcs1_der = rsa_pkcs1_pubkey_der(n_S, e_S)
    key_S_pem = to_pem(key_S_pkcs1_der, "RSA PUBLIC KEY")

    key_obj_T = {
        "keytype": "rsa",
        "scheme": "rsassa-pkcs1v15-sha256",
        "keyval": {"public": key_T_pem}
    }
    key_obj_S = {
        "keytype": "rsa",
        "scheme": "rsassa-pkcs1v15-sha256",
        "keyval": {"public": key_S_pem}
    }
    keyid_T = compute_keyid(key_obj_T)
    keyid_S = compute_keyid(key_obj_S)
    print(f"  Key T ID: {keyid_T[:16]}...")
    print(f"  Key S ID: {keyid_S[:16]}...")

    # Create directories
    os.makedirs(f"{output_dir}/repository/targets", exist_ok=True)
    os.makedirs(f"{output_dir}/keystore", exist_ok=True)

    # Write keystore DER files (both in SPKI format for openssl compatibility)
    with open(f"{output_dir}/keystore/targets_snapshot.pub.der", "wb") as f:
        f.write(key_T_spki_der)
    key_S_spki_der = rsa_spki_der(n_S, e_S)
    with open(f"{output_dir}/keystore/timestamp.pub.der", "wb") as f:
        f.write(key_S_spki_der)

    # Create target files
    fw1 = (b"FIRMWARE_IMAGE_v1.0\x00" + bytes(range(256)) * 4
           + b"\nBuild:v1.0-release-stable-20240315\n")
    with open(f"{output_dir}/repository/targets/firmware_v1.0.bin", "wb") as f:
        f.write(fw1)

    fw2 = (b"FIRMWARE_IMAGE_v1.1\x00" + bytes(range(256)) * 4
           + b"\nBuild:v1.1-security-patch-20240601\n")
    with open(f"{output_dir}/repository/targets/firmware_v1.1.bin", "wb") as f:
        f.write(fw2)

    cfg = json.dumps({
        "version": "1.0",
        "secure_boot": True,
        "debug_mode": False,
        "update_channel": "stable"
    }, indent=2).encode()
    with open(f"{output_dir}/repository/targets/config_default.json", "wb") as f:
        f.write(cfg)

    # Payload to be injected by attacker
    payload = (b"#!/bin/sh\necho 'PAYLOAD_EXECUTED_SUCCESSFULLY'\n"
               b"id\nuname -a\ncat /etc/shadow 2>/dev/null\n")
    with open(f"{output_dir}/payload.bin", "wb") as f:
        f.write(payload)

    # --- TUF Metadata ---

    # root.json (signed by Key T)
    root_signed = {
        "_type": "root",
        "spec_version": "1.0.31",
        "version": 1,
        "expires": "2030-12-31T23:59:59Z",
        "keys": {
            keyid_T: key_obj_T,
            keyid_S: key_obj_S
        },
        "roles": {
            "root": {"keyids": [keyid_T], "threshold": 1},
            "targets": {"keyids": [keyid_T], "threshold": 1},
            "snapshot": {"keyids": [keyid_T], "threshold": 1},
            "timestamp": {"keyids": [keyid_S], "threshold": 1}
        },
        "consistent_snapshot": False
    }
    root_sig = rsa_sign_pkcs1v15_sha256(canonical_json(root_signed), n_T, d_T)
    root_metadata = {
        "signed": root_signed,
        "signatures": [{"keyid": keyid_T, "sig": root_sig}]
    }

    # targets.json (signed by Key T)
    targets_signed = {
        "_type": "targets",
        "spec_version": "1.0.31",
        "version": 1,
        "expires": "2030-12-31T23:59:59Z",
        "targets": {
            "firmware_v1.0.bin": {
                "length": len(fw1),
                "hashes": {"sha256": sha256_hex(fw1)}
            },
            "firmware_v1.1.bin": {
                "length": len(fw2),
                "hashes": {"sha256": sha256_hex(fw2)}
            },
            "config_default.json": {
                "length": len(cfg),
                "hashes": {"sha256": sha256_hex(cfg)}
            }
        }
    }
    targets_sig = rsa_sign_pkcs1v15_sha256(canonical_json(targets_signed), n_T, d_T)
    targets_metadata = {
        "signed": targets_signed,
        "signatures": [{"keyid": keyid_T, "sig": targets_sig}]
    }

    # snapshot.json (signed by Key T)
    snapshot_signed = {
        "_type": "snapshot",
        "spec_version": "1.0.31",
        "version": 1,
        "expires": "2030-12-31T23:59:59Z",
        "meta": {
            "targets.json": {"version": 1}
        }
    }
    snapshot_sig = rsa_sign_pkcs1v15_sha256(canonical_json(snapshot_signed), n_T, d_T)
    snapshot_metadata = {
        "signed": snapshot_signed,
        "signatures": [{"keyid": keyid_T, "sig": snapshot_sig}]
    }

    # timestamp.json (signed by Key S — different key!)
    snapshot_bytes = json.dumps(snapshot_metadata, indent=2).encode()
    timestamp_signed = {
        "_type": "timestamp",
        "spec_version": "1.0.31",
        "version": 1,
        "expires": "2030-12-31T23:59:59Z",
        "meta": {
            "snapshot.json": {
                "version": 1,
                "length": len(snapshot_bytes),
                "hashes": {"sha256": sha256_hex(snapshot_bytes)}
            }
        }
    }
    timestamp_sig = rsa_sign_pkcs1v15_sha256(canonical_json(timestamp_signed), n_S, d_S)
    timestamp_metadata = {
        "signed": timestamp_signed,
        "signatures": [{"keyid": keyid_S, "sig": timestamp_sig}]
    }

    # Write all metadata
    for name, data in [
        ("root.json", root_metadata),
        ("1.root.json", root_metadata),
        ("targets.json", targets_metadata),
        ("snapshot.json", snapshot_metadata),
        ("timestamp.json", timestamp_metadata),
    ]:
        with open(f"{output_dir}/repository/{name}", "w") as f:
            json.dump(data, f, indent=2)

    print(f"Repository created at {output_dir}/repository/")
    print(f"Keystore at {output_dir}/keystore/")
    print(f"Payload at {output_dir}/payload.bin")
    print("Done.")


if __name__ == "__main__":
    main()
