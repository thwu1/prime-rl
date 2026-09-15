"""Hybrid vindex router module.

Implements the Vitess DES null-key hash algorithm and a hybrid routing
strategy that uses SQLite for legacy IDs and hash-based routing for new IDs.
"""

import json
import os
import sqlite3
import struct

from Crypto.Cipher import DES

# ---------------------------------------------------------------------------
# DES null-key cipher (matches Vitess: des.NewCipher(make([]byte, 8)))
# ---------------------------------------------------------------------------
_DES_CIPHER = DES.new(b"\x00" * 8, DES.MODE_ECB)

# ---------------------------------------------------------------------------
# Load configuration
# ---------------------------------------------------------------------------
_APP_DIR = "/app"

with open(os.path.join(_APP_DIR, "shard_config.json")) as _f:
    _SHARD_CONFIG = json.load(_f)

with open(os.path.join(_APP_DIR, "table_config.json")) as _f:
    _TABLE_CONFIG = json.load(_f)

# Parse shard boundaries from hex strings
_SHARD_BOUNDARIES = []
for sr in _SHARD_CONFIG["shard_ranges"]:
    end_hex = sr["end"]
    if end_hex:
        _SHARD_BOUNDARIES.append(int(end_hex, 16))
# Result for 8 equal shards: [0x20, 0x40, 0x60, 0x80, 0xa0, 0xc0, 0xe0]

# Legacy SQLite connection (read-only)
_LEGACY_DB = sqlite3.connect(
    "file:" + os.path.join(_APP_DIR, "legacy_mappings.db") + "?mode=ro",
    uri=True,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def vhash(shard_key: int) -> bytes:
    """Compute the Vitess hash vindex keyspace ID for an integer shard key.

    Matches the Go implementation:
      1. Cast to uint64 (preserving bit pattern for negative int64 values)
      2. Encode as 8 big-endian bytes
      3. Encrypt with DES using a null (all-zeros) 8-byte key (single block, ECB)
    """
    shard_key = shard_key & 0xFFFFFFFFFFFFFFFF
    key_bytes = struct.pack(">Q", shard_key)
    return _DES_CIPHER.encrypt(key_bytes)


def _keyspace_id_to_shard(ksid: bytes) -> int:
    """Map an 8-byte keyspace ID to a shard number using first-byte comparison."""
    first_byte = ksid[0]
    for i, boundary in enumerate(_SHARD_BOUNDARIES):
        if first_byte < boundary:
            return i
    return len(_SHARD_BOUNDARIES)


def route_id(table_name: str, record_id: int) -> int:
    """Route a record to a shard using the hybrid vindex strategy.

    - IDs <= threshold: lookup in legacy SQLite database
    - IDs >  threshold: compute via hash vindex algorithm
    """
    config = _TABLE_CONFIG[table_name]
    threshold = config["threshold"]

    if record_id <= threshold:
        cursor = _LEGACY_DB.cursor()
        cursor.execute(
            "SELECT shard_number FROM shard_map "
            "WHERE table_name = ? AND record_id = ?",
            (table_name, record_id),
        )
        row = cursor.fetchone()
        if row is not None:
            return row[0]
        # Fallback to hash if legacy mapping is missing

    ksid = vhash(record_id)
    return _keyspace_id_to_shard(ksid)
