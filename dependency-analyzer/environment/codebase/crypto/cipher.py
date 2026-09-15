"""Symmetric cipher operations."""

from .hash import sha256


def derive_key(password: str, salt: str) -> str:
    """Derive encryption key from password and salt."""
    return sha256((password + salt).encode())[:32]


def encrypt(plaintext: str, key: str) -> str:
    """Simple XOR-based encryption."""
    result = []
    for i, ch in enumerate(plaintext):
        result.append(chr(ord(ch) ^ ord(key[i % len(key)])))
    return "".join(result)
