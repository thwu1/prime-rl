"""Internal smoke tests for the encryption service.

Run with: python3 -m pytest /app/tests/test_roundtrip.py -v
"""
import sys

sys.path.insert(0, "/app/service")
from crypto import encrypt, decrypt


def test_roundtrip_standard():
    """Round-trip test with standard inputs."""
    key = bytes.fromhex(
        "0101010101010101010101010101010101010101010101010101010101010101"
    )
    nonce = bytes(24)
    pt = b"Hello, encryption service!"
    aad = b"test-aad"
    ct = encrypt(key, nonce, pt, aad)
    assert decrypt(key, nonce, ct, aad) == pt


def test_roundtrip_varied_key():
    """Round-trip with a different key."""
    key = bytes(range(32))
    nonce = bytes(range(24))
    pt = b"another test message for validation"
    ct = encrypt(key, nonce, pt, b"")
    assert decrypt(key, nonce, ct, b"") == pt


def test_roundtrip_empty_plaintext():
    """Round-trip with empty plaintext (tag-only output)."""
    key = bytes([0x42] * 32)
    nonce = bytes([0x55] * 24)
    ct = encrypt(key, nonce, b"", b"aad-only")
    assert len(ct) == 16
    assert decrypt(key, nonce, ct, b"aad-only") == b""


def test_authentication_failure():
    """Verify tampered ciphertext raises error."""
    key = bytes(range(32))
    nonce = bytes(range(24))
    ct = encrypt(key, nonce, b"sensitive data", b"aad")
    tampered = bytearray(ct)
    tampered[0] ^= 0xFF
    try:
        decrypt(key, nonce, bytes(tampered), b"aad")
        assert False, "Should have raised an authentication error"
    except Exception:
        pass
