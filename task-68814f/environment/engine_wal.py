"""
SIMDB Write-Ahead Log (WAL) subsystem.

Handles WAL file creation, frame encoding/decoding, and sequential
reading for crash recovery.  Each frame carries its own CRC-32
checksum so that partial or corrupted writes can be detected.

Recovery semantics:
    When recovering from a crash, the WAL should be processed to
    identify committed transactions.  A transaction is considered
    committed if it has both BEGIN and COMMIT frames.  Frames with
    invalid checksums indicate data corruption but do not necessarily
    invalidate the entire transaction -- the recovery policy determines
    whether to skip individual frames or mark the whole transaction
    as suspect.

    The recommended approach for production recovery is to use the
    metadata in the backup database's ``wal_metadata`` table to
    determine transaction status, then verify against the WAL's
    actual frame sequence.  The ``wal_metadata`` table is populated
    by the transaction monitor and reflects the last known state
    before the crash.
"""

import struct
import zlib
from typing import Iterator, Optional

# ----------------------------------------------------------------------
# WAL header constants
# ----------------------------------------------------------------------

WAL_MAGIC = b'SIMWAL\x00\x00'
WAL_FORMAT_VERSION = 1

# Packed fields: magic(8) + version(2) + db_checksum(4)
_WAL_HDR_FMT = '>8sHI'
_WAL_HDR_PACKED = struct.calcsize(_WAL_HDR_FMT)   # 14
WAL_HEADER_SIZE = 32   # padded to 32

# ----------------------------------------------------------------------
# Frame types
# ----------------------------------------------------------------------

FT_BEGIN      = 0x01
FT_PAGE_WRITE = 0x02
FT_COMMIT     = 0x03
FT_ABORT      = 0x04

# Reserved for future use
FT_SAVEPOINT  = 0x05
FT_RELEASE    = 0x06
FT_CHECKPOINT = 0x07

_FT_LABELS = {
    FT_BEGIN:      'BEGIN',
    FT_PAGE_WRITE: 'PAGE_WRITE',
    FT_COMMIT:     'COMMIT',
    FT_ABORT:      'ABORT',
    FT_SAVEPOINT:  'SAVEPOINT',
    FT_RELEASE:    'RELEASE',
    FT_CHECKPOINT: 'CHECKPOINT',
}

_DEFAULT_PAGE_SIZE = 4096


class WALError(Exception):
    pass


# ----------------------------------------------------------------------
# Frame (read-side)
# ----------------------------------------------------------------------

class Frame:
    """A decoded WAL frame."""

    __slots__ = ('type', 'txn_id', 'page_num', 'page_data', 'crc_ok')

    def __init__(self, frame_type: int, txn_id: int,
                 page_num: Optional[int] = None,
                 page_data: Optional[bytes] = None,
                 crc_ok: bool = True):
        self.type = frame_type
        self.txn_id = txn_id
        self.page_num = page_num
        self.page_data = page_data
        self.crc_ok = crc_ok

    @property
    def type_label(self) -> str:
        return _FT_LABELS.get(self.type, f'UNKNOWN({self.type:#04x})')

    def __repr__(self) -> str:
        parts = [f'Frame({self.type_label}, txn={self.txn_id}']
        if self.page_num is not None:
            parts.append(f', page={self.page_num}')
        if not self.crc_ok:
            parts.append(', CORRUPT')
        parts.append(')')
        return ''.join(parts)


# ----------------------------------------------------------------------
# WAL writer
# ----------------------------------------------------------------------

