"""Vitess-compatible hash vindex implementation.

This module provides the keyspace ID computation used for shard routing.
The keyspace_id is an 8-byte binary value derived from the sharding key
(channel_id) using MD5 hashing. Shard routing is determined by comparing
the keyspace_id against shard key ranges using left-justified binary
comparison (Vitess convention).

Key range notation:
  - "-80" means keyspace_id < 0x80 (first byte < 0x80)
  - "80-c0" means 0x80 <= first byte < 0xc0
  - "c0-" means first byte >= 0xc0

The range boundaries are hex strings representing the START of the byte
range, zero-padded to 8 bytes on the right for comparison.
"""

import hashlib
import struct


def compute_keyspace_id(sharding_key: int) -> bytes:
    """Compute 8-byte keyspace ID from a sharding key (e.g., channel_id).

    Uses MD5 hash of the big-endian 8-byte representation of the key,
    then takes the first 8 bytes as the keyspace_id.
    """
    key_bytes = struct.pack('>Q', sharding_key)
    h = hashlib.md5(key_bytes).digest()
    return h[:8]


def hex_to_range_bound(hex_str: str) -> bytes:
    """Convert a hex range boundary string to an 8-byte comparison value.

    Empty string represents the minimum (all zeros) or maximum value
    depending on context:
    - As a start bound: b'\\x00' * 8
    - As an end bound: should be treated as "infinity" (greater than all values)
    """
    if not hex_str:
        return b'\x00' * 8
    padded = hex_str.ljust(16, '0')
    return bytes.fromhex(padded)


def keyspace_id_in_range(keyspace_id: bytes, range_start: str, range_end: str) -> bool:
    """Check if a keyspace_id falls within a shard's key range.

    Args:
        keyspace_id: 8-byte keyspace ID
        range_start: Hex string for range start (empty = minimum)
        range_end: Hex string for range end (empty = maximum/infinity)

    Returns:
        True if keyspace_id is in [range_start, range_end)
    """
    start = hex_to_range_bound(range_start)
    if range_end == '':
        return keyspace_id >= start
    end = hex_to_range_bound(range_end)
    return start <= keyspace_id < end
