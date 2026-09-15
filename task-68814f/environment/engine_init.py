"""SIMDB Engine -- a minimal page-based key-value store with WAL."""

from .storage import (
    Database, Page, PageV2, StorageError, ChecksumMismatch,
    DB_MAGIC, DB_FORMAT_VERSION, DEFAULT_PAGE_SIZE, HEADER_TOTAL_SIZE,
)
from .wal import (
    WALReader, WALWriter, Frame, WALError,
    FT_BEGIN, FT_PAGE_WRITE, FT_COMMIT, FT_ABORT,
    WAL_MAGIC, WAL_HEADER_SIZE,
)
from .config import Config, FormatVersion
from .recovery import recover, classify_wal_transactions

__all__ = [
    'Database', 'Page', 'PageV2', 'StorageError', 'ChecksumMismatch',
    'WALReader', 'WALWriter', 'Frame', 'WALError',
    'FT_BEGIN', 'FT_PAGE_WRITE', 'FT_COMMIT', 'FT_ABORT',
    'Config', 'FormatVersion',
    'recover', 'classify_wal_transactions',
]