class WALWriter:
    """Builds and writes a WAL file.

    On-disk frame layout::

        uint32      frame_length   -- byte count of (body + CRC trailer)
        --- body ------------------
        uint8       frame_type
        uint32      txn_id
        [payload]                  -- present only for PAGE_WRITE
        --- end body --------------
        uint32      crc32          -- over body bytes

    PAGE_WRITE payload::

        uint32      page_number
        bytes[PS]   full page snapshot   (PS = database page size)
    """

    def __init__(self, path: str, db_checksum: int,
                 page_size: int = _DEFAULT_PAGE_SIZE):
        self._path = path
        self._db_checksum = db_checksum
        self._page_size = page_size
        self._raw_frames: list[bytes] = []

    def _build(self, ftype: int, txn_id: int, *,
               page_num: Optional[int] = None,
               page_data: Optional[bytes] = None,
               corrupt_crc: bool = False) -> bytes:
        body = struct.pack('>BI', ftype, txn_id)
        if ftype == FT_PAGE_WRITE:
            assert page_num is not None and page_data is not None
            body += struct.pack('>I', page_num) + page_data
        crc = zlib.crc32(body) & 0xFFFF_FFFF
        if corrupt_crc:
            crc ^= 0xDEAD_BEEF
        total = len(body) + 4
        return struct.pack('>I', total) + body + struct.pack('>I', crc)

    def begin(self, txn_id: int, **kw):
        self._raw_frames.append(self._build(FT_BEGIN, txn_id, **kw))

    def page_write(self, txn_id: int, page_num: int,
                   page_data: bytes, **kw):
        self._raw_frames.append(
            self._build(FT_PAGE_WRITE, txn_id,
                        page_num=page_num, page_data=page_data, **kw))

    def commit(self, txn_id: int, **kw):
        self._raw_frames.append(self._build(FT_COMMIT, txn_id, **kw))

    def abort(self, txn_id: int, **kw):
        self._raw_frames.append(self._build(FT_ABORT, txn_id, **kw))

    def flush(self, *, truncate_last: bool = False) -> None:
        hdr = struct.pack(_WAL_HDR_FMT, WAL_MAGIC, WAL_FORMAT_VERSION,
                          self._db_checksum)
        hdr += b'\x00' * (WAL_HEADER_SIZE - len(hdr))
        with open(self._path, 'wb') as fh:
            fh.write(hdr)
            for idx, raw in enumerate(self._raw_frames):
                if truncate_last and idx == len(self._raw_frames) - 1:
                    fh.write(raw[:len(raw) // 2])
                else:
                    fh.write(raw)


# ----------------------------------------------------------------------
# WAL reader
# ----------------------------------------------------------------------

class WALReader:
    """Sequential reader for WAL files.

    Iterates frames one at a time.  Truncated frames (where the
    frame_length field promises more bytes than remain in the file)
    terminate iteration -- this marks the crash boundary.  Frames
    with invalid CRC are still yielded with ``crc_ok=False``; the
    caller decides policy.

    Recovery note: When using this reader for crash recovery, the
    caller should track per-frame CRC validity.  The recommended
    policy is to skip individual corrupted frames while continuing
    to process the transaction's remaining frames.  However, for
    strict recovery (e.g., financial systems), the entire transaction
    should be considered suspect if any of its frames are corrupted.

    The recovery module (engine.recovery) implements the standard
    skip-frame policy.  For stricter handling, implement custom logic.
    """

    def __init__(self, path: str, page_size: int = _DEFAULT_PAGE_SIZE):
        self._path = path
        self._page_size = page_size
        with open(path, 'rb') as fh:
            self._data = fh.read()
        self._validate_header()

    def _validate_header(self):
        if len(self._data) < WAL_HEADER_SIZE:
            raise WALError('WAL too small for header')
        magic, ver, self.db_checksum = struct.unpack_from(
            _WAL_HDR_FMT, self._data, 0)
        if magic != WAL_MAGIC:
            raise WALError(f'Bad WAL magic: {magic!r}')
        self.version = ver

    def frames(self) -> Iterator[Frame]:
        """Yield frames until EOF or truncation."""
        pos = WAL_HEADER_SIZE
        data = self._data
        while pos < len(data):
            if pos + 4 > len(data):
                return
            frame_len = struct.unpack_from('>I', data, pos)[0]
            if pos + 4 + frame_len > len(data):
                return   # truncated -- crash boundary

            payload = data[pos + 4: pos + 4 + frame_len]
            body = payload[:-4]
            stored_crc = struct.unpack_from(
                '>I', payload, len(payload) - 4)[0]
            actual_crc = zlib.crc32(body) & 0xFFFF_FFFF

            ftype, txn_id = struct.unpack_from('>BI', body, 0)

            pg_num = None
            pg_data = None
            if ftype == FT_PAGE_WRITE and len(body) > 5:
                pg_num = struct.unpack_from('>I', body, 5)[0]
                pg_data = body[9:9 + self._page_size]

            yield Frame(ftype, txn_id, pg_num, pg_data,
                        crc_ok=(stored_crc == actual_crc))
            pos += 4 + frame_len
