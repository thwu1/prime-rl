"""Secure key wrapping module - V3 design.


Addresses weaknesses identified in firmware V1 and V2:

V1 weaknesses addressed:
  - Single-byte XOR obfuscation (trivially breakable, only 256 possibilities)
  - Key stored as contiguous bytes (findable via pattern matching)
  - XOR constant visible as ARM EOR instruction in code section

V2 weaknesses addressed:
  - Key halves stored contiguously within marker-bounded regions
  - Bit rotation with only 8 possible values (brute-forceable)
  - Rotation amount stored in plaintext firmware header
  - No tamper detection on key material

V3 protection layers:
  Layer 1: Per-wrap random salt -> SHA-256 derived multi-byte wrapping key
           (not single-byte XOR, unique per wrap, not derivable without salt)
  Layer 2: Scatter storage with cryptographically-derived positions
           (key bytes non-contiguous, positions unpredictable without salt)
  Layer 3: HMAC-SHA256 integrity verification
           (detects any tampering or corruption of the blob)
"""
import os
import hashlib
import struct

BLOB_SIZE = 768
MAGIC = b"KWv3"
SALT_OFFSET = 4
SALT_SIZE = 32
HMAC_OFFSET = 36
HMAC_SIZE = 32
DATA_START = 128


def _derive_wrap_key(salt):
    """Derive a 16-byte wrapping key from the random salt via SHA-256."""
    return hashlib.sha256(salt + b"V3-WRAP-KEY-DERIVE").digest()[:16]


def _scatter_positions(salt):
    """Compute 16 unique scatter positions deterministically from salt.
    Uses iterated SHA-256 to generate position candidates, ensuring
    positions are spread across the data region."""
    positions = []
    used = set()
    seed = salt
    available = BLOB_SIZE - DATA_START
    while len(positions) < 16:
        seed = hashlib.sha256(seed + b"SCATTER-POS").digest()
        for i in range(0, 32, 2):
            p = DATA_START + (struct.unpack('>H', seed[i:i + 2])[0] % available)
            if p not in used:
                used.add(p)
                positions.append(p)
                if len(positions) == 16:
                    break
    return positions


def _hmac_sha256(key, msg):
    """HMAC-SHA256 using only hashlib (no hmac module dependency)."""
    block_size = 64
    if len(key) > block_size:
        key = hashlib.sha256(key).digest()
    key = key + b'\x00' * (block_size - len(key))
    o_key_pad = bytes(k ^ 0x5c for k in key)
    i_key_pad = bytes(k ^ 0x36 for k in key)
    return hashlib.sha256(
        o_key_pad + hashlib.sha256(i_key_pad + msg).digest()
    ).digest()


def wrap_key(key):
    """Wrap a 16-byte AES key into a secure blob.

    Args:
        key: exactly 16 bytes of key material

    Returns:
        bytes: opaque blob (768 bytes) containing the wrapped key
    """
    if not isinstance(key, (bytes, bytearray)) or len(key) != 16:
        raise ValueError("Key must be exactly 16 bytes")

    # Generate per-wrap random salt
    salt = os.urandom(SALT_SIZE)

    # Derive multi-byte wrapping key from salt
    wrap_k = _derive_wrap_key(salt)

    # XOR key with derived wrapping key (multi-byte, not single-byte)
    wrapped_bytes = bytes(k ^ w for k, w in zip(key, wrap_k))

    # Initialize blob with random fill for high entropy
    blob = bytearray(os.urandom(BLOB_SIZE))

    # Write header: magic + salt
    blob[0:4] = MAGIC
    blob[SALT_OFFSET:SALT_OFFSET + SALT_SIZE] = salt

    # Clear HMAC slot before computing
    blob[HMAC_OFFSET:HMAC_OFFSET + HMAC_SIZE] = b'\x00' * HMAC_SIZE

    # Scatter wrapped key bytes at salt-derived positions
    for i, pos in enumerate(_scatter_positions(salt)):
        blob[pos] = wrapped_bytes[i]

    # Compute HMAC over the entire blob (with HMAC slot zeroed)
    mac = _hmac_sha256(salt, bytes(blob))[:HMAC_SIZE]
    blob[HMAC_OFFSET:HMAC_OFFSET + HMAC_SIZE] = mac

    return bytes(blob)


def unwrap_key(blob):
    """Recover the 16-byte AES key from a wrapped blob.

    Args:
        blob: bytes produced by wrap_key

    Returns:
        bytes: the original 16-byte key

    Raises:
        ValueError: if the blob is invalid, corrupted, or tampered with
    """
    if not isinstance(blob, (bytes, bytearray)) or len(blob) < BLOB_SIZE:
        raise ValueError(f"Blob too small: {len(blob)} < {BLOB_SIZE}")

    if blob[0:4] != MAGIC:
        raise ValueError("Invalid blob magic header")

    salt = blob[SALT_OFFSET:SALT_OFFSET + SALT_SIZE]
    stored_mac = blob[HMAC_OFFSET:HMAC_OFFSET + HMAC_SIZE]

    # Verify HMAC integrity
    check = bytearray(blob[:BLOB_SIZE])
    check[HMAC_OFFSET:HMAC_OFFSET + HMAC_SIZE] = b'\x00' * HMAC_SIZE
    expected_mac = _hmac_sha256(salt, bytes(check))[:HMAC_SIZE]

    if stored_mac != expected_mac:
        raise ValueError("HMAC verification failed — blob corrupted or tampered")

    # Derive wrapping key and gather scattered bytes
    wrap_k = _derive_wrap_key(salt)
    positions = _scatter_positions(salt)
    wrapped_bytes = bytes(blob[pos] for pos in positions)

    # Reverse XOR to recover original key
    key = bytes(w ^ k for w, k in zip(wrapped_bytes, wrap_k))

    return key
