#!/usr/bin/env python3

"""
RSA key infrastructure audit solution.

Discovers and exploits three classes of vulnerability:
1. Shared prime factors (batch GCD)
2. ROCA fingerprint (CVE-2017-15361) on Infineon TPM-generated keys
3. Close-primes weakness (factorable via Fermat's method)
"""

import hashlib
import json
import math
import os
import subprocess
import sys

from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_der_public_key,
    load_pem_public_key,
)


# ── Key parsing ─────────────────────────────────────────────────────────────

def load_all_keys(keys_dir):
    """Load all RSA public keys from mixed PEM/DER files, return {id: (n, e)}."""
    keys = {}
    for fname in sorted(os.listdir(keys_dir)):
        fpath = os.path.join(keys_dir, fname)
        cert_id = os.path.splitext(fname)[0]

        with open(fpath, "rb") as f:
            data = f.read()

        try:
            if fname.endswith(".pem"):
                # Handle both SPKI and PKCS#1 PEM
                if b"BEGIN RSA PUBLIC KEY" in data:
                    # PKCS#1 format - parse manually via openssl
                    result = subprocess.run(
                        ["openssl", "rsa", "-RSAPublicKey_in", "-pubin",
                         "-in", fpath, "-outform", "DER", "-out", "/dev/stdout"],
                        capture_output=True,
                    )
                    pub = load_der_public_key(result.stdout)
                else:
                    pub = load_pem_public_key(data)
            elif fname.endswith(".der"):
                pub = load_der_public_key(data)
            else:
                continue

            nums = pub.public_numbers()
            keys[cert_id] = (nums.n, nums.e)
            print(f"  Loaded {cert_id}: {nums.n.bit_length()}-bit modulus")
        except Exception as e:
            print(f"  WARNING: Failed to load {fname}: {e}", file=sys.stderr)
            # Fallback: try openssl to convert
            try:
                if fname.endswith(".pem"):
                    result = subprocess.run(
                        ["openssl", "rsa", "-pubin", "-in", fpath, "-modulus", "-noout"],
                        capture_output=True, text=True,
                    )
                else:
                    result = subprocess.run(
                        ["openssl", "rsa", "-pubin", "-inform", "DER",
                         "-in", fpath, "-modulus", "-noout"],
                        capture_output=True, text=True,
                    )
                modulus_hex = result.stdout.strip().split("=")[1]
                n = int(modulus_hex, 16)
                keys[cert_id] = (n, 65537)
                print(f"  Loaded {cert_id} via openssl fallback: {n.bit_length()}-bit")
            except Exception as e2:
                print(f"  FAILED to load {fname}: {e2}", file=sys.stderr)

    return keys


# ── Attack 1: Shared factor detection via pairwise GCD ──────────────────────

