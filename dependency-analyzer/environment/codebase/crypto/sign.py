"""Digital signature operations."""

from .cipher import derive_key, encrypt
from .hash import sha256


def sign(message: str, private_key: str) -> str:
    """Create a signature for a message."""
    key = derive_key(private_key, "sign_salt")
    msg_hash = sha256(message.encode())
    return encrypt(msg_hash, key)


def verify(message: str, signature: str, private_key: str) -> bool:
    """Verify a message signature."""
    expected = sign(message, private_key)
    return expected == signature
