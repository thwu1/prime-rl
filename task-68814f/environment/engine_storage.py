"""
SIMDB Storage Engine -- binary database file handling.

This module implements the on-disk format for SIMDB database files,
including page serialization, header management, and checksum computation.

Supported format versions:
  - V1 (current): Fixed-size pages with sequential KV entries
  - V2 (experimental): Pages with per-page CRC and flags field
                        (see engine/config.py for V2 constants)

The storage engine uses CRC-32 checksums for integrity verification.
The header checksum covers all serialized page data concatenated in
page order.
"""

import os
import struct
import zlib
from typing import Dict, List, Optional, Tuple

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

DB_MAGIC = b'SIMDB\x00'
DB_FORMAT_VERSION = 1
DEFAULT_PAGE_SIZE = 4096

# Header layout: magic(6) + version(2) + page_size(4) + page_count(4)
#                + checksum(4) + reserved(12) = 32 bytes total
_HEADER_FMT = '>6sHIII'
_HEADER_PACKED_SIZE = struct.calcsize(_HEADER_FMT)   # 20
HEADER_TOTAL_SIZE = 32   # includes reserved padding

_ENTRY_HDR_FMT = '>HH'  # key_length, value_length

# V2 experimental format constants
_V2_PAGE_CRC_FMT = '>I'
_V2_PAGE_FLAGS_FMT = '>I'
_V2_PAGE_HDR_SIZE = 8    # CRC(4) + flags(4)


class StorageError(Exception):
    """Raised for storage-layer errors."""


class ChecksumMismatch(StorageError):
    """Raised when a checksum verification fails."""


# ----------------------------------------------------------------------
# Page (V1 format)
# ----------------------------------------------------------------------

class Page:
    """In-memory representation of a single data page.

    Binary layout (big-endian, packed sequentially):

        uint16   num_entries
        entry[]  entries       -- *num_entries* records, back-to-back
        bytes    zero-pad      -- fills remaining space to *page_size*

    Each entry:

        uint16   key_length
        uint16   value_length
        bytes    key_data      -- UTF-8
        bytes    value_data    -- UTF-8

    Note: entries are stored in lexicographic key order to enable
    binary search during reads.
    """

    __slots__ = ('_entries', '_page_size')

    def __init__(self, page_size: int = DEFAULT_PAGE_SIZE):
        self._entries: Dict[str, str] = {}
        self._page_size = page_size

    # -- accessors -----------------------------------------------------

    @property
    def entries(self) -> Dict[str, str]:
        return dict(self._entries)

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self._entries.get(key, default)

    def put(self, key: str, value: str) -> None:
        self._entries[key] = value

    def remove(self, key: str) -> bool:
        return self._entries.pop(key, None) is not None

    # -- serialization -------------------------------------------------

    def to_bytes(self) -> bytes:
        """Serialize to exactly *page_size* bytes.

        Entries are sorted by key for deterministic output and to
        support binary search during reads.
        """
        items = sorted(self._entries.items())
        buf = struct.pack('>H', len(items))
        for k, v in items:
            kb = k.encode('utf-8')
            vb = v.encode('utf-8')
            buf += struct.pack(_ENTRY_HDR_FMT, len(kb), len(vb))
            buf += kb + vb
        if len(buf) > self._page_size:
            raise StorageError(
                f'Page data ({len(buf)} B) exceeds page size '
                f'({self._page_size} B)')
        return buf.ljust(self._page_size, b'\x00')

    @classmethod
    def from_bytes(cls, data: bytes,
                   page_size: int = DEFAULT_PAGE_SIZE) -> 'Page':
        """Deserialize from raw bytes."""
        page = cls(page_size)
        n = struct.unpack_from('>H', data, 0)[0]
        pos = 2
        for _ in range(n):
            klen, vlen = struct.unpack_from(_ENTRY_HDR_FMT, data, pos)
            pos += struct.calcsize(_ENTRY_HDR_FMT)
            key = data[pos:pos + klen].decode('utf-8')
            pos += klen
            val = data[pos:pos + vlen].decode('utf-8')
            pos += vlen
            page._entries[key] = val
        return page


# ----------------------------------------------------------------------
# Page (V2 experimental -- not deployed in production)
# ----------------------------------------------------------------------

