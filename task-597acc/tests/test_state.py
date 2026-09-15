
import hashlib
import os


# SHA-256 of the correct 16-byte AES key
EXPECTED_HASH = "12690650b9813840d8851dd495929a34cd2dd65101cc58b1ee8b39c7c2adeaa6"


def test_recovered_key_exists():
    """The recovered key file must exist."""
    assert os.path.exists("/app/recovered_key.hex"), \
        "recovered_key.hex not found at /app/recovered_key.hex"


def test_recovered_key_format():
    """The key must be a valid 32-character lowercase hex string."""
    with open("/app/recovered_key.hex", "r") as f:
        hex_str = f.read().strip().lower()
    assert len(hex_str) == 32, \
        f"Expected 32 hex characters, got {len(hex_str)}"
    assert all(c in "0123456789abcdef" for c in hex_str), \
        "Invalid hex characters in key"


def test_recovered_key_correct():
    """The recovered key must match the expected SHA-256 hash."""
    with open("/app/recovered_key.hex", "r") as f:
        hex_str = f.read().strip().lower()
    key_bytes = bytes.fromhex(hex_str)
    assert len(key_bytes) == 16, \
        f"Expected 16 bytes, got {len(key_bytes)}"
    actual_hash = hashlib.sha256(key_bytes).hexdigest()
    assert actual_hash == EXPECTED_HASH, \
        "Recovered key does not match expected value"
