#!/usr/bin/env python3
"""
Election data generator for SecureVote benchmark task.
Generates PEM key files, SQLite database, audit log, and patch test keys.
This script runs during Docker build and is NOT included in the final image.
"""

import base64
import hashlib
import json
import os
import random
import sqlite3
import sys

sys.path.insert(0, '/app')
from election_system import (
    generate_key_batch, generate_key_seeded, generate_key_adjacent,
    encode_vote, encrypt_vote, CANDIDATES, PUBLIC_EXPONENT,
    RSA_HALF_BITS, _next_prime
)


# ============================================================
# DER/PEM encoding for RSA public keys
# ============================================================

def _der_len(length):
    if length < 0x80:
        return bytes([length])
    elif length < 0x100:
        return bytes([0x81, length])
    else:
        return bytes([0x82, (length >> 8) & 0xff, length & 0xff])


def _der_int(n):
    if n == 0:
        raw = b'\x00'
    else:
        raw = n.to_bytes((n.bit_length() + 7) // 8, 'big')
        if raw[0] & 0x80:
            raw = b'\x00' + raw
    return b'\x02' + _der_len(len(raw)) + raw


def _der_seq(data):
    return b'\x30' + _der_len(len(data)) + data


def _der_bits(data):
    payload = b'\x00' + data
    return b'\x03' + _der_len(len(payload)) + payload


def rsa_pubkey_pem(n, e):
    """Generate PEM-encoded RSA public key in SubjectPublicKeyInfo format."""
    # RSA algorithm OID: 1.2.840.113549.1.1.1
    oid = bytes([0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d,
                 0x01, 0x01, 0x01])
    algo = _der_seq(oid + b'\x05\x00')
    rsa_key = _der_seq(_der_int(n) + _der_int(e))
    spki = _der_seq(algo + _der_bits(rsa_key))
    b64 = base64.b64encode(spki).decode()
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    return ("-----BEGIN PUBLIC KEY-----\n" +
            "\n".join(lines) +
            "\n-----END PUBLIC KEY-----\n")


# ============================================================
# Election configuration
# ============================================================

BATCH_ALPHA_SEED = 0x53435652
BATCH_BETA_BASE_TS = 1730800532
BATCH_GAMMA_SEEDS = list(range(7001, 7011))

VOTE_MAP = {
    'V001': 1, 'V002': 3, 'V003': 0, 'V004': 2, 'V005': 1,
    'V006': 3, 'V007': 0, 'V008': 1, 'V009': 2, 'V010': 3,
    'V011': 1, 'V012': 0, 'V013': 2, 'V014': 3, 'V015': 1,
    'V016': 0, 'V017': 1, 'V018': 2, 'V019': 3, 'V020': 0,
    'V021': 2, 'V022': 1, 'V023': 3, 'V024': 0, 'V025': 1,
    'V026': 1, 'V027': 3, 'V028': 2, 'V029': 0, 'V030': 3,
}


# ============================================================
# Patch test key generators (mirror each patch's algorithm)
# ============================================================

def gen_secure_key(seed):
    """Generate a key with independent random primes (for SECURE patch test keys)."""
    rng = random.Random(seed)
    p_candidate = rng.getrandbits(RSA_HALF_BITS)
    p_candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
    p = _next_prime(p_candidate)
    q_candidate = rng.getrandbits(RSA_HALF_BITS)
    q_candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
    q = _next_prime(q_candidate)
    return (p * q, PUBLIC_EXPONENT)


def gen_improved_pool_keys(batch_seed, count):
    """Mirror of Patch B: deterministic pool with random pair selection."""
    rng = random.Random(batch_seed)
    pool_size = count * 3
    prime_pool = []
    for _ in range(pool_size):
        candidate = rng.getrandbits(RSA_HALF_BITS)
        candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
        prime_pool.append(_next_prime(candidate))
    keys = []
    indices_used = set()
    for _ in range(count):
        while True:
            i = rng.randrange(pool_size)
            j = rng.randrange(pool_size)
            if i != j and i not in indices_used and j not in indices_used:
                indices_used.add(i)
                indices_used.add(j)
                break
        keys.append((prime_pool[i] * prime_pool[j], PUBLIC_EXPONENT))
    return keys


def gen_independent_hash_key(seed_value):
    """Mirror of Patch D: independent SHA-512 derivation for both primes."""
    p_material = hashlib.sha512(f"independent_p:{seed_value}".encode()).digest()
    p_candidate = int.from_bytes(p_material, 'big') >> (512 - RSA_HALF_BITS)
    p_candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
    p = _next_prime(p_candidate)
    q_material = hashlib.sha512(f"independent_q:{seed_value}".encode()).digest()
    q_candidate = int.from_bytes(q_material, 'big') >> (512 - RSA_HALF_BITS)
    q_candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
    q = _next_prime(q_candidate)
    return (p * q, PUBLIC_EXPONENT)


def gen_extended_gap_key(seed_value):
    """Mirror of Patch E: close primes with 48-bit gap (still vulnerable)."""
    p_material = hashlib.sha512(f"sv_prime_p:{seed_value}".encode()).digest()
    p_candidate = int.from_bytes(p_material, 'big') >> (512 - RSA_HALF_BITS)
    p_candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
    p = _next_prime(p_candidate)
    q_material = hashlib.sha512(f"sv_prime_q:{seed_value}".encode()).digest()
    q_offset = int.from_bytes(q_material[:6], 'big')
    q_candidate = p + q_offset * 2 + 1
    if q_candidate % 2 == 0:
        q_candidate += 1
    q = _next_prime(q_candidate)
    return (p * q, PUBLIC_EXPONENT)


# ============================================================
# Main setup
# ============================================================

def main():
    os.makedirs('/app/keys', exist_ok=True)
    for d in 'ABCDE':
        os.makedirs(f'/app/patches/test_keys/{d}', exist_ok=True)

    # ---- Create SQLite database ----
    conn = sqlite3.connect('/app/election.db')
    cur = conn.cursor()
    cur.execute('''CREATE TABLE voters (
        voter_id TEXT PRIMARY KEY,
        batch TEXT NOT NULL,
        enrollment_time TEXT NOT NULL
    )''')
    cur.execute('''CREATE TABLE ballots (
        voter_id TEXT PRIMARY KEY,
        encrypted_vote TEXT NOT NULL,
        FOREIGN KEY(voter_id) REFERENCES voters(voter_id)
    )''')
    cur.execute('''CREATE TABLE election_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')
    cur.execute("INSERT INTO election_meta VALUES ('election_id', '2024-district-7')")
    cur.execute("INSERT INTO election_meta VALUES ('candidates', ?)",
                (json.dumps(CANDIDATES),))

    # ---- Batch alpha: V001-V010 (pool-based keygen) ----
    batch_keys = generate_key_batch(BATCH_ALPHA_SEED, 10)
    for i in range(10):
        vid = f'V{i + 1:03d}'
        n, e = batch_keys[i]
        m = encode_vote(vid, VOTE_MAP[vid])
        ct = encrypt_vote(m, n, e)
        with open(f'/app/keys/{vid}.pem', 'w') as f:
            f.write(rsa_pubkey_pem(n, e))
        cur.execute("INSERT INTO voters VALUES (?, 'alpha', ?)",
                    (vid, f'2024-11-05T07:30:{i:02d}Z'))
        cur.execute("INSERT INTO ballots VALUES (?, ?)", (vid, str(ct)))

    # ---- Batch beta: V011-V020 (timestamp-seeded keygen) ----
    for i in range(10):
        vid = f'V{i + 11:03d}'
        ts = BATCH_BETA_BASE_TS + i
        n, e = generate_key_seeded(ts)
        m = encode_vote(vid, VOTE_MAP[vid])
        ct = encrypt_vote(m, n, e)
        with open(f'/app/keys/{vid}.pem', 'w') as f:
            f.write(rsa_pubkey_pem(n, e))
        cur.execute("INSERT INTO voters VALUES (?, 'beta', ?)",
                    (vid, f'2024-11-05T08:15:{32 + i:02d}Z'))
        cur.execute("INSERT INTO ballots VALUES (?, ?)", (vid, str(ct)))

    # ---- Batch gamma: V021-V030 (hash-derived keygen) ----
    for i in range(10):
        vid = f'V{i + 21:03d}'
        seed = BATCH_GAMMA_SEEDS[i]
        n, e = generate_key_adjacent(seed)
        m = encode_vote(vid, VOTE_MAP[vid])
        ct = encrypt_vote(m, n, e)
        with open(f'/app/keys/{vid}.pem', 'w') as f:
            f.write(rsa_pubkey_pem(n, e))
        cur.execute("INSERT INTO voters VALUES (?, 'gamma', ?)",
                    (vid, f'2024-11-05T09:00:{i:02d}Z'))
        cur.execute("INSERT INTO ballots VALUES (?, ?)", (vid, str(ct)))

    conn.commit()
    conn.close()

    # ---- Generate audit log ----
    log = []
    log.append("=== SecureVote Audit Log - Election 2024-district-7 ===")
    log.append("")
    log.append("[2024-11-05T07:00:00Z] System initialized")
    log.append("[2024-11-05T07:00:01Z] Election parameters loaded: "
               "4 candidates, 30 voters")
    log.append("[2024-11-05T07:15:00Z] Candidate roster finalized: "
               "Aster, Bloom, Cedar, Dahlia")
    log.append("")
    log.append("--- Batch alpha enrollment (pool-based keygen) ---")
    for i in range(10):
        vid = f'V{i + 1:03d}'
        log.append(
            f"[2024-11-05T07:30:{i:02d}Z] KeyGen voter={vid} batch=alpha "
            f"method=pool_batch pool_seed={BATCH_ALPHA_SEED} status=complete"
        )
    log.append("")
    log.append("--- Batch beta enrollment (field-seeded keygen) ---")
    for i in range(10):
        vid = f'V{i + 11:03d}'
        ts = BATCH_BETA_BASE_TS + i
        log.append(
            f"[2024-11-05T08:15:{32 + i:02d}Z] KeyGen voter={vid} batch=beta "
            f"method=seeded_generate seed_time={ts} status=complete"
        )
    log.append("")
    log.append("--- Batch gamma enrollment (hash-derived keygen) ---")
    for i in range(10):
        vid = f'V{i + 21:03d}'
        seed = BATCH_GAMMA_SEEDS[i]
        log.append(
            f"[2024-11-05T09:00:{i:02d}Z] KeyGen voter={vid} batch=gamma "
            f"method=adjacent_derive derivation_seed={seed} status=complete"
        )
    log.append("")
    log.append("--- Vote encryption phase ---")
    for i in range(30):
        vid = f'V{i + 1:03d}'
        log.append(
            f"[2024-11-05T10:{i // 10:02d}:{(i % 10) * 6:02d}Z] VoteEncrypt "
            f"voter={vid} status=sealed"
        )
    log.append("")
    log.append("[2024-11-05T10:30:00Z] Election data finalized and sealed")
    log.append("[2024-11-05T10:30:01Z] Audit log closed")
    log.append("=== End of log ===")

    with open('/app/audit.log', 'w') as f:
        f.write('\n'.join(log) + '\n')

    # ---- Generate patch test keys ----

    # Patch A (SECURE): CSPRNG-based independent generation
    for i, seed in enumerate([0xA001, 0xA002, 0xA003]):
        n, e = gen_secure_key(seed)
        with open(f'/app/patches/test_keys/A/key{i + 1}.pem', 'w') as f:
            f.write(rsa_pubkey_pem(n, e))

    # Patch B (VULNERABLE): Improved pool with known seed
    patch_b_keys = gen_improved_pool_keys(0xBEEF5678, 3)
    for i, (n, e) in enumerate(patch_b_keys):
        with open(f'/app/patches/test_keys/B/key{i + 1}.pem', 'w') as f:
            f.write(rsa_pubkey_pem(n, e))

    # Patch C (SECURE): SystemRandom-based
    for i, seed in enumerate([0xC001, 0xC002, 0xC003]):
        n, e = gen_secure_key(seed)
        with open(f'/app/patches/test_keys/C/key{i + 1}.pem', 'w') as f:
            f.write(rsa_pubkey_pem(n, e))

    # Patch D (SECURE): Independent hash derivation
    for i, seed in enumerate([8001, 8002, 8003]):
        n, e = gen_independent_hash_key(seed)
        with open(f'/app/patches/test_keys/D/key{i + 1}.pem', 'w') as f:
            f.write(rsa_pubkey_pem(n, e))

    # Patch E (VULNERABLE): Extended gap — still close primes
    for i, seed in enumerate([9001, 9002, 9003]):
        n, e = gen_extended_gap_key(seed)
        with open(f'/app/patches/test_keys/E/key{i + 1}.pem', 'w') as f:
            f.write(rsa_pubkey_pem(n, e))

    print(f"Generated: 30 voter keys, SQLite DB, audit log, "
          f"5 patches with 3 test keys each")


if __name__ == '__main__':
    main()