class PageV2(Page):
    """V2 page format with per-page CRC and flags field.

    Binary layout::

        uint32   page_crc32    -- CRC-32 of bytes following this field
        uint32   flags         -- bit 0: compressed, bit 1: encrypted
        uint16   num_entries
        entry[]  entries
        bytes    zero-pad

    This format adds 8 bytes of overhead per page.  The usable
    data area is (page_size - 8) bytes.
    """

    def to_bytes(self) -> bytes:
        inner_size = self._page_size - _V2_PAGE_HDR_SIZE
        old_ps = self._page_size
        self._page_size = inner_size
        try:
            inner = super().to_bytes()
        finally:
            self._page_size = old_ps
        crc = zlib.crc32(inner) & 0xFFFF_FFFF
        return struct.pack('>II', crc, 0) + inner

    @classmethod
    def from_bytes(cls, data: bytes,
                   page_size: int = DEFAULT_PAGE_SIZE) -> 'PageV2':
        crc_stored, flags = struct.unpack_from('>II', data, 0)
        inner = data[_V2_PAGE_HDR_SIZE:page_size]
        crc_computed = zlib.crc32(inner) & 0xFFFF_FFFF
        if crc_stored != crc_computed:
            raise ChecksumMismatch(
                f'V2 page CRC: stored 0x{crc_stored:08X}, '
                f'computed 0x{crc_computed:08X}')
        page = cls(page_size)
        n = struct.unpack_from('>H', inner, 0)[0]
        pos = 2
        for _ in range(n):
            klen, vlen = struct.unpack_from(_ENTRY_HDR_FMT, inner, pos)
            pos += struct.calcsize(_ENTRY_HDR_FMT)
            key = inner[pos:pos + klen].decode('utf-8')
            pos += klen
            val = inner[pos:pos + vlen].decode('utf-8')
            pos += vlen
            page._entries[key] = val
        return page


# ----------------------------------------------------------------------
# Database file
# ----------------------------------------------------------------------

class Database:
    """Manages a SIMDB database file.

    On-disk structure::

        [Header  -- HEADER_TOTAL_SIZE bytes]
        [Page 0  -- page_size bytes]
        [Page 1  -- page_size bytes]
        ...
        [Page N-1]

    The header checksum (CRC-32) is computed over the concatenation
    of all page bytes in order.
    """

    def __init__(self, path: str, page_size: int = DEFAULT_PAGE_SIZE,
                 format_version: int = DB_FORMAT_VERSION):
        self.path = path
        self.page_size = page_size
        self.format_version = format_version
        self.pages: List[Page] = []

    def _make_page(self) -> Page:
        """Create a page appropriate for the current format version."""
        if self.format_version >= 2:
            return PageV2(self.page_size)
        return Page(self.page_size)

    def compute_checksum(self) -> int:
        """CRC-32 of all serialized pages concatenated."""
        raw = b''.join(p.to_bytes() for p in self.pages)
        return zlib.crc32(raw) & 0xFFFF_FFFF

    def flush(self) -> None:
        """Write to disk."""
        cksum = self.compute_checksum()
        hdr = struct.pack(_HEADER_FMT, DB_MAGIC, self.format_version,
                          self.page_size, len(self.pages), cksum)
        hdr += b'\x00' * (HEADER_TOTAL_SIZE - len(hdr))
        with open(self.path, 'wb') as fh:
            fh.write(hdr)
            for p in self.pages:
                fh.write(p.to_bytes())

    @classmethod
    def load(cls, path: str) -> 'Database':
        """Read and validate a database file.

        Determines the format version from the header and uses
        the appropriate page deserializer.
        """
        with open(path, 'rb') as fh:
            raw = fh.read()
        if len(raw) < HEADER_TOTAL_SIZE:
            raise StorageError('File smaller than header')

        magic, version, ps, pc, stored_cksum = struct.unpack_from(
            _HEADER_FMT, raw, 0)

        if magic != DB_MAGIC:
            raise StorageError(f'Bad magic: {magic!r}')
        if version not in (1, 2):
            raise StorageError(f'Unsupported version {version}')

        db = cls(path, ps, version)
        page_cls = PageV2 if version >= 2 else Page
        for i in range(pc):
            start = HEADER_TOTAL_SIZE + i * ps
            db.pages.append(page_cls.from_bytes(raw[start:start + ps], ps))

        computed = db.compute_checksum()
        if stored_cksum != computed:
            raise ChecksumMismatch(
                f'Header CRC mismatch: stored 0x{stored_cksum:08X}, '
                f'computed 0x{computed:08X}')
        return db
