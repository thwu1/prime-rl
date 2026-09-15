# Binary Data Formats

Two binary companion files may accompany a crash database. All multi-byte integers are **big-endian** (network byte order). The value `0xFFFFFFFF` is reserved as a null sentinel.

---

## Page State File (`.pgstate`) — PGST Format

Records which data pages were durably flushed to disk before the crash. Pages absent from this file were never flushed (treat their on-disk LSN as −1).

### Layout

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0 | 4 | bytes | Magic: `PGST` (0x50 0x47 0x53 0x54) |
| 4 | 4 | uint32 | Entry count (N) |
| 8 | 8×N | entries | N page entries |

### Page Entry (8 bytes)

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0 | 4 | uint32 | `page_id` — page identifier |
| 4 | 4 | uint32 | `flushed_lsn` — highest LSN durably written for this page |

Entries are **not** guaranteed to be sorted.

---

## WAL Suffix File (`.walsuffix`) — WAL1 Format

Contains log records that were appended to the write-ahead log after the SQLite WAL export. These records must be merged with the SQLite WAL records (by LSN order) before analysis. This file may not exist if all records are already in the SQLite database.

### Layout

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0 | 4 | bytes | Magic: `WAL1` (0x57 0x41 0x4C 0x31) |
| 4 | 4 | uint32 | Record count (N) |
| 8 | 24×N | records | N log records |

### Log Record (24 bytes, fixed size)

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0 | 4 | uint32 | `lsn` — Log Sequence Number |
| 4 | 1 | uint8 | `record_type` — type code (see table) |
| 5 | 3 | — | Reserved (zero-padded) |
| 8 | 4 | uint32 | `txn_id` — transaction identifier (`0xFFFFFFFF` if null) |
| 12 | 4 | uint32 | `prev_lsn` — previous LSN for same transaction (`0xFFFFFFFF` if null) |
| 16 | 4 | uint32 | `page_id` — affected page (`0xFFFFFFFF` if not applicable) |
| 20 | 4 | uint32 | `undo_next_lsn` — CLR undo chain target (`0xFFFFFFFF` if not applicable) |

### Record Type Codes

| Code | Type |
|------|------|
| 0x01 | UPDATE |
| 0x02 | COMMIT |
| 0x03 | ABORT |
| 0x04 | CLR |
| 0x05 | END |

Note: BEGIN_CHECKPOINT and END_CHECKPOINT records with their associated snapshot tables are only stored in the SQLite database, never in the binary suffix.
