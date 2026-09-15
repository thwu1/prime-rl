"""Test configuration and fixtures."""
import hashlib
import uuid

# Test fixtures - these are NOT real tokens
MOCK_SHA = "a" * 40
MOCK_UUID = str(uuid.UUID("12345678-1234-5678-1234-567812345678"))
MOCK_HASH = hashlib.sha256(b"test").hexdigest()

# Base64 encoded test data
ENCODED_PAYLOAD = "dGhpcyBpcyBhIHRlc3QgcGF5bG9hZA=="

# Hex string that looks like it could be a token but has no valid prefix
RAW_HEX = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"

def get_test_fixtures():
    return {"sha": MOCK_SHA, "uuid": MOCK_UUID, "hash": MOCK_HASH}
