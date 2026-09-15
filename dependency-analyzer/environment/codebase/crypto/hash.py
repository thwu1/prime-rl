"""Hash functions for cryptographic operations."""

import hashlib


def sha256(data: bytes) -> str:
    """Compute SHA-256 hash of data."""
    return hashlib.sha256(data).hexdigest()


def md5(data: bytes) -> str:
    """Compute MD5 hash of data."""
    return hashlib.md5(data).hexdigest()
