#!/usr/bin/env python3
"""
CryptoExchange Protocol v1.0
=============================
Custom key exchange protocol using Diffie-Hellman over the polynomial ring
GF(2)[x] / f(x), where f(x) is a degree-64 modulus polynomial.

Wire Format
-----------
Each message is framed as:

    [2 bytes magic: 0xCE 0xFF]
    [1 byte  type]
    [2 bytes payload length, big-endian]
    [payload bytes]

Message Types
~~~~~~~~~~~~~
  0x01  INIT        : [1B version]
  0x02  PARAMS      : [9B modulus polynomial, big-endian] [8B generator polynomial, big-endian]
  0x03  PUBKEY_A    : [8B public_key_A, big-endian]
  0x04  PUBKEY_B    : [8B public_key_B, big-endian]
  0x05  ENCRYPTED   : [16B IV] [4B ciphertext_len, big-endian] [ciphertext bytes]

Conversation Flow (over TCP, default port 31337)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  Client -> Server : INIT       (version=1)
  Server -> Client : PARAMS     (modulus, generator)
  Client -> Server : PUBKEY_A   (g^a mod f)
  Server -> Client : PUBKEY_B   (g^b mod f)
  Server -> Client : ENCRYPTED  (iv, ciphertext)

Key Derivation
~~~~~~~~~~~~~~
  shared_secret = other_public ^ own_private  mod  modulus   (GF(2)[x] exponentiation)
  shared_bytes  = shared_secret encoded as big-endian bytes (minimal length, no leading zero bytes)
  aes_key       = SHA-256(shared_bytes)[:16]                 (first 16 bytes)

Encryption
~~~~~~~~~~
  AES-128-CBC with PKCS#7 padding.

GF(2) Polynomial Representation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  Polynomials are stored as Python integers.
  Bit i of the integer represents the coefficient of x^i.
  Example: x^3 + x + 1  =  0b1011  =  11
"""

import hashlib
import os
import struct
import sys

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad


# ── Protocol constants ──

MAGIC        = b'\xCE\xFF'
MSG_INIT      = 0x01
MSG_PARAMS    = 0x02
MSG_PUBKEY_A  = 0x03
MSG_PUBKEY_B  = 0x04
MSG_ENCRYPTED = 0x05


# ── GF(2) polynomial arithmetic ──

def poly_degree(f):
    """Degree of polynomial f, or -1 if f == 0."""
    if f == 0:
        return -1
    return f.bit_length() - 1


def poly_mul(f, g):
    """Multiply two GF(2) polynomials (schoolbook)."""
    result = 0
    while g:
        if g & 1:
            result ^= f
        f <<= 1
        g >>= 1
    return result


def poly_mod(f, g):
    """Reduce f modulo g in GF(2)[x]."""
    dg = poly_degree(g)
    if dg < 0:
        raise ZeroDivisionError("polynomial division by zero")
    while True:
        df = poly_degree(f)
        if df < dg:
            return f
        f ^= g << (df - dg)


def poly_mulmod(f, g, m):
    """Compute (f * g) mod m in GF(2)[x]."""
    return poly_mod(poly_mul(f, g), m)


def poly_powmod(base, exp, mod):
    """Compute base^exp mod m via repeated squaring in GF(2)[x]."""
    result = 1
    base = poly_mod(base, mod)
    while exp > 0:
        if exp & 1:
            result = poly_mulmod(result, base, mod)
        exp >>= 1
        base = poly_mulmod(base, base, mod)
    return result


# ── Message framing ──

def make_message(msg_type, payload):
    """Build a framed protocol message."""
    return MAGIC + struct.pack('!BH', msg_type, len(payload)) + payload


def parse_messages(data):
    """Parse a byte stream into a list of (type, payload) tuples."""
    messages = []
    offset = 0
    while offset + 5 <= len(data):
        if data[offset:offset + 2] != MAGIC:
            raise ValueError(f"bad magic at offset {offset}: {data[offset:offset+2].hex()}")
        msg_type = data[offset + 2]
        length = struct.unpack('!H', data[offset + 3:offset + 5])[0]
        payload = data[offset + 5:offset + 5 + length]
        messages.append((msg_type, payload))
        offset += 5 + length
    return messages


# ── Key exchange logic ──

class KeyExchangeParty:
    def __init__(self, modulus, generator):
        self.modulus = modulus
        self.generator = generator
        self.private_key = int.from_bytes(os.urandom(8), 'big')
        self.public_key = poly_powmod(generator, self.private_key, modulus)

    def compute_shared_secret(self, other_public):
        return poly_powmod(other_public, self.private_key, self.modulus)

    def derive_aes_key(self, shared_secret):
        sb = shared_secret.to_bytes((shared_secret.bit_length() + 7) // 8, 'big')
        return hashlib.sha256(sb).digest()[:16]

    def encrypt(self, plaintext, aes_key):
        iv = os.urandom(16)
        cipher = AES.new(aes_key, AES.MODE_CBC, iv=iv)
        return iv, cipher.encrypt(pad(plaintext, 16))

    def decrypt(self, ciphertext, iv, aes_key):
        cipher = AES.new(aes_key, AES.MODE_CBC, iv=iv)
        return unpad(cipher.decrypt(ciphertext), 16)
