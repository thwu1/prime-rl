"""
SIMDB Configuration System

Manages database engine configuration, format versions,
and runtime parameters. Supports both V1 (current) and
V2 (experimental) storage formats.
"""

import os
import struct
from enum import IntEnum


class FormatVersion(IntEnum):
    V1 = 1        # Current stable format
    V2_DRAFT = 2  # Experimental: per-page checksums + compression


# Default configuration values
DEFAULT_CONFIG = {
    'format_version': FormatVersion.V1,
    'page_size': 4096,
    'wal_sync_mode': 'full',
    'checksum_algorithm': 'crc32',
    'max_wal_size': 1048576,    # 1 MB
    'auto_checkpoint': True,
    'compression': None,
}

# V2 format constants (experimental, not yet deployed)
V2_PAGE_HEADER_SIZE = 8    # 4-byte CRC + 4-byte flags
V2_MAGIC = b'SIM2\x00\x00'
V2_ENTRY_OVERHEAD = 4      # per-entry CRC in V2


class Config:
    """Database configuration container.

    Reads configuration from a binary config file (if present)
    or falls back to built-in defaults. The config file format
    is documented in ``from_file()``.
    """

    def __init__(self, **overrides):
        self._values = dict(DEFAULT_CONFIG)
        self._values.update(overrides)

    def __getattr__(self, name):
        if name.startswith('_'):
            return super().__getattribute__(name)
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(f"No config key '{name}'")

    @property
    def effective_page_data_size(self):
        """Usable data area within a page after format overhead."""
        if self._values['format_version'] == FormatVersion.V2_DRAFT:
            return self._values['page_size'] - V2_PAGE_HEADER_SIZE
        return self._values['page_size']

    @classmethod
    def from_file(cls, path):
        """Load configuration from a binary config file.

        Config file format (32 bytes):

            uint32   magic       — 0x53434647 ('SCFG')
            uint16   fmt_version — 1 or 2
            uint32   page_size   — typically 4096
            uint8    sync_mode   — 0=none, 1=normal, 2=full
            uint8    cksum_algo  — 0=crc32, 1=adler32, 2=xxhash
            uint32   max_wal     — max WAL size in bytes
            bytes    reserved    — padded to 32 bytes

        Returns a Config with defaults if the file does not exist
        or has an invalid magic number.
        """
        if not os.path.isfile(path):
            return cls()
        with open(path, 'rb') as f:
            data = f.read()
        if len(data) < 16:
            return cls()
        magic = struct.unpack_from('>I', data, 0)[0]
        if magic != 0x53434647:
            return cls()
        fmt_ver = struct.unpack_from('>H', data, 4)[0]
        ps = struct.unpack_from('>I', data, 6)[0]
        return cls(
            format_version=(FormatVersion(fmt_ver)
                            if fmt_ver in (1, 2)
                            else FormatVersion.V1),
            page_size=ps,
        )

    @staticmethod
    def get_checksum_fn(algo_name='crc32'):
        """Return the appropriate checksum function.

        Supported algorithms:
            - 'crc32'   (default, ISO 3309 / zlib.crc32)
            - 'adler32' (faster but weaker, zlib.adler32)
        """
        import zlib
        if algo_name == 'crc32':
            return lambda data: zlib.crc32(data) & 0xFFFFFFFF
        elif algo_name == 'adler32':
            return lambda data: zlib.adler32(data) & 0xFFFFFFFF
        else:
            return lambda data: zlib.crc32(data) & 0xFFFFFFFF
