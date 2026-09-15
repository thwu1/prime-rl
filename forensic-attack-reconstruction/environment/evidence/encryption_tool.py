#!/usr/bin/env python3
"""Secure file encryption utility v2.1 - custom stream cipher implementation."""
import hashlib
import os
import sys
import struct
import argparse


def kdf(seed, iterations=50000):
    """PBKDF-inspired key derivation with SHA-512 iterative hashing."""
    dk = hashlib.sha512(seed.encode('utf-8')).digest()
    for _ in range(iterations):
        dk = hashlib.sha512(dk).digest()
    return dk[:32]


def crypt(data, key):
    """CTR-mode stream cipher encryption. Nonce is prepended to output."""
    result = bytearray()
    nonce = os.urandom(12)
    for i in range(0, len(data), 32):
        counter_block = nonce + struct.pack('>I', i // 32)
        keystream = hashlib.sha256(key + counter_block).digest()
        chunk = data[i:i + 32]
        result.extend(b ^ k for b, k in zip(chunk, keystream[:len(chunk)]))
    return nonce + bytes(result)


def decrypt(data, key):
    """CTR-mode stream cipher decryption. Reads nonce from first 12 bytes."""
    nonce = data[:12]
    ciphertext = data[12:]
    result = bytearray()
    for i in range(0, len(ciphertext), 32):
        counter_block = nonce + struct.pack('>I', i // 32)
        keystream = hashlib.sha256(key + counter_block).digest()
        chunk = ciphertext[i:i + 32]
        result.extend(b ^ k for b, k in zip(chunk, keystream[:len(chunk)]))
    return bytes(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='File encryption/decryption utility')
    parser.add_argument('--mode', choices=['encrypt', 'decrypt'], required=True,
                        help='Operation mode')
    parser.add_argument('--seed', required=True,
                        help='Passphrase for key derivation')
    parser.add_argument('--input', required=True,
                        help='Input file path')
    parser.add_argument('--output', required=True,
                        help='Output file path')
    args = parser.parse_args()

    key = kdf(args.seed)

    with open(args.input, 'rb') as f:
        data = f.read()

    if args.mode == 'encrypt':
        result = crypt(data, key)
    else:
        result = decrypt(data, key)

    with open(args.output, 'wb') as f:
        f.write(result)

    print(f"[+] {args.mode}ion complete: {args.output} ({len(result)} bytes)")
