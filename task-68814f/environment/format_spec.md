# SIMDB Database & WAL Format Specification v1

## Overview

SIMDB is a page-based key-value store with write-ahead logging for crash recovery. This document specifies the binary formats for the database file and its associated WAL (Write-Ahead Log).

All multi-byte integers are stored in **big-endian** byte order.

---

## Database File Format

### File Header (32 bytes)

| Offset | Size | Type       | Description                                          |
|--------|------|------------|------------------------------------------------------|
| 0      | 6    | bytes      | Magic bytes: `SIMDB\x00`                             |
| 6      | 2    | uint16 BE  | Format version (currently `1`)                       |
| 8      | 4    | uint32 BE  | Page size in bytes (always `4096` in this version)   |
| 12     | 4    | uint32 BE  | Total number of data pages                           |
| 16     | 4    | uint32 BE  | CRC32 checksum of all data pages concatenated        |
| 20     | 12   | bytes      | Reserved (zeros)                                     |

The CRC32 checksum is computed over the raw bytes of all data pages concatenated in order (page 0 through page N-1), using the standard CRC32 algorithm (ISO 3309 / ITU-T V.42, as implemented by `zlib.crc32`).

### Data Pages

Data pages follow immediately after the 32-byte header. Each page is exactly `page_size` bytes (4096).

**Page N** starts at file offset: `32 + N * page_size`

#### Page Internal Format

| Offset | Size    | Type       | Description                          |
|--------|---------|------------|--------------------------------------|
| 0      | 2       | uint16 BE  | Number of key-value entries (`n`)    |
| 2      | varies  | entries[]  | `n` consecutive entry records        |
| ...    | ...     | zeros      | Zero-padding to fill `page_size`     |

#### Entry Record Format

Each entry is stored sequentially within the page, immediately after the previous entry:

| Size      | Type       | Description                    |
|-----------|------------|--------------------------------|
| 2         | uint16 BE  | Key length in bytes (`klen`)   |
| 2         | uint16 BE  | Value length in bytes (`vlen`) |
| `klen`    | bytes      | Key data (UTF-8 string)        |
| `vlen`    | bytes      | Value data (UTF-8 string)      |

---

## WAL File Format

### WAL Header (32 bytes)

| Offset | Size | Type       | Description                                              |
|--------|------|------------|----------------------------------------------------------|
| 0      | 8    | bytes      | Magic bytes: `SIMWAL\x00\x00`                            |
| 8      | 2    | uint16 BE  | WAL format version (currently `1`)                       |
| 10     | 4    | uint32 BE  | CRC32 checksum of the original database's data pages     |
| 14     | 18   | bytes      | Reserved (zeros)                                         |

The `db_checksum` field stores the CRC32 of the database pages as they were when the WAL was created. This can be used to verify that the WAL corresponds to the correct database file.

### WAL Frames

Frames are stored sequentially after the 32-byte WAL header. Each frame has the following layout:

| Size         | Type       | Description                                                   |
|--------------|------------|---------------------------------------------------------------|
| 4            | uint32 BE  | Frame length: number of bytes following this field (inclusive of the trailing checksum) |
| 1            | uint8      | Frame type (see below)                                        |
| 4            | uint32 BE  | Transaction ID                                                |
| (varies)     |            | Type-specific payload (see below)                             |
| 4            | uint32 BE  | CRC32 checksum of the frame body                              |

The **frame body** consists of everything between the frame-length field and the checksum field (i.e., from `frame_type` through the end of the type-specific payload). The CRC32 checksum is computed over exactly these bytes.

#### Frame Types

| Type Value | Name         | Description                                      |
|------------|--------------|--------------------------------------------------|
| 1          | `BEGIN`      | Marks the start of a transaction. No payload.    |
| 2          | `PAGE_WRITE` | Contains a complete modified page (see below).   |
| 3          | `COMMIT`     | Marks successful completion. No payload.         |
| 4          | `ABORT`      | Marks explicit rollback. No payload.             |

#### PAGE_WRITE Payload

| Size        | Type       | Description                    |
|-------------|------------|--------------------------------|
| 4           | uint32 BE  | Page number (0-indexed)        |
| `page_size` | bytes      | Complete page data (4096 bytes)|

The page data is a full snapshot of the page after modification. It uses the same internal page format described above.

---

## WAL Recovery Procedure

To recover a database from a crash, apply the following procedure:

1. **Read the original database file** including its header and all data pages.

2. **Process WAL frames sequentially** from the start of the WAL, maintaining per-transaction state:
   - Track which transactions have received a valid `BEGIN` frame.
   - Collect `PAGE_WRITE` data for each transaction.
   - Record final disposition (`COMMIT` or `ABORT`) for each transaction.

3. **Validate each frame's CRC32 checksum** before processing it:
   - Compute CRC32 over the frame body (from `frame_type` through end of payload).
   - Compare against the stored checksum at the end of the frame.
   - If a frame fails validation, **mark its transaction as corrupted**. Do not process the frame's contents, but continue reading subsequent frames.

4. **Handle truncated frames**: If fewer than 4 bytes remain (cannot read `frame_len`), or if the `frame_len` indicates more bytes than are available in the file, **stop processing the WAL entirely**. This indicates the system crashed mid-write.

5. **Classify transactions** after processing all readable frames:
   - **Committed**: Has a valid `BEGIN` frame AND a valid `COMMIT` frame, with NO corrupted frames belonging to this transaction.
   - **Aborted**: Has a valid `ABORT` frame.
   - **Corrupted**: Has at least one frame that failed CRC32 validation.
   - **Uncommitted**: Has a `BEGIN` but no `COMMIT` or `ABORT` (transaction was in progress at crash time).

6. **Apply committed transactions only**: Replay `PAGE_WRITE` frames from committed transactions **in WAL order** (the order they appear in the WAL file). If multiple committed writes target the same page, the last write in WAL order determines the final page content.

7. **Recalculate the header checksum**: After applying all committed writes, recompute the CRC32 over all data pages and update the database file header accordingly.

8. **Write the recovered database** with the updated header and page contents.
