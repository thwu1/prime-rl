#!/usr/bin/env python3
"""
AES-128-CMAC (RFC 4493) implementation.

This module provides a correct implementation of AES-128-CMAC as specified
in RFC 4493. It is the ONLY cryptographic primitive provided for the task.
All higher-level operations (KDF, MAC computation) must be built on top.
"""

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def _aes128_encrypt(key, block):
    """Encrypt a single 16-byte block with AES-128 in ECB mode."""
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(block) + encryptor.finalize()


def _left_shift_one(data):
    """Left-shift a 16-byte string by 1 bit."""
    result = bytearray(16)
    overflow = 0
    for i in range(15, -1, -1):
        result[i] = ((data[i] << 1) | overflow) & 0xFF
        overflow = 1 if (data[i] & 0x80) else 0
    return bytes(result)


def _xor_bytes(a, b):
    """XOR two equal-length byte strings."""
    return bytes(x ^ y for x, y in zip(a, b))


def _cmac_generate_subkeys(key):
    """Generate CMAC subkeys K1, K2 from AES key per RFC 4493 Section 2.3."""
    CONST_ZERO = b'\x00' * 16
    CONST_RB = b'\x00' * 15 + b'\x87'

    L = _aes128_encrypt(key, CONST_ZERO)

    if (L[0] & 0x80) == 0:
        K1 = _left_shift_one(L)
    else:
        K1 = _xor_bytes(_left_shift_one(L), CONST_RB)

    if (K1[0] & 0x80) == 0:
        K2 = _left_shift_one(K1)
    else:
        K2 = _xor_bytes(_left_shift_one(K1), CONST_RB)

    return K1, K2


def aes_128_cmac(key, message):
    """Compute AES-128-CMAC per RFC 4493.

    Args:
        key: 16-byte AES key
        message: variable-length message bytes

    Returns:
        16-byte MAC value
    """
    assert len(key) == 16, f"AES-128-CMAC requires 16-byte key, got {len(key)}"
    K1, K2 = _cmac_generate_subkeys(key)

    n = max((len(message) + 15) // 16, 1)

    if len(message) == 0:
        flag = False
    else:
        flag = (len(message) % 16 == 0)

    if flag:
        M_last = _xor_bytes(message[(n - 1) * 16 : n * 16], K1)
    else:
        last_block = message[(n - 1) * 16:]
        padding_len = 16 - len(last_block)
        padded = last_block + b'\x80' + b'\x00' * (padding_len - 1)
        M_last = _xor_bytes(padded, K2)

    X = b'\x00' * 16
    for i in range(n - 1):
        Y = _xor_bytes(X, message[i * 16 : (i + 1) * 16])
        X = _aes128_encrypt(key, Y)

    Y = _xor_bytes(X, M_last)
    return _aes128_encrypt(key, Y)
