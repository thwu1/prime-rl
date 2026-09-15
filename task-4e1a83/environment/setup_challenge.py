#!/usr/bin/env python3
"""Generate audit artifacts for the DH key exchange challenge."""
import base64
import hashlib
import math
import os
import random
import sqlite3
import struct

SMALL_PRIMES = [3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53,
                59, 61, 67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113,
                127, 131, 137, 139, 149, 151, 157, 163, 167, 173, 179, 181,
                191, 193, 197, 199, 211, 223, 227, 229, 233, 239, 241, 251,
                257, 263, 269, 271, 277, 281, 283, 293, 307, 311, 313]


def is_prime(n):
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0:
        return False
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
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


def is_primitive_root(g, p, prime_factors):
    for qi in prime_factors:
        if pow(g, (p - 1) // qi, p) == 1:
            return False
    return True


def find_smooth_prime(target_bits, rng):
    for _ in range(500000):
        val = 2
        while val.bit_length() < target_bits - 1:
            sp = rng.choice(SMALL_PRIMES)
            val *= sp
        p = val + 1
        if p.bit_length() >= target_bits - 3 and is_prime(p):
            return p
    raise RuntimeError("Could not find smooth prime")


def factorize_smooth(n):
    factors = {}
    for sp in [2] + SMALL_PRIMES:
        while n % sp == 0:
            factors[sp] = factors.get(sp, 0) + 1
            n //= sp
    if n > 1:
        factors[n] = 1
    return factors


def der_encode_length(length):
    if length < 0x80:
        return bytes([length])
    elif length < 0x100:
        return b'\x81' + bytes([length])
    else:
        return b'\x82' + length.to_bytes(2, 'big')


def int_to_der_integer(n):
    if n == 0:
        payload = b'\x00'
    else:
        byte_len = (n.bit_length() + 7) // 8
        payload = n.to_bytes(byte_len, 'big')
        if payload[0] & 0x80:
            payload = b'\x00' + payload
    return b'\x02' + der_encode_length(len(payload)) + payload


def make_dh_params_pem(modulus, generator):
    p_der = int_to_der_integer(modulus)
    g_der = int_to_der_integer(generator)
    seq_payload = p_der + g_der
    seq = b'\x30' + der_encode_length(len(seq_payload)) + seq_payload
    b64 = base64.b64encode(seq).decode('ascii')
    lines = [b64[i:i+64] for i in range(0, len(b64), 64)]
    return ("-----BEGIN DH PARAMETERS-----\n"
            + "\n".join(lines)
            + "\n-----END DH PARAMETERS-----\n")


def main():
    os.makedirs("/app/artifacts", exist_ok=True)

    rng_p = random.Random(0xDEADBEEF)
    rng_q = random.Random(0xCAFEBABE)

    p = find_smooth_prime(128, rng_p)
    q = find_smooth_prime(128, rng_q)
    while p == q:
        q = find_smooth_prime(128, rng_q)

    n = p * q

    p_pf = sorted(set(factorize_smooth(p - 1).keys()))
    q_pf = sorted(set(factorize_smooth(q - 1).keys()))

    g = None
    for g_candidate in range(2, 10000):
        if (is_primitive_root(g_candidate, p, p_pf) and
                is_primitive_root(g_candidate, q, q_pf)):
            g = g_candidate
            break

    lam = (p - 1) * (q - 1) // math.gcd(p - 1, q - 1)
    rng_a = random.Random(0xF00DBABE)
    a = rng_a.randint(lam // 4, lam // 2)
    A = pow(g, a, n)

    # --- Artifact 1: DH parameter PEM file ---
    pem_content = make_dh_params_pem(n, g)
    with open("/app/artifacts/server_dhparams.pem", "w") as f:
        f.write(pem_content)

    # --- Artifact 2: SQLite audit database ---
    target_sid = "a3f7c912-4e8b-4d2a-b6c1-8e9f0a1b2c3d"

    db = sqlite3.connect("/app/artifacts/audit.db")
    cur = db.cursor()

    cur.execute("""CREATE TABLE key_exchanges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        session_id TEXT NOT NULL,
        client_ip TEXT NOT NULL,
        server_ip TEXT NOT NULL,
        public_value_hex TEXT NOT NULL,
        status TEXT NOT NULL
    )""")

    cur.execute("""CREATE TABLE sessions (
        session_id TEXT PRIMARY KEY,
        established_at TEXT NOT NULL,
        cipher_spec TEXT NOT NULL,
        key_derivation TEXT NOT NULL,
        status TEXT NOT NULL
    )""")

    fake_rng = random.Random(0x12345678)
    fake_clients = ["10.0.1.15", "10.0.1.22", "10.0.2.8", "10.0.3.44",
                    "192.168.1.100", "10.0.1.7", "172.16.0.33"]

    for i in range(15):
        fsid = "{:08x}-{:04x}-{:04x}-{:04x}-{:012x}".format(
            fake_rng.randint(0, 0xFFFFFFFF),
            fake_rng.randint(0, 0xFFFF),
            fake_rng.randint(0, 0xFFFF),
            fake_rng.randint(0, 0xFFFF),
            fake_rng.randint(0, 0xFFFFFFFFFFFF))
        fpub = format(fake_rng.getrandbits(256), 'x')
        fts = "2024-11-{:02d}T{:02d}:{:02d}:{:02d}Z".format(
            10 + i % 20, 8 + i % 12,
            fake_rng.randint(0, 59), fake_rng.randint(0, 59))
        cur.execute(
            "INSERT INTO key_exchanges "
            "(timestamp,session_id,client_ip,server_ip,public_value_hex,status) "
            "VALUES (?,?,?,?,?,?)",
            (fts, fsid, fake_rng.choice(fake_clients),
             "10.0.0.1", fpub, "completed"))
        cur.execute(
            "INSERT INTO sessions "
            "(session_id,established_at,cipher_spec,key_derivation,status) "
            "VALUES (?,?,?,?,?)",
            (fsid, fts, "DH-XOR-SHA256",
             "sha256(decimal(private_key))", "closed"))

    real_ts = "2024-11-15T14:32:17Z"
    cur.execute(
        "INSERT INTO key_exchanges "
        "(timestamp,session_id,client_ip,server_ip,public_value_hex,status) "
        "VALUES (?,?,?,?,?,?)",
        (real_ts, target_sid, "10.0.1.42", "10.0.0.1",
         format(A, 'x'), "completed"))
    cur.execute(
        "INSERT INTO sessions "
        "(session_id,established_at,cipher_spec,key_derivation,status) "
        "VALUES (?,?,?,?,?)",
        (target_sid, real_ts, "DH-XOR-SHA256",
         "sha256(decimal(private_key))", "active"))

    db.commit()
    db.close()

    # --- Artifact 3: Proprietary binary capture ---
    flag = b"FLAG{cr7pt0_4ud1t_s3ss10n_d3crypt3d_2024}"
    key = hashlib.sha256(str(a).encode()).digest()
    ciphertext = bytes(flag[i] ^ key[i % 32] for i in range(len(flag)))
    plaintext_hash = hashlib.sha256(flag).digest()

    sid_bytes = target_sid.encode('ascii')
    ts_unix = 1731681137

    capture = b""
    capture += b"KSEC"
    capture += struct.pack(">H", 1)
    capture += struct.pack(">Q", ts_unix)
    capture += struct.pack(">B", len(sid_bytes))
    capture += sid_bytes
    capture += struct.pack(">B", 0x01)
    capture += struct.pack(">I", len(ciphertext))
    capture += ciphertext
    capture += plaintext_hash

    with open("/app/artifacts/session_capture.bin", "wb") as f:
        f.write(capture)


if __name__ == "__main__":
    main()
