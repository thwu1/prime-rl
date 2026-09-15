
"""Configuration for the process map serialization library."""

# Compression threshold in bytes. Process maps larger than this
# will be compressed using zlib and stored in PMXZ blob format.
COMPRESS_THRESHOLD = 4096

# PMXZ blob format constants
BLOB_MAGIC = b"PMXZ"
BLOB_VERSION = 2

# Header overhead for the blob format (magic + version + uint32 length)
HEADER_OVERHEAD = 9  # 4 + 1 + 4
