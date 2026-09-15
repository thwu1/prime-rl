#!/usr/bin/env python3
"""
libecc_params.py — Montgomery/Barrett parameter computation tool.

Computes internal representation constants for elliptic curve primes,
following the conventions used by the ANSSI libecc library's
expand_libecc.py curve parameter expansion tooling.

Architecture-dependent values are computed for 64-bit, 32-bit, and
16-bit word sizes. The aligned bit length, Montgomery coefficients,
and Barrett division coefficients depend on the word size.

Usage:
    python3 /challenge/libecc_params.py <prime_hex> [--word-size=64]
    python3 /challenge/libecc_params.py <prime_hex> --all-word-sizes

Examples:
    python3 /challenge/libecc_params.py 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
    python3 /challenge/libecc_params.py 0xF1FD178C0B3AD58F...  --all-word-sizes
"""
# Adapted from ANSSI libecc expand_libecc.py (BSD/GPLv2 dual-licensed)
# Original authors: Ryad BENADJILA, Arnaud EBALARD, Jean-Pierre FLORI

import sys
import json
import argparse


def egcd(b, n):
    x0, x1, y0, y1 = 1, 0, 0, 1
    while n != 0:
        q, b, n = b // n, n, b % n
        x0, x1 = x1, x0 - q * x1
        y0, y1 = y1, y0 - q * y1
    return b, x0, y0


def modinv(a, m):
    g, x, _ = egcd(a, m)
    if g != 1:
        raise ValueError("No modular inverse")
    return x % m


def getbitlen(bint):
    if bint is None or bint == 0:
        return 1 if bint == 0 else 0
    return int(bint).bit_length()


def getbytelen(bint):
    bl = getbitlen(bint)
    return (bl + 7) // 8


def compute_aligned_bitlen(prime, wlen):
    """
    Compute the word-aligned bit length for a prime under a given word size.
    The byte size of the prime is rounded up to the nearest multiple of the
    word size in bytes, then converted back to bits.
    """
    pbitlen = prime.bit_length()
    byte_size = (pbitlen + 7) // 8
    word_bytes = wlen // 8
    if byte_size % word_bytes != 0:
        aligned_bytes = ((byte_size // word_bytes) + 1) * word_bytes
    else:
        aligned_bytes = byte_size
    return aligned_bytes * 8


def compute_monty_coef(prime, pbitlen, wlen):
    """
    Compute Montgomery coefficients r, r^2, and mpinv.
    pbitlen is the aligned bit length (a multiple of word bit size).
    """
    r = (1 << int(pbitlen)) % prime
    r_square = (1 << (2 * int(pbitlen))) % prime
    mpinv = 2**wlen - modinv(prime, 2**wlen)
    return r, r_square, mpinv


def compute_div_coef(prime, pbitlen, wlen):
    """
    Compute Barrett division coefficients: p_shift, p_normalized, p_reciprocal.
    """
    tmp = prime
    cnt = 0
    while tmp != 0:
        tmp >>= 1
        cnt += 1
    pshift = int(pbitlen - cnt)
    primenorm = prime << pshift
    B = 2**wlen
    prec = B**3 // ((primenorm >> int(pbitlen - 2 * wlen)) + 1) - B
    return pshift, primenorm, prec


def compute_params(prime, wlen):
    """Compute all internal parameters for a given prime and word size."""
    abl = compute_aligned_bitlen(prime, wlen)
    r, r_sq, mpinv = compute_monty_coef(prime, abl, wlen)
    p_shift, p_norm, p_recip = compute_div_coef(prime, abl, wlen)
    return {
        "word_size": wlen,
        "aligned_bitlen": abl,
        "r": hex(r),
        "r_squared": hex(r_sq),
        "mpinv": hex(mpinv),
        "p_shift": p_shift,
        "p_normalized": hex(p_norm),
        "p_reciprocal": hex(p_recip),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Compute libecc Montgomery/Barrett internal parameters"
    )
    parser.add_argument("prime", help="Prime in hex (0x-prefixed) or decimal")
    parser.add_argument(
        "--word-size", type=int, default=64, choices=[16, 32, 64],
        help="Word size in bits (default: 64)"
    )
    parser.add_argument(
        "--all-word-sizes", action="store_true",
        help="Compute for all word sizes (16, 32, 64)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON"
    )
    args = parser.parse_args()

    prime_str = args.prime.strip()
    if prime_str.startswith("0x") or prime_str.startswith("0X"):
        prime = int(prime_str, 16)
    else:
        prime = int(prime_str)

    if args.all_word_sizes:
        word_sizes = [16, 32, 64]
    else:
        word_sizes = [args.word_size]

    results = {}
    for ws in word_sizes:
        params = compute_params(prime, ws)
        results[f"{ws}bit"] = params

        if not args.json:
            print(f"=== {ws}-bit word size ===")
            print(f"  aligned_bitlen : {params['aligned_bitlen']}")
            print(f"  r              : {params['r']}")
            print(f"  r_squared      : {params['r_squared']}")
            print(f"  mpinv          : {params['mpinv']}")
            print(f"  p_shift        : {params['p_shift']}")
            print(f"  p_normalized   : {params['p_normalized']}")
            print(f"  p_reciprocal   : {params['p_reciprocal']}")
            print()

    if args.json:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