def find_shared_factors(keys):
    """Find pairs of keys that share a common prime factor."""
    shared = {}
    ids = sorted(keys.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            id_a, id_b = ids[i], ids[j]
            n_a, n_b = keys[id_a][0], keys[id_b][0]
            g = math.gcd(n_a, n_b)
            if g > 1 and g != n_a and g != n_b:
                print(f"  SHARED FACTOR: {id_a} and {id_b} share p={g}")
                shared[id_a] = (g, n_a // g)
                shared[id_b] = (g, n_b // g)
    return shared


# ── Attack 2: ROCA fingerprint detection ────────────────────────────────────

def small_primes_up_to(n):
    sieve = [True] * (n + 1)
    sieve[0] = sieve[1] = False
    for i in range(2, int(n**0.5) + 1):
        if sieve[i]:
            for j in range(i * i, n + 1, i):
                sieve[j] = False
    return [i for i in range(2, n + 1) if sieve[i]]


def primorial(bound):
    result = 1
    for p in small_primes_up_to(bound):
        result *= p
    return result


ROCA_M = primorial(71)
ROCA_G = 65537
ROCA_PRIMES = small_primes_up_to(71)


def _powers_mod(g, p):
    """Compute the set of all powers of g modulo p."""
    powers = set()
    val = 1
    for _ in range(p):
        powers.add(val)
        val = (val * g) % p
        if val == 1:
            break
    return powers


def is_roca_vulnerable(n):
    """Check if n exhibits the ROCA fingerprint."""
    for p in ROCA_PRIMES:
        if p == 2:
            continue
        powers = _powers_mod(ROCA_G, p)
        if n % p not in powers:
            return False
    return True


def _order_mod_prime(g, p):
    val = g % p
    if val == 0:
        return 0
    order = 1
    current = val
    while current != 1:
        current = (current * val) % p
        order += 1
    return order


def _order_mod_primorial():
    result = 1
    for p in ROCA_PRIMES:
        o = _order_mod_prime(ROCA_G, p)
        result = math.lcm(result, o)
    return result


def factor_roca_key(n):
    """Factor a ROCA-vulnerable RSA modulus via primorial subgroup enumeration."""
    order = _order_mod_primorial()
    val = 1
    for a in range(order):
        if a > 0:
            val = (val * ROCA_G) % ROCA_M
        if val < 2:
            continue
        if n % val == 0:
            q = n // val
            if q > 1 and miller_rabin(val) and miller_rabin(q):
                return min(val, q), max(val, q)
    return None, None


# ── Attack 3: Close-primes detection via Fermat factoring ───────────────────

def fermat_factor(n, max_iterations=100000):
    """Factor n using Fermat's method (works when p and q are close)."""
    a = math.isqrt(n) + 1
    for _ in range(max_iterations):
        b2 = a * a - n
        b = math.isqrt(b2)
        if b * b == b2:
            return a - b, a + b
        a += 1
    return None, None


# ── Primality testing ───────────────────────────────────────────────────────

def miller_rabin(n):
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


# ── RSA private key derivation ──────────────────────────────────────────────

def derive_d(p, q, e=65537):
    return pow(e, -1, math.lcm(p - 1, q - 1))


# ── Main audit logic ───────────────────────────────────────────────────────

def main():
    os.makedirs("/app/results", exist_ok=True)

    # Step 1: Load all keys
    print("=== Loading keys ===")
    keys = load_all_keys("/app/keys")
    print(f"Loaded {len(keys)} keys\n")

    # Track discovered vulnerabilities: cert_id -> (p, q)
    factors = {}
    vuln_flags = {k: False for k in keys}

    # Step 2: Check for shared factors (batch GCD)
    print("=== Checking for shared prime factors ===")
    shared = find_shared_factors(keys)
    for cert_id, (p, q) in shared.items():
        factors[cert_id] = (p, q)
        vuln_flags[cert_id] = True

    # Step 3: Check for ROCA fingerprint
    print("\n=== Checking for ROCA fingerprint ===")
    roca_keys = []
    for cert_id, (n, e) in sorted(keys.items()):
        if cert_id in factors:
            continue  # Already factored
        if is_roca_vulnerable(n):
            print(f"  {cert_id}: ROCA-VULNERABLE ({n.bit_length()}-bit)")
            roca_keys.append(cert_id)
            vuln_flags[cert_id] = True
        else:
            print(f"  {cert_id}: not ROCA")

    # Step 4: Check for close-primes / weak key sizes via Fermat
    print("\n=== Checking for close-primes / weak keys (Fermat) ===")
    for cert_id, (n, e) in sorted(keys.items()):
        if cert_id in factors:
            continue
        if cert_id in roca_keys:
            continue
        # Try Fermat factoring (fast when p ≈ q)
        p, q = fermat_factor(n, max_iterations=100000)
        if p and q and p > 1 and q > 1:
            factors[cert_id] = (min(p, q), max(p, q))
            vuln_flags[cert_id] = True
            print(f"  {cert_id}: CLOSE-PRIMES ({n.bit_length()}-bit), factored")

    # Step 5: Factor ROCA keys
    print("\n=== Factoring ROCA keys ===")
    for cert_id in roca_keys:
        n = keys[cert_id][0]
        print(f"  {cert_id}: factoring {n.bit_length()}-bit modulus...")
        p, q = factor_roca_key(n)
        if p and q:
            factors[cert_id] = (p, q)
            print(f"    SUCCESS: p={p.bit_length()}-bit, q={q.bit_length()}-bit")
        else:
            print(f"    FAILED (modulus may be too large)")

    # Step 6: Decrypt challenge ciphertexts
    print("\n=== Decrypting challenges ===")
    decrypted = {}
    for cert_id, (p, q) in sorted(factors.items()):
        n, e = keys[cert_id]
        d = derive_d(p, q, e)
        # Load challenge
        challenge_path = f"/app/challenges/{cert_id}.json"
        with open(challenge_path) as f:
            c = int(json.load(f)["ciphertext"])
        m = pow(c, d, n)
        decrypted[cert_id] = str(m)
        print(f"  {cert_id}: plaintext = {m}")

    # Step 7: Write results
    print("\n=== Writing results ===")
    audit = {}
    for cert_id in sorted(keys.keys()):
        audit[cert_id] = {"vulnerable": vuln_flags[cert_id]}

    with open("/app/results/audit.json", "w") as f:
        json.dump(audit, f, indent=2)

    with open("/app/results/decrypted.json", "w") as f:
        json.dump(decrypted, f, indent=2)

    print("Done.")


if __name__ == "__main__":
    main()
