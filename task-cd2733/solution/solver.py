#!/usr/bin/env python3
"""
Solver for the PRNG infrastructure security evaluation challenge.

Strategy:
1. Parse the DER public key to extract RSA modulus and exponent.
2. Query the SQLite audit database to enumerate all PRNG instances.
3. Classify ChaCha20-CSPRNG instances as immediately secure.
4. For each HardenedPRNG-LCG instance, extract logged outputs and
   attempt LCG parameter recovery to determine if whitening was disabled.
5. On the vulnerable instance (raw LCG outputs): recover LCG parameters,
   replay from the known seed, collect 512-bit primes, factor the RSA
   modulus, compute the private key, and decrypt the intercepted message.
6. On the secure instance (whitened outputs): confirm that LCG recovery
   fails, classifying it as secure.
7. Evaluate the remediation proposal: SHA-512 whitening with >= 1 round
   prevents LCG state recovery via preimage resistance.
8. Write assessment.json and flag.txt.
"""

import json
import sqlite3
import sys
from math import gcd
from functools import reduce
from Crypto.Util.number import long_to_bytes, bytes_to_long, isPrime
from Crypto.PublicKey import RSA


# ================================================================
# Step 1: Extract RSA public key from DER file
# ================================================================
print("[*] Reading DER-encoded public key...")
with open("/app/pubkey.der", "rb") as f:
    rsa_key = RSA.import_key(f.read())
n_rsa = rsa_key.n
e = rsa_key.e
print(f"[*] RSA modulus: {n_rsa.bit_length()} bits, e={e}")

# ================================================================
# Step 2: Enumerate all PRNG instances from the audit database
# ================================================================
print("[*] Querying audit database...")
db = sqlite3.connect("/app/audit.db")

instances = db.execute(
    "SELECT instance_id, algorithm, purpose, status FROM prng_instances"
).fetchall()

print(f"[*] Found {len(instances)} PRNG instances:")
for inst_id, algo, purpose, status in instances:
    print(f"    {inst_id}: {algo} ({purpose}, {status})")

# ================================================================
# Step 3: Classify instances
# ================================================================
secure_instances = []
hardened_instances = []

for inst_id, algo, purpose, status in instances:
    if "ChaCha20" in algo:
        # ChaCha20-CSPRNG is a cryptographically secure PRNG by design
        secure_instances.append(inst_id)
        print(f"[+] {inst_id}: ChaCha20-CSPRNG → SECURE (CSPRNG by design)")
    elif "HardenedPRNG" in algo:
        hardened_instances.append((inst_id, purpose))
        print(f"[?] {inst_id}: HardenedPRNG-LCG → needs output analysis")

# ================================================================
# Step 4: Analyze HardenedPRNG instances for LCG structure
# ================================================================
compromised_instance = None
compromised_outputs = None

for inst_id, purpose in hardened_instances:
    rows = db.execute("""
        SELECT step_number, output_hex FROM prng_outputs
        WHERE instance_id = ?
        ORDER BY step_number ASC
    """, (inst_id,)).fetchall()

    s = [int(r[1], 16) for r in rows]
    print(f"\n[*] Analyzing {inst_id} ({len(s)} outputs)...")

    if len(s) < 4:
        print(f"[!] Insufficient outputs for LCG analysis on {inst_id}")
        secure_instances.append(inst_id)
        continue

    # Attempt LCG parameter recovery from consecutive outputs.
    # If outputs are raw LCG states, differences satisfy:
    #   t_i * t_{i+2} - t_{i+1}^2 ≡ 0 (mod lcg_modulus)
    t = [s[i + 1] - s[i] for i in range(len(s) - 1)]

    zeros = []
    for i in range(len(t) - 2):
        z = t[i + 2] * t[i] - t[i + 1] * t[i + 1]
        zeros.append(abs(z))

    candidate_n = reduce(gcd, zeros)

    # Strip small spurious factors
    for small_p in range(2, 10000):
        while candidate_n % small_p == 0 and candidate_n > (1 << 500):
            candidate_n //= small_p

    # Verify: if candidate_n is a plausible LCG modulus (~521 bits),
    # try to recover multiplier and check consistency
    if candidate_n.bit_length() >= 500 and candidate_n.bit_length() <= 530:
        try:
            lcg_m = (t[1] * pow(t[0], -1, candidate_n)) % candidate_n
            lcg_c = (s[1] - lcg_m * s[0]) % candidate_n

            # Verify recovery against all outputs
            state = s[0]
            valid = True
            for i in range(1, len(s)):
                state = (state * lcg_m + lcg_c) % candidate_n
                if state != s[i]:
                    valid = False
                    break

            if valid:
                print(f"[!] {inst_id}: LCG structure CONFIRMED — whiten_rounds=0")
                print(f"    Recovered modulus: {candidate_n.bit_length()} bits")
                compromised_instance = inst_id
                compromised_outputs = s
                lcg_n = candidate_n
            else:
                print(f"[+] {inst_id}: LCG verification failed → outputs are whitened → SECURE")
                secure_instances.append(inst_id)
        except (ValueError, ZeroDivisionError):
            print(f"[+] {inst_id}: LCG recovery failed → outputs are whitened → SECURE")
            secure_instances.append(inst_id)
    else:
        print(f"[+] {inst_id}: No LCG modulus found ({candidate_n.bit_length()} bits) → SECURE")
        secure_instances.append(inst_id)

