"""
TEA (Tiny Encryption Algorithm) implementation.

Standard 32-round TEA with 64-bit block and 128-bit key.
Reference: Wheeler & Needham, 1994.
"""

import struct


def tea_encrypt(v, key):
    """
    Encrypt an 8-byte block with a 16-byte key using TEA.

    Args:
        v: bytes (8 bytes) - plaintext block
        key: bytes (16 bytes) - encryption key

    Returns:
        bytes (8 bytes) - ciphertext block
    """
    v0, v1 = struct.unpack('>II', v)
    k = struct.unpack('>IIII', key)
    delta = 0x9E3779B9
    s = 0
    for _ in range(32):
        s = (s + delta) & 0xFFFFFFFF
        v0 = (v0 + (((v1 << 4) + k[0]) ^ (v1 + s) ^ ((v1 >> 5) + k[1]))) & 0xFFFFFFFF
        v1 = (v1 + (((v0 << 4) + k[2]) ^ (v0 + s) ^ ((v0 >> 5) + k[3]))) & 0xFFFFFFFF
    return struct.pack('>II', v0, v1)


def tea_decrypt(v, key):
    """
    Decrypt an 8-byte block with a 16-byte key using TEA.

    Args:
        v: bytes (8 bytes) - ciphertext block
        key: bytes (16 bytes) - decryption key

    Returns:
        bytes (8 bytes) - plaintext block
    """
    v0, v1 = struct.unpack('>II', v)
    k = struct.unpack('>IIII', key)
    delta = 0x9E3779B9
    s = (delta * 32) & 0xFFFFFFFF
    for _ in range(32):
        v1 = (v1 - (((v0 << 4) + k[2]) ^ (v0 + s) ^ ((v0 >> 5) + k[3]))) & 0xFFFFFFFF
        v0 = (v0 - (((v1 << 4) + k[0]) ^ (v1 + s) ^ ((v1 >> 5) + k[1]))) & 0xFFFFFFFF
        s = (s - delta) & 0xFFFFFFFF
    return struct.pack('>II', v0, v1)
