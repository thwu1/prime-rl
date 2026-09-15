"""Low-level cryptographic primitives for CTR-DRBG."""

from Crypto.Cipher import AES


def bytes_xor(a, b):
    """XOR two byte strings (truncates to shorter length)."""
    return bytes(x ^ y for x, y in zip(a, b))


def increment_counter(V):
    """Increment a big-endian counter block by 1 mod 2^(len*8)."""
    val = int.from_bytes(V, "big")
    val = (val + 1) % (1 << (len(V) * 8))
    return val.to_bytes(len(V), "big")


def block_encrypt(key, plaintext):
    """AES ECB single-block encryption."""
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(plaintext)