if not compromised_instance:
    print("[!] No compromised instance found!")
    sys.exit(1)

print(f"\n[*] Compromised instance: {compromised_instance}")
print(f"[*] Secure instances: {secure_instances}")

# ================================================================
# Step 5: Identify the key generation event for the compromised instance
# ================================================================
key_event = db.execute("""
    SELECT key_id, key_algorithm, details
    FROM key_events
    WHERE instance_id = ? AND event_type = 'key_generation'
""", (compromised_instance,)).fetchone()
db.close()

if not key_event:
    print("[!] No key generation event for compromised instance")
    sys.exit(1)

details = json.loads(key_event[2])
print(f"[*] Key: {key_event[0]}, algorithm: {key_event[1]}")
print(f"[*] Details: {details}")

# ================================================================
# Step 6: Verify seed and replay the LCG to find primes
# ================================================================
SEED = 271828182845904523536028747135266249775724709369995

expected_s0 = (SEED * lcg_m + lcg_c) % lcg_n
assert expected_s0 == compromised_outputs[0], "Seed verification failed"
print("[+] Seed verified against first logged output")

num_primes = details.get("num_primes", 8)
prime_bits = details.get("prime_bits", 512)

state = SEED
primes = []
step = 0

while len(primes) < num_primes:
    state = (state * lcg_m + lcg_c) % lcg_n
    step += 1
    if isPrime(state) and state.bit_length() == prime_bits:
        primes.append(state)
        print(f"[*] Prime #{len(primes)} found at step {step}")

print(f"[+] All {num_primes} primes found after {step} LCG steps")

# ================================================================
# Step 7: Verify primes factor the RSA modulus
# ================================================================
n_check = 1
for p in primes:
    assert n_rsa % p == 0, "Prime does not divide RSA modulus"
    n_check *= p
assert n_check == n_rsa, "Product of recovered primes != RSA modulus"
print("[+] All primes verified as factors of RSA modulus")

# ================================================================
# Step 8: Decrypt the intercepted message
# ================================================================
phi = 1
for p in primes:
    phi *= (p - 1)

d = pow(e, -1, phi)

with open("/app/intercepted.enc") as f:
    ct = int(f.read().strip(), 16)

flag_int = pow(ct, d, n_rsa)
flag = long_to_bytes(flag_int).decode("ascii")
print(f"[+] Decrypted: {flag}")

# ================================================================
# Step 9: Evaluate the remediation proposal
# ================================================================
# The HardenedPRNG applies SHA-512 iteratively to the raw LCG state.
# SHA-512 provides preimage resistance (~256-bit security), meaning
# even a single round of whitening makes LCG state recovery computationally
# infeasible. The minimum secure value for whiten_rounds is 1.
# The proposal suggests whiten_rounds=3, which exceeds the minimum.
remediation_verdict = "ACCEPT"
minimum_secure_rounds = 1
print(f"[*] Remediation: whiten_rounds=3 proposed, minimum needed is {minimum_secure_rounds}")
print(f"[*] Verdict: {remediation_verdict}")

# ================================================================
# Step 10: Write outputs
# ================================================================
assessment = {
    "compromised_instance": compromised_instance,
    "attack_vector": (
        "HardenedPRNG instance configured with whiten_rounds=0, exposing raw "
        "LCG internal state. Consecutive outputs reveal the linear congruential "
        "structure, enabling recovery of LCG modulus, multiplier, and increment "
        "via GCD of difference-product relations. With recovered parameters and "
        "the known public seed, the full LCG sequence is replayed to extract all "
        "prime factors of the multi-prime RSA modulus."
    ),
    "decrypted_message": flag,
    "secure_instances": sorted(secure_instances),
    "remediation_verdict": remediation_verdict,
    "minimum_secure_rounds": minimum_secure_rounds,
}

with open("/app/assessment.json", "w") as f:
    json.dump(assessment, f, indent=2)
print("[+] Assessment written to /app/assessment.json")

with open("/app/flag.txt", "w") as f:
    f.write(flag)
print("[+] Flag written to /app/flag.txt")
