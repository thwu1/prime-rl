"""
Vault Protocol Implementation
==============================

This module implements the secure vault protocol used to protect the master secret.

Protocol overview:
  1. A master secret S is split into shares using Shamir's (t, n) Secret Sharing
     Scheme over a prime field F_p.
  2. Each share s_i is encrypted using party i's RSA public key via textbook RSA:
     c_i = s_i ^ e_i  (mod N_i)
  3. To recover S, at least t shares must be decrypted and combined via
     Lagrange interpolation.

Key generation was performed by each party independently. The vault operator
collected public keys and encrypted each share. Private keys were never shared.

Security notes:
  - Textbook RSA (no padding) is used for simplicity, as shares are uniformly
    random elements of F_p and thus already have high entropy.
  - Each party was responsible for generating their own RSA key pair with
    adequate security parameters. The vault operator did not audit key quality.
"""

import json
import hashlib


def shamir_split(secret, threshold, num_shares, prime, coefficients):
    """Split secret into shares using Shamir's scheme."""

    def eval_poly(coeffs, x, p):
        result = 0
        for i, c in enumerate(coeffs):
            result = (result + c * pow(x, i, p)) % p
        return result

    shares = []
    for i in range(1, num_shares + 1):
        shares.append((i, eval_poly(coefficients, i, prime)))
    return shares


def shamir_reconstruct(shares, prime):
    """Reconstruct secret from shares using Lagrange interpolation.

    shares: list of (x_i, y_i) tuples
    prime: the prime modulus for the finite field
    """
    secret = 0
    for i, (xi, yi) in enumerate(shares):
        # Compute Lagrange basis polynomial L_i(0)
        numerator = 1
        denominator = 1
        for j, (xj, _) in enumerate(shares):
            if i != j:
                numerator = (numerator * (-xj)) % prime
                denominator = (denominator * (xi - xj)) % prime
        # L_i(0) = numerator / denominator mod prime
        lagrange_coeff = (numerator * pow(denominator, -1, prime)) % prime
        secret = (secret + yi * lagrange_coeff) % prime
    return secret


def rsa_encrypt(message, n, e):
    """Textbook RSA encryption: c = m^e mod n"""
    assert 0 <= message < n
    return pow(message, e, n)


def rsa_decrypt(ciphertext, n, d):
    """Textbook RSA decryption: m = c^d mod n"""
    return pow(ciphertext, d, n)


def load_challenge(filepath="challenge_data.json"):
    """Load challenge data from JSON file."""
    with open(filepath) as f:
        return json.load(f)


def verify_secret(secret_hex, expected_hash):
    """Verify recovered secret against expected hash."""
    computed = hashlib.sha256(secret_hex.encode()).hexdigest()
    return computed == expected_hash
