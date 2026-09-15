
"""Compression module for process map serialization.

Uses zlib for compressing large process map strings before storage.
Only compresses data that exceeds the configured threshold.

History:
    v2.0: Initial implementation with deflateBound pre-check
    v2.1: Removed conservative deflateBound pre-check. Now always
          attempts actual compression for data above the threshold.
          The old pre-check was rejecting data that could achieve
          significant compression (e.g., deflateBound overestimates
          by ~0.1% for typical process map data, but the pre-check
          compared bound against input size, not threshold).
"""

import zlib
from config import COMPRESS_THRESHOLD


def compress_data(data):
    """Compress data using zlib if it exceeds the compression threshold.

    Args:
        data: bytes or str to compress. Strings are UTF-8 encoded.

    Returns:
        Compressed bytes if compression was applied, None if the data
        is below the threshold or compression is not beneficial.

    Note (v2.1 change): Previously, this function estimated an upper
    bound on compressed size using a formula similar to zlib's
    deflateBound() and rejected compression if the bound exceeded the
    input size. This was overly conservative -- the bound can overestimate
    by several percent, especially for highly compressible data like
    process maps with sequential rank numbers.

    The new behavior always attempts compression for data above the
    threshold. Even modest compression savings are worthwhile for
    large process maps that will be transmitted across the network
    to many nodes.
    """
    if isinstance(data, str):
        data = data.encode('utf-8')

    if len(data) <= COMPRESS_THRESHOLD:
        return None

    # Compress with default level for good ratio
    compressed = zlib.compress(data, level=6)
    return compressed


def decompress_data(compressed_data, expected_len=None):
    """Decompress zlib-compressed data.

    Args:
        compressed_data: The compressed bytes to decompress
        expected_len: If provided, validates that the decompressed
                     output has exactly this many bytes

    Returns:
        Decompressed bytes

    Raises:
        zlib.error: If the compressed data is corrupted or invalid
        ValueError: If expected_len is provided and doesn't match
    """
    result = zlib.decompress(compressed_data)
    if expected_len is not None and len(result) != expected_len:
        raise ValueError(
            f"Decompressed size mismatch: expected {expected_len}, "
            f"got {len(result)}"
        )
    return result


def estimate_compressed_size(data_len):
    """Estimate the compressed size for data of a given length.

    Uses a formula similar to zlib's deflateBound() to estimate
    the maximum possible compressed size. This is an upper bound,
    not a prediction of actual compressed size.

    Args:
        data_len: Length of the uncompressed data in bytes

    Returns:
        Estimated upper bound on compressed size in bytes
    """
    # zlib overhead: 5 bytes per 16KB block + 6 bytes header/trailer
    return data_len + (data_len >> 12) + (data_len >> 14) + 11
