"""
Vitess-compatible VIndex implementation (fixed).
Uses xxHash64 with correct big-endian byte ordering.
"""
import xxhash
import struct


def compute_keyspace_id(value: int) -> bytes:
    """
    Compute the 8-byte keyspace ID for a given integer value using
    the Vitess hash vindex algorithm.

    Protocol:
    1. Pack the input value as a big-endian uint64
    2. Compute xxHash64 of the packed bytes
    3. Pack the hash result as a big-endian uint64

    Args:
        value: The integer value of the sharding column

    Returns:
        8 bytes representing the keyspace ID
    """
    packed = struct.pack('>Q', value)
    hash_val = xxhash.xxh64(packed).intdigest()
    return struct.pack('>Q', hash_val)


def get_shard_for_ksid(ksid: bytes, shard_ranges: list) -> str:
    """
    Determine which shard a keyspace ID belongs to.

    Args:
        ksid: 8-byte keyspace ID
        shard_ranges: List of (start_hex, end_hex) tuples defining shard boundaries.
                     Empty string means unbounded.

    Returns:
        Shard name in the format "start-end"
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
    """Convenience function: compute keyspace ID and return the shard name."""
    ksid = compute_keyspace_id(value)
    return get_shard_for_ksid(ksid, shard_ranges)
