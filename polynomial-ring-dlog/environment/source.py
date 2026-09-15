#!/usr/bin/env python3
"""
Secure Key Exchange over Polynomial Rings
==========================================
Implements Diffie-Hellman key exchange using polynomial arithmetic
in GF(2)[x] / f(x), where f(x) is a carefully chosen modulus polynomial.

The shared secret is used to derive an AES-CBC encryption key.
"""

import hashlib
import json
import os
import sys

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


# ---------- GF(2) polynomial arithmetic ----------
# Polynomials are represented as Python integers.
# Bit i corresponds to the coefficient of x^i.

def poly_degree(f):
    """Return the degree of polynomial f, or -1 if f == 0."""
    if f == 0:
        return -1
    return f.bit_length() - 1


def poly_mul(f, g):
    """Multiply two GF(2) polynomials."""
    result = 0
    while g:
        if g & 1:
            result ^= f
        f <<= 1
        g >>= 1
    return result


def poly_mod(f, g):
    """Compute f mod g in GF(2)[x]."""
    dg = poly_degree(g)
    if dg < 0:
        raise ZeroDivisionError("division by zero polynomial")
    while True:
        df = poly_degree(f)
        if df < dg:
            return f
        f ^= g << (df - dg)


def poly_mulmod(f, g, m):
    """Compute (f * g) mod m in GF(2)[x]."""
    return poly_mod(poly_mul(f, g), m)


def poly_powmod(base, exp, mod):
    """Compute base^exp mod m in GF(2)[x] using repeated squaring."""
    result = 1
    base = poly_mod(base, mod)
    while exp > 0:
        if exp & 1:
            result = poly_mulmod(result, base, mod)
        exp >>= 1
        base = poly_mulmod(base, base, mod)
    return result


# ---------- Key exchange parameters ----------

# Modulus polynomial f(x) of degree 64 over GF(2)
F_MODULUS = 0x15d38708255efb951

# Generator element g(x) in the ring GF(2)[x] / f(x)
GENERATOR = 0xbdd640fb06671ad3


def generate_keypair():
    """Generate a random private/public key pair."""
    # Private key: random integer
    private = int.from_bytes(os.urandom(8), 'big')
    # Public key: g^private mod f
    public = poly_powmod(GENERATOR, private, F_MODULUS)
    return private, public


def compute_shared_secret(private_key, other_public_key):
    """Compute the shared secret from own private key and other's public key."""
    return poly_powmod(other_public_key, private_key, F_MODULUS)


def derive_aes_key(shared_secret):
    """Derive a 128-bit AES key from the shared secret."""
    secret_bytes = shared_secret.to_bytes(
        (shared_secret.bit_length() + 7) // 8, 'big'
    )
    return hashlib.sha256(secret_bytes).digest()[:16]


def encrypt_message(plaintext, aes_key):
    """Encrypt plaintext using AES-CBC with a random IV."""
    iv = os.urandom(16)
    cipher = AES.new(aes_key, AES.MODE_CBC, iv=iv)
    ciphertext = cipher.encrypt(pad(plaintext, 16))
    return iv, ciphertext


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <plaintext_file>")
        sys.exit(1)

    with open(sys.argv[1], 'rb') as fp:
        plaintext = fp.read()

    # Alice generates her keypair
    priv_a, pub_a = generate_keypair()
    # Bob generates his keypair
    priv_b, pub_b = generate_keypair()

    # Both compute the shared secret
    shared_a = compute_shared_secret(priv_a, pub_b)
    shared_b = compute_shared_secret(priv_b, pub_a)
    assert shared_a == shared_b, "Key exchange failed!"

    # Derive AES key and encrypt
    aes_key = derive_aes_key(shared_a)
    iv, ciphertext = encrypt_message(plaintext, aes_key)

    # Output public parameters and ciphertext
    output = {
        "modulus": hex(F_MODULUS),
        "generator": hex(GENERATOR),
        "public_A": hex(pub_a),
        "public_B": hex(pub_b),
        "iv": iv.hex(),
        "ciphertext": ciphertext.hex(),
    }

    with open("output.json", "w") as fp:
        json.dump(output, fp, indent=2)

    print("Encrypted output written to output.json")


if __name__ == "__main__":
    main()
