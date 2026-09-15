#!/usr/bin/env python3
"""
Deterministic setup for the PRNG audit cryptanalysis challenge.
Used ONLY during Docker build. NOT available at runtime.
"""

import hashlib
import json
import os
import random
import sqlite3
from Crypto.Util.number import isPrime, bytes_to_long, GCD
from Crypto.PublicKey import RSA


def derive_number(key, label, target_bits):
    """Deterministically derive a large integer from key+label via SHA-512 chain."""
    chunks = []
    needed_bytes = (target_bits + 7) // 8
    for i in range((needed_bytes // 64) + 2):
        h = hashlib.sha512(f"{key}:{label}:{i}".encode()).digest()
        chunks.append(h)
    raw = b"".join(chunks)[:needed_bytes]
    n = int.from_bytes(raw, "big")
    n = n % (1 << target_bits)
    n |= (1 << (target_bits - 1))
    return n


def find_next_prime(n):
    if n % 2 == 0:
        n += 1
    while not isPrime(n):
        n += 2
    return n


def whiten(value, rounds):
    """Replicate HardenedPRNG._whiten for setup purposes."""
    data = value.to_bytes(66, 'big')
    for _ in range(rounds):
        data = hashlib.sha512(data).digest()
    return int.from_bytes(data, 'big')


# ======== Secret Parameters (build-time only) ========
MASTER_KEY = "terminal-bench-prng-audit-v2"

lcg_n = find_next_prime(derive_number(MASTER_KEY, "modulus", 521))
lcg_m = derive_number(MASTER_KEY, "multiplier", 519) % lcg_n
lcg_c = derive_number(MASTER_KEY, "increment", 518) % lcg_n

RSA_E = 65537
NUM_PRIMES = 8
PRIME_BITS = 512
NUM_LOGGED = 6
SEED = 271828182845904523536028747135266249775724709369995
FLAG = b"FLAG{prng_m4sk_byp4ss_lcg_f4ct0r1z4t10n_c7f}"

# Seed for the secure (whitened) HardenedPRNG instance
SEED_D = 314159265358979323846264338327950288419716939937510


# ======== LCG ========
class LCG:
    def __init__(self, m, c, n, s):
        self.m, self.c, self.n, self.state = m, c, n, s

    def next(self):
        self.state = (self.state * self.m + self.c) % self.n
        return self.state


# ======== Generate Challenge Data ========
print(f"[setup] LCG modulus: {lcg_n.bit_length()} bits")
print(f"[setup] LCG multiplier: {lcg_m.bit_length()} bits")
print(f"[setup] LCG increment: {lcg_c.bit_length()} bits")

lcg = LCG(lcg_m, lcg_c, lcg_n, SEED)
primes = []
logged_outputs = []
total_steps = 0

while len(primes) < NUM_PRIMES:
    raw = lcg.next()
    total_steps += 1
    if len(logged_outputs) < NUM_LOGGED:
        logged_outputs.append((total_steps, raw))
    if isPrime(raw) and raw.bit_length() == PRIME_BITS:
        primes.append(raw)
        print(f"[setup] Prime #{len(primes)} at step {total_steps}")

print(f"[setup] All {NUM_PRIMES} primes found after {total_steps} LCG steps")

# RSA key
n_rsa = 1
for p in primes:
    n_rsa *= p
print(f"[setup] RSA modulus: {n_rsa.bit_length()} bits")

phi = 1
for p in primes:
    phi *= (p - 1)

assert GCD(RSA_E, phi) == 1
d = pow(RSA_E, -1, phi)

flag_int = bytes_to_long(FLAG)
assert flag_int < n_rsa
ct = pow(flag_int, RSA_E, n_rsa)
assert pow(ct, d, n_rsa) == flag_int
print("[setup] Encryption round-trip verified")


# ======== Generate whitened outputs for the secure instance (prng-d5e8) ========
lcg_d = LCG(lcg_m, lcg_c, lcg_n, SEED_D)
whitened_outputs_d = []
for i in range(5):
    raw_state = lcg_d.next()
    whitened_int = whiten(raw_state, 64)
    whitened_outputs_d.append((i + 1, whitened_int))
print(f"[setup] Generated {len(whitened_outputs_d)} whitened outputs for prng-d5e8")


# ======== Write Output Files ========
os.makedirs("/app", exist_ok=True)

# 1. DER-encoded RSA public key (SubjectPublicKeyInfo / PKCS#8)
rsa_key_obj = RSA.construct((n_rsa, RSA_E))
der_data = rsa_key_obj.export_key(format='DER')
with open("/app/pubkey.der", "wb") as f:
    f.write(der_data)
print(f"[setup] Public key: {len(der_data)} bytes DER")

# 2. SQLite audit database with multiple PRNG instances (including red herrings)
db_path = "/app/audit.db"
db = sqlite3.connect(db_path)
cur = db.cursor()

cur.execute("""CREATE TABLE prng_instances (
    instance_id TEXT PRIMARY KEY,
    algorithm TEXT,
    purpose TEXT,
    created_at TEXT,
    seed_fingerprint TEXT,
    status TEXT
)""")

cur.execute("""CREATE TABLE prng_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT,
    step_number INTEGER,
    output_hex TEXT,
    timestamp TEXT,
    FOREIGN KEY (instance_id) REFERENCES prng_instances(instance_id)
)""")

cur.execute("""CREATE TABLE key_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT,
    event_type TEXT,
    key_id TEXT,
    key_algorithm TEXT,
    timestamp TEXT,
    details TEXT,
    FOREIGN KEY (instance_id) REFERENCES prng_instances(instance_id)
)""")

# Instance A: The vulnerable LCG PRNG (used for CA key generation, whiten_rounds=0)
seed_fp = hashlib.sha256(str(SEED).encode()).hexdigest()[:16]
cur.execute("INSERT INTO prng_instances VALUES (?,?,?,?,?,?)",
            ("prng-7a3f", "HardenedPRNG-LCG", "ca-keygen",
             "2024-03-15T09:00:00Z", seed_fp, "active"))

# Instance B: ChaCha20 PRNG (red herring - TLS session keys)
cur.execute("INSERT INTO prng_instances VALUES (?,?,?,?,?,?)",
            ("prng-b1e2", "ChaCha20-CSPRNG", "tls-session-keys",
             "2024-03-14T08:00:00Z",
             hashlib.sha256(b"chacha-seed-1").hexdigest()[:16], "active"))

# Instance C: Another ChaCha20 PRNG (red herring - nonce generation)
cur.execute("INSERT INTO prng_instances VALUES (?,?,?,?,?,?)",
            ("prng-c4d9", "ChaCha20-CSPRNG", "nonce-generation",
             "2024-03-14T12:00:00Z",
             hashlib.sha256(b"chacha-seed-2").hexdigest()[:16], "revoked"))

# Instance D: HardenedPRNG with proper whitening (whiten_rounds=64, secure)
seed_fp_d = hashlib.sha256(str(SEED_D).encode()).hexdigest()[:16]
cur.execute("INSERT INTO prng_instances VALUES (?,?,?,?,?,?)",
            ("prng-d5e8", "HardenedPRNG-LCG", "code-signing",
             "2024-03-15T10:00:00Z", seed_fp_d, "active"))

# PRNG outputs for Instance A (the real LCG outputs — raw, unwhitened)
for i, (step, output) in enumerate(logged_outputs):
    cur.execute(
        "INSERT INTO prng_outputs (instance_id, step_number, output_hex, timestamp) "
        "VALUES (?,?,?,?)",
        ("prng-7a3f", step, hex(output), f"2024-03-15T09:00:{i + 1:02d}Z"))

# Red herring outputs for Instance B (fake random data)
rng = random.Random(42)
for i in range(8):
    fake = rng.getrandbits(512)
    cur.execute(
        "INSERT INTO prng_outputs (instance_id, step_number, output_hex, timestamp) "
        "VALUES (?,?,?,?)",
        ("prng-b1e2", i + 1, hex(fake), f"2024-03-14T08:01:{i:02d}Z"))

# Red herring outputs for Instance C (fake random data, different width)
for i in range(5):
    fake = rng.getrandbits(256)
    cur.execute(
        "INSERT INTO prng_outputs (instance_id, step_number, output_hex, timestamp) "
        "VALUES (?,?,?,?)",
        ("prng-c4d9", i + 1, hex(fake), f"2024-03-14T12:00:{i:02d}Z"))

# Whitened outputs for Instance D (SHA-512-whitened LCG — secure)
for step, whitened_val in whitened_outputs_d:
    cur.execute(
        "INSERT INTO prng_outputs (instance_id, step_number, output_hex, timestamp) "
        "VALUES (?,?,?,?)",
        ("prng-d5e8", step, hex(whitened_val),
         f"2024-03-15T10:00:{step:02d}Z"))

# Key events - Instance A (the target, CA key generation)
cur.execute(
    "INSERT INTO key_events (instance_id, event_type, key_id, key_algorithm, "
    "timestamp, details) VALUES (?,?,?,?,?,?)",
    ("prng-7a3f", "key_generation", "ca-key-001", "RSA-4096-MP8",
     "2024-03-15T09:01:00Z",
     json.dumps({"num_primes": 8, "prime_bits": 512, "public_exponent": 65537})))

cur.execute(
    "INSERT INTO key_events (instance_id, event_type, key_id, key_algorithm, "
    "timestamp, details) VALUES (?,?,?,?,?,?)",
    ("prng-7a3f", "cert_issuance", "ca-key-001", "RSA-4096-MP8",
     "2024-03-15T09:02:00Z",
     json.dumps({"subject": "CN=Internal CA,O=Corp", "validity_days": 3650})))

# Key events - Instance D (code-signing key, secure)
cur.execute(
    "INSERT INTO key_events (instance_id, event_type, key_id, key_algorithm, "
    "timestamp, details) VALUES (?,?,?,?,?,?)",
    ("prng-d5e8", "key_generation", "sign-key-001", "RSA-2048",
     "2024-03-15T10:01:00Z",
     json.dumps({"num_primes": 2, "prime_bits": 1024, "public_exponent": 65537})))

# Key events - red herrings
cur.execute(
    "INSERT INTO key_events (instance_id, event_type, key_id, key_algorithm, "
    "timestamp, details) VALUES (?,?,?,?,?,?)",
    ("prng-b1e2", "session_key_derivation", "tls-sess-0042", "AES-256-GCM",
     "2024-03-14T08:02:00Z",
     json.dumps({"protocol": "TLS 1.3",
                 "cipher_suite": "TLS_AES_256_GCM_SHA384"})))

cur.execute(
    "INSERT INTO key_events (instance_id, event_type, key_id, key_algorithm, "
    "timestamp, details) VALUES (?,?,?,?,?,?)",
    ("prng-c4d9", "nonce_generation", "nonce-batch-17", "AES-GCM-IV",
     "2024-03-14T12:01:00Z",
     json.dumps({"batch_size": 1000, "iv_length_bits": 96})))

db.commit()
db.close()
print(f"[setup] Audit database written")

# 3. Encrypted flag (hex-encoded ciphertext)
with open("/app/intercepted.enc", "w") as f:
    f.write(hex(ct))
print("[setup] Encrypted flag written")

print("[setup] Done.")
