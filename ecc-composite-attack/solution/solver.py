#!/usr/bin/env python3
"""
Solver for ECC Protocol Security Audit & Remediation.

Phase 1: Cryptanalysis — Factor composite modulus via Williams p+1,
         solve ECDLP via Pohlig-Hellman on reduced curves, decrypt
         AES-256-CBC payload using the recovered scalar.
Phase 2: Vulnerability Audit — Classify the vulnerability chain and
         evaluate four proposed remediations.
Phase 3: Secure Replacement — Generate hardened ECC parameters using
         PARI/GP to ensure non-smooth curve orders.
"""

import base64
import json
import subprocess
import sys
from math import gcd, isqrt


# ===== Modular arithmetic =====

def extended_gcd(a, b):
    if a == 0:
        return b, 0, 1
    g, x, y = extended_gcd(b % a, a)
    return g, y - (b // a) * x, x


def modinv(a, m):
    g, x, _ = extended_gcd(a % m, m)
    if g != 1:
        return None
    return x % m


# ===== Sieve and factoring =====

def sieve_primes(bound):
    sieve = [True] * (bound + 1)
    sieve[0] = sieve[1] = False
    for i in range(2, isqrt(bound) + 1):
        if sieve[i]:
            for j in range(i * i, bound + 1, i):
                sieve[j] = False
    return [i for i in range(2, bound + 1) if sieve[i]]


def trial_factor(m, primes):
    """Factor m assuming it is smooth over the given primes."""
    factors = {}
    for p in primes:
        while m % p == 0:
            factors[p] = factors.get(p, 0) + 1
            m //= p
        if m == 1:
            break
    if m > 1:
        factors[m] = 1
    return factors


def williams_pp1(n, B):
    """Factor n using Williams p+1 method."""
    primes = sieve_primes(B)
    for seed in [3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47,
                 53, 59, 61, 67, 71, 73]:
        V = seed % n
        for p_i in primes:
            pp = p_i
            while pp * p_i <= B:
                pp *= p_i
            vk = V
            vk1 = (V * V - 2) % n
            bits = bin(pp)[2:]
            for bit in bits[1:]:
                if bit == '1':
                    vk = (vk * vk1 - V) % n
                    vk1 = (vk1 * vk1 - 2) % n
                else:
                    vk1 = (vk * vk1 - V) % n
                    vk = (vk * vk - 2) % n
            V = vk
        g = gcd(V - 2, n)
        if 1 < g < n:
            return g
    return None


# ===== ECC arithmetic on generalized Weierstrass curve =====
# y^2 = x^3 + A*x^2 + B*x + C (mod m)

def ec_add(P, Q, A, B, mod):
    if P is None:
        return Q
    if Q is None:
        return P
    px, py = P
    qx, qy = Q
    if px == qx:
        if (py + qy) % mod == 0:
            return None
        num = (3 * px * px + 2 * A * px + B) % mod
        den = (2 * py) % mod
    else:
        num = (qy - py) % mod
        den = (qx - px) % mod
    inv = modinv(den, mod)
    if inv is None:
        raise ValueError(f"Cannot invert {den} mod {mod}")
    lam = (num * inv) % mod
    x3 = (lam * lam - A - px - qx) % mod
    y3 = (lam * (px - x3) - py) % mod
    return (x3, y3)


def ec_mul(k, P, A, B, mod):
    result = None
    temp = P
    while k > 0:
        if k & 1:
            result = ec_add(result, temp, A, B, mod)
        temp = ec_add(temp, temp, A, B, mod)
        k >>= 1
    return result


# ===== Baby-step Giant-step =====

def bsgs(G, Q, order, A, B, mod):
    m = isqrt(order) + 1
    baby = {}
    current = None
    for j in range(m):
        key = (None, None) if current is None else (current[0], current[1])
        baby[key] = j
        current = ec_add(current, G, A, B, mod)
    neg_mG = ec_mul(m, G, A, B, mod)
    if neg_mG is not None:
        neg_mG = (neg_mG[0], (-neg_mG[1]) % mod)
    gamma = Q
    for i in range(m):
        key = (None, None) if gamma is None else (gamma[0], gamma[1])
        if key in baby:
            return (i * m + baby[key]) % order
        gamma = ec_add(gamma, neg_mG, A, B, mod)
    raise ValueError("BSGS failed")


# ===== Pohlig-Hellman =====

def pohlig_hellman(G, Q, order, factors, A, B, mod):
    remainders = []
    moduli = []
    for prime, exp in factors.items():
        pe = prime ** exp
        cofactor = order // pe
        G_prime = ec_mul(cofactor, G, A, B, mod)
        Q_prime = ec_mul(cofactor, Q, A, B, mod)
        if exp == 1:
            k = bsgs(G_prime, Q_prime, prime, A, B, mod)
        else:
            k = 0
            G_base = ec_mul(pe // prime, G_prime, A, B, mod)
            gamma = Q_prime
            for i in range(exp):
                gamma_i = ec_mul(pe // (prime ** (i + 1)), gamma, A, B, mod)
                d_i = bsgs(G_base, gamma_i, prime, A, B, mod)
                k += d_i * (prime ** i)
                minus_d_G = ec_mul(d_i * (prime ** i), G_prime, A, B, mod)
                if minus_d_G is not None:
                    minus_d_G = (minus_d_G[0], (-minus_d_G[1]) % mod)
                gamma = ec_add(gamma, minus_d_G, A, B, mod)
        remainders.append(k)
        moduli.append(pe)
    result = remainders[0]
    mod_so_far = moduli[0]
    for i in range(1, len(remainders)):
        r = remainders[i]
        m = moduli[i]
        g, u, v = extended_gcd(mod_so_far, m)
        assert (result - r) % g == 0, "CRT inconsistency"
        lcm_val = mod_so_far * m // g
        result = (result + mod_so_far * ((r - result) // g) * u) % lcm_val
        mod_so_far = lcm_val
    return result % mod_so_far


# =================================================================
# Phase 1: Cryptanalysis
# =================================================================

def phase1_cryptanalysis():
    """Factor n, solve ECDLP, decrypt AES payload."""
    with open("/app/challenge/public_params.json") as f:
        params = json.load(f)

    n = int(params["n"])
    A_n = int(params["A"])
    B_n = int(params["B"])
    Gx = int(params["G"]["x"])
    Gy = int(params["G"]["y"])
    Qx = int(params["Q"]["x"])
    Qy = int(params["Q"]["y"])

    print(f"[*] n = {n} ({n.bit_length()} bits)", flush=True)

    # Factor n via Williams' p+1
    print("[*] Factoring n via Williams' p+1...", flush=True)
    p = williams_pp1(n, 300000)
    if p is None:
        print("[!] B=300000 failed, trying B=1000000...", flush=True)
        p = williams_pp1(n, 1000000)
    if p is None:
        print("[!] Pure Python failed, falling back to ecm...", flush=True)
        result = subprocess.run(
            ['ecm', '-pp1', '-q', '-c', '40', '1000000'],
            input=str(n).encode(), capture_output=True, text=True
        )
        if result.stdout.strip():
            p = int(result.stdout.strip().split()[0])
    if p is None:
        print("[-] Factoring failed", flush=True)
        sys.exit(1)

    q = n // p
    assert p * q == n
    if p > q:
        p, q = q, p
    print(f"[+] p = {p}", flush=True)
    print(f"[+] q = {q}", flush=True)

    assert p % 4 == 3
    assert q % 4 == 3
    order_p = p + 1
    order_q = q + 1

    small_primes = sieve_primes(300000)
    factors_p = trial_factor(order_p, small_primes)
    factors_q = trial_factor(order_q, small_primes)
    print(f"[+] p+1 factors: {factors_p}", flush=True)
    print(f"[+] q+1 factors: {factors_q}", flush=True)

    Ap = A_n % p
    Bp_c = B_n % p
    print("[*] Solving ECDLP on E(Fp)...", flush=True)
    s_p = pohlig_hellman(
        (Gx % p, Gy % p), (Qx % p, Qy % p),
        order_p, factors_p, Ap, Bp_c, p
    )
    print(f"[+] s = {s_p} (mod p+1)", flush=True)

    Aq = A_n % q
    Bq_c = B_n % q
    print("[*] Solving ECDLP on E(Fq)...", flush=True)
    s_q = pohlig_hellman(
        (Gx % q, Gy % q), (Qx % q, Qy % q),
        order_q, factors_q, Aq, Bq_c, q
    )
    print(f"[+] s = {s_q} (mod q+1)", flush=True)

    # CRT combination
    g, u, v = extended_gcd(order_p, order_q)
    lcm_val = order_p * order_q // g
    s = (s_p + order_p * ((s_q - s_p) // g) * u) % lcm_val
    print(f"[+] Recovered scalar s = {s}", flush=True)

    # AES-256-CBC decryption
    with open("/app/challenge/key_derivation.json") as f:
        kd = json.load(f)
    iterations = int(kd["pbkdf2_iterations"])

    with open("/app/challenge/encrypted_payload.b64") as f:
        payload_b64 = f.read().strip()
    ciphertext = base64.b64decode(payload_b64)

    result = subprocess.run(
        ['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2',
         '-pass', f'pass:{s}', '-iter', str(iterations)],
        input=ciphertext, capture_output=True
    )
    if result.returncode != 0:
        print(f"[-] Decryption failed: {result.stderr.decode()}", flush=True)
        sys.exit(1)

    plaintext = result.stdout.decode('utf-8')
    print(f"[+] Decrypted: {plaintext}", flush=True)

    with open("/app/solution.txt", "w") as f:
        f.write(plaintext)
    print("[+] Written /app/solution.txt", flush=True)


# =================================================================
# Phase 2: Vulnerability Audit
# =================================================================

def phase2_audit():
    """Write vulnerability assessment and remediation evaluations."""
    audit = {
        "modulus_type": "composite",
        "cm_discriminant": -4,
        "j_invariant": 1728,
        "factoring_method": "williams_p_plus_1",
        "ecdlp_method": "pohlig_hellman",
        "R1_verdict": "INEFFECTIVE",
        "R2_verdict": "EFFECTIVE",
        "R3_verdict": "EFFECTIVE",
        "R4_verdict": "INEFFECTIVE"
    }
    with open("/app/audit.json", "w") as f:
        json.dump(audit, f, indent=2)
    print("[+] Written /app/audit.json", flush=True)


# =================================================================
# Phase 3: Secure Replacement Configuration
# =================================================================

def phase3_secure_config():
    """Generate secure ECC parameters using PARI/GP."""
    print("[*] Generating secure ECC config via PARI/GP...", flush=True)
    result = subprocess.run(
        ['gp', '-q', '/solution/gen_secure_config.gp'],
        capture_output=True, text=True, timeout=120
    )
    lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
    if len(lines) < 6:
        print(f"[-] GP output: {result.stdout}", flush=True)
        print(f"[-] GP stderr: {result.stderr}", flush=True)
        sys.exit(1)

    config = {
        "p": lines[0].strip(),
        "q": lines[1].strip(),
        "a": lines[2].strip(),
        "b": lines[3].strip(),
        "Gx": lines[4].strip(),
        "Gy": lines[5].strip()
    }
    with open("/app/secure_config.json", "w") as f:
        json.dump(config, f, indent=2)
    print(f"[+] Secure config: p={config['p'][:24]}..., q={config['q'][:24]}...",
          flush=True)
    print("[+] Written /app/secure_config.json", flush=True)


# =================================================================

def main():
    phase1_cryptanalysis()
    phase2_audit()
    phase3_secure_config()


if __name__ == "__main__":
    main()
