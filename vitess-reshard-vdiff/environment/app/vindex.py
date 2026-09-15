"""
Vitess-compatible VIndex implementation.
Maps column values to keyspace IDs for shard routing.

A keyspace ID is an 8-byte value that determines which shard a row belongs to.
The hash vindex computes a deterministic hash of the sharding column value
to produce a uniformly distributed keyspace ID.
"""
import hashlib
import struct


def compute_keyspace_id(value: int) -> bytes:
    """
    Compute the 8-byte keyspace ID for a given integer value using the hash vindex.

    The keyspace ID determines which shard a row is routed to. It must produce
    a uniform distribution across the keyspace ID space [0, 2^64).

    Args:
        value: The integer value of the sharding column (e.g., workspace_id)

    Returns:
        8 bytes representing the keyspace ID
    """
    value_bytes = struct.pack('<Q', value)
    digest = hashlib.sha256(value_bytes).digest()
    return digest[:8]


def get_shard_for_ksid(ksid: bytes, shard_ranges: list) -> str:
    """
    Determine which shard a keyspace ID belongs to.

    Args:
        ksid: 8-byte keyspace ID
        shard_ranges: List of (start_hex, end_hex) tuples defining shard boundaries.
                     Empty string means unbounded (start="" means minimum, end="" means maximum).
                     Example: [("", "80"), ("80", "")] for a 2-shard setup.

    Returns:
        Shard name in the format "start-end" (e.g., "-80", "80-", "40-80")
    """
    ksid_int = struct.unpack('>Q', ksid)[0]

    for start_hex, end_hex in shard_ranges:
        if start_hex:
            start_int = int(start_hex, 16) << (64 - len(start_hex) * 4)
        else:
            start_int = 0

        if end_hex:
            end_int = int(end_hex, 16) << (64 - len(end_hex) * 4)
        else:
            end_int = (1 << 64)

        if start_int <= ksid_int < end_int:
            return f"{start_hex}-{end_hex}"

    raise ValueError(f"No shard found for keyspace ID: {ksid.hex()}")


def get_shard_for_value(value: int, shard_ranges: list) -> str:
    """
    Convenience function: compute keyspace ID and return the shard name.
    """
    ksid = compute_keyspace_id(value)
    return get_shard_for_ksid(ksid, shard_ranges)
