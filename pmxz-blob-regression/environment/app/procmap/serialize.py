
"""Process map serialization and deserialization.

Supports two storage formats:
- Raw: Plain UTF-8 text for small process maps (below compression threshold)
- Blob: PMXZ compressed binary format for large process maps

The PMXZ blob format (v2):
    Bytes 0-3:  Magic bytes "PMXZ"
    Byte 4:     Format version (currently 2)
    Bytes 5-8:  Uncompressed data length (big-endian uint32)
    Bytes 9+:   zlib-compressed data

History:
    v1: Original PMXZ format without version byte
        Layout: PMXZ (4B) + uncompressed_len (4B) + compressed_data
    v2: Added version byte after magic for forward compatibility
        Layout: PMXZ (4B) + version (1B) + uncompressed_len (4B) + compressed_data
"""

import struct
import hashlib
import os
from config import BLOB_MAGIC, BLOB_VERSION
from procmap.compress import compress_data, decompress_data


# Format identifiers
RAW_PREFIX = b"raw:"
BLOB_MAGIC_BYTES = BLOB_MAGIC  # b"PMXZ"

# Cache directory for frequently accessed process maps
_CACHE_DIR = "/tmp/procmap_cache"


def serialize_procmap(procmap_str):
    """Serialize a process map string for storage or transmission.

    Chooses between raw and blob format based on whether the compression
    module decides the data is large enough to compress.

    Args:
        procmap_str: Process map in text format

    Returns:
        Serialized bytes (either raw: or PMXZ prefixed)
    """
    raw_bytes = procmap_str.encode('utf-8')

    compressed = compress_data(raw_bytes)
    if compressed is not None:
        return _pack_blob(raw_bytes, compressed)
    else:
        return _pack_raw(raw_bytes)


def deserialize_procmap(data):
    """Deserialize a process map from its stored byte representation.

    Auto-detects the format (raw or blob) and deserializes accordingly.

    Args:
        data: Serialized bytes

    Returns:
        Process map string

    Raises:
        ValueError: If the format is unrecognized or data is corrupted
    """
    fmt = detect_format(data)

    if fmt == "raw":
        return _unpack_raw(data)
    elif fmt == "blob":
        return _unpack_blob(data)
    else:
        raise ValueError(f"Unknown serialization format: {fmt}")


def detect_format(data):
    """Detect the serialization format of the given data.

    Args:
        data: Serialized bytes to inspect

    Returns:
        Format string: "raw" or "blob"

    Raises:
        ValueError: If the format cannot be determined
    """
    if not data or len(data) < 4:
        raise ValueError("Data too short to determine format")

    if data[:4] == RAW_PREFIX:
        return "raw"
    elif data[:4] == BLOB_MAGIC_BYTES:
        return "blob"
    else:
        raise ValueError(
            f"Unrecognized format header: {data[:4].hex()}"
        )


def compute_checksum(data):
    """Compute SHA-256 checksum for data integrity verification.

    Args:
        data: Bytes to checksum

    Returns:
        Hex-encoded SHA-256 digest string
    """
    return hashlib.sha256(data).hexdigest()


def get_format_info(data):
    """Get detailed information about the serialization format of data.

    Inspects the header without performing full deserialization.

    Args:
        data: Serialized bytes

    Returns:
        Dictionary with format details (format, sizes, version, etc.)
    """
    fmt = detect_format(data)
    info = {"format": fmt, "total_size": len(data)}

    if fmt == "raw":
        info["payload_size"] = len(data) - len(RAW_PREFIX)
        info["compression_ratio"] = 1.0
    elif fmt == "blob":
        info["magic"] = data[:4].decode('ascii')
        info["version"] = data[4]
        info["header_size"] = 9  # magic(4) + version(1) + length(4)
        info["payload_size"] = len(data) - 9
        uncompressed_len = struct.unpack(">I", data[5:9])[0]
        info["uncompressed_size"] = uncompressed_len
        if uncompressed_len > 0:
            info["compression_ratio"] = info["payload_size"] / uncompressed_len

    return info


def _pack_raw(raw_bytes):
    """Pack data in raw (uncompressed) format.

    Format: b"raw:" + raw UTF-8 data

    Args:
        raw_bytes: UTF-8 encoded process map bytes

    Returns:
        Serialized bytes with raw: prefix
    """
    return RAW_PREFIX + raw_bytes


