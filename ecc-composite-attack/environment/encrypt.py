#!/usr/bin/env python3
"""
ECC-AES Encryption Pipeline.

This script shows the full encryption chain used to produce the challenge:

Stage 1 — ECC Key Exchange over Z/nZ:
  - n = p * q (composite, both primes secret)
  - Curve: y^2 = x^3 + A*x^2 + B*x + C  (mod n)
  - Secret scalar s chosen, public key Q = s * G published
  - The curve is a disguised form of y^2 = x^3 + x (j-invariant 1728,
    CM by Z[i]) obtained via x -> x - A/3. For primes p ≡ 3 (mod 4),
    the curve order is p+1.

Stage 2 — AES Encryption:
  - Password = decimal string representation of s
  - Encryption: openssl enc -aes-256-cbc -pbkdf2 -iter 600000
                -pass pass:<DECIMAL_s>
  - Output format: OpenSSL Salted__ (8-byte magic + 8-byte salt + ciphertext)
  - Base64-encoded as encrypted_payload.b64

To decrypt: recover s from the ECC system, then use it as the openssl password.
"""

import json


# --- ECC arithmetic on generalized Weierstrass curve ---
# y^2 = x^3 + A*x^2 + B*x + C (mod n)

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


def ec_add(P, Q, A, B, n):
    """Point addition on y^2 = x^3 + A*x^2 + B*x + C (mod n)."""
    if P is None:
        return Q
    if Q is None:
        return P
    px, py = P
    qx, qy = Q
    if px == qx:
        if (py + qy) % n == 0:
            return None
        num = (3 * px * px + 2 * A * px + B) % n
        den = (2 * py) % n
    else:
        num = (qy - py) % n
        den = (qx - px) % n
    inv = modinv(den, n)
    if inv is None:
        raise ValueError("Modular inverse failed")
    lam = (num * inv) % n
    x3 = (lam * lam - A - px - qx) % n
    y3 = (lam * (px - x3) - py) % n
    return (x3, y3)


def ec_mul(k, P, A, B, n):
    """Double-and-add scalar multiplication."""
    result = None
    temp = P
    while k > 0:
        if k & 1:
            result = ec_add(result, temp, A, B, n)
        temp = ec_add(temp, temp, A, B, n)
        k >>= 1
    return result


def show_pipeline():
    """Display the encryption pipeline (secret values redacted)."""
    with open("/app/challenge/public_params.json") as f:
        params = json.load(f)

    n = int(params["n"])
    A = int(params["A"])
    B = int(params["B"])
    C = int(params["C"])

    print(f"Modulus n = {n}")
    print(f"  n has {n.bit_length()} bits")
    print(f"  n is {'NOT prime (composite)' if n > 2 else 'prime'}")
    print()
    print(f"Curve: y^2 = x^3 + A*x^2 + B*x + C (mod n)")
    print(f"  A = {A}")
    print(f"  B = {B}")
    print(f"  C = {C}")
    print()
    print("Pipeline:")
    print("  1. Factor n into primes p, q")
    print("  2. Reduce curve mod p and mod q")
    print("  3. Solve ECDLP: find s such that Q = s*G on each reduced curve")
    print("  4. Combine via CRT to recover s")
    print("  5. Use decimal(s) as OpenSSL password to decrypt the payload")
    print()
    print("AES parameters:")
    print("  Cipher:     AES-256-CBC")
    print("  KDF:        PBKDF2 (SHA-256)")
    print("  Iterations: 600000")
    print("  Password:   str(s)  (decimal representation of the scalar)")


if __name__ == "__main__":
    show_pipeline()
