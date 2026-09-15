#!/usr/bin/env python3
"""Generate challenge crypto artifacts. Runs during Docker build, then deleted."""
import hashlib
import json
import os
import random

FLAG = b'n0_crypt0_1s_s4f3_fr0m_th3_d3t3rm1n3d@flare-on.com'
MASTER_KEY = b'FLARE2024MASTERKEY'
RC4_KEY = b'f1rmw4r3_k3y_2024'
SUB_SEED = 42
XOR_SALT = b'STREAM'


def rc4(data, key):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    i = j = 0
    out = []
    for b in data:
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        out.append(b ^ S[(S[i] + S[j]) % 256])
    return bytes(out)


os.makedirs('/app/captured', exist_ok=True)

# === Encrypt the flag with 3-layer pipeline ===
# Layer 1 (innermost): byte substitution
sub_table = list(range(256))
random.Random(SUB_SEED).shuffle(sub_table)
data = bytes([sub_table[b] for b in FLAG])

# Layer 2 (middle): RC4
data = rc4(data, RC4_KEY)

# Layer 3 (outermost): XOR stream derived from master key
xor_key = hashlib.sha256(MASTER_KEY + XOR_SALT).digest()[:16]
data = bytes([b ^ xor_key[i % 16] for i, b in enumerate(data)])

with open('/app/captured/encrypted_payload.bin', 'wb') as f:
    f.write(data)

# === Generate RSA key material (e=3, small plaintext => cube root attack) ===
m = int.from_bytes(MASTER_KEY, 'big')
c = pow(m, 3)  # m^3 < n, so no modular reduction

# Deterministic 2048-bit modulus (just needs to be > m^3)
rng = random.Random(0xDEADBEEF)
n_bytes = bytearray(256)
for i in range(256):
    n_bytes[i] = rng.randint(0, 255)
n_bytes[0] |= 0x80  # Ensure 2048-bit
n = int.from_bytes(bytes(n_bytes), 'big')
assert n > c, "Modulus must exceed ciphertext"

with open('/app/captured/key_material.json', 'w') as f:
    json.dump({'n': hex(n), 'e': 3, 'ciphertext': hex(c)}, f, indent=2)

# === Generate encrypted config (contains substitution seed) ===
config = json.dumps({
    'beacon_interval': 300,
    'jitter': 0.2,
    'c2_endpoints': ['https://cdn-assets.example.com/api/v2'],
    'sub_table_seed': SUB_SEED,
    'protocol_version': '2.1',
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'exfil_method': 'dns',
    'persistence': True
}, indent=2).encode()

with open('/app/captured/config.enc', 'wb') as f:
    f.write(rc4(config, RC4_KEY))

# === Write verification hash (plaintext flag never stored in final image) ===
with open('/app/.verification', 'w') as f:
    f.write(hashlib.sha256(FLAG).hexdigest())

print("Challenge artifacts generated successfully.")