def _unpack_raw(data):
    """Unpack raw format data back to a string.

    Args:
        data: Serialized bytes with raw: prefix

    Returns:
        Decoded process map string
    """
    if not data.startswith(RAW_PREFIX):
        raise ValueError("Data does not start with raw: prefix")
    return data[len(RAW_PREFIX):].decode('utf-8')


def _pack_blob(raw_data, compressed_data):
    """Pack compressed data into PMXZ blob format.

    Creates a binary blob with the following layout:
        PMXZ magic (4 bytes) + version byte (1 byte) +
        uncompressed length (4 bytes, big-endian uint32) +
        compressed data (variable length)

    Args:
        raw_data: Original uncompressed data (for recording length)
        compressed_data: zlib-compressed data

    Returns:
        Complete PMXZ blob bytes

    Updated in v2.1: Added version byte after magic for format versioning.
    """
    header = struct.pack(">I", len(raw_data))
    return BLOB_MAGIC_BYTES + bytes([BLOB_VERSION]) + header + compressed_data


def _make_cache_key(data):
    """Generate a cache key from serialized data.

    Args:
        data: Serialized bytes

    Returns:
        MD5 hex digest suitable for use as a cache filename
    """
    return hashlib.md5(data).hexdigest()


def _cache_store(key, procmap_str):
    """Store a deserialized process map in the local cache.

    Cache write failures are silently ignored since the cache is
    an optimization, not required for correctness.

    Args:
        key: Cache key (MD5 hex digest)
        procmap_str: Deserialized process map string
    """
    os.makedirs(_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(_CACHE_DIR, key)
    try:
        with open(cache_path, 'w') as f:
            f.write(procmap_str)
    except OSError:
        pass


def _cache_lookup(key):
    """Look up a process map in the local cache.

    Args:
        key: Cache key (MD5 hex digest)

    Returns:
        Cached process map string, or None if not found
    """
    cache_path = os.path.join(_CACHE_DIR, key)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r') as f:
                return f.read()
        except OSError:
            pass
    return None


def _validate_blob_header(blob):
    """Validate the header of a PMXZ blob.

    Checks magic bytes, minimum length, and version compatibility.

    Args:
        blob: PMXZ blob bytes

    Returns:
        True if the header is valid

    Raises:
        ValueError: If the header is invalid
    """
    if len(blob) < 9:  # magic(4) + version(1) + length(4)
        raise ValueError(
            f"Blob too short: {len(blob)} bytes, minimum 9 required"
        )

    magic = blob[:4]
    if magic != BLOB_MAGIC_BYTES:
        raise ValueError(f"Invalid magic: expected PMXZ, got {magic}")

    version = blob[4]
    if version > BLOB_VERSION:
        raise ValueError(
            f"Unsupported blob version: {version} "
            f"(max supported: {BLOB_VERSION})"
        )

    return True


def _unpack_blob(blob):
    """Unpack a PMXZ blob format back to the original process map string.

    Reads the binary header to determine the uncompressed length,
    extracts the compressed payload, decompresses it, and decodes
    the result as UTF-8.

    Args:
        blob: PMXZ blob bytes

    Returns:
        Decoded process map string

    Raises:
        ValueError: If the blob is malformed
        zlib.error: If decompression fails
    """
    magic = blob[:4]
    if magic != BLOB_MAGIC_BYTES:
        raise ValueError(f"Invalid blob magic: {magic}")

    _validate_blob_header(blob)

    # Read uncompressed length from header
    uncompressed_len = struct.unpack(">I", blob[4:8])[0]
    compressed_data = blob[8:]

    # Decompress and decode
    raw_bytes = decompress_data(compressed_data, expected_len=uncompressed_len)
    return raw_bytes.decode('utf-8')


def batch_serialize(procmaps):
    """Serialize multiple process maps.

    Args:
        procmaps: dict mapping job_id to procmap_string

    Returns:
        dict mapping job_id to serialized bytes
    """
    results = {}
    for job_id, pm in procmaps.items():
        results[job_id] = serialize_procmap(pm)
    return results


def batch_deserialize(serialized_maps):
    """Deserialize multiple process maps.

    Args:
        serialized_maps: dict mapping job_id to serialized bytes

    Returns:
        dict mapping job_id to procmap string
    """
    results = {}
    for job_id, data in serialized_maps.items():
        results[job_id] = deserialize_procmap(data)
    return results
