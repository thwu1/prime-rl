# TKV1 Flash Key-Value Store Format Specification

## Overview

This document specifies a log-structured, crash-consistent key-value store
designed for NOR flash memory. It is inspired by the TickV storage system used in
Tock OS for embedded devices, adapted for a simulated environment.

## Flash Memory Constraints

- Flash is organized into fixed-size **pages** (default 4096 bytes).
- An erased page has all bytes set to `0xFF`.
- **Writing** can only change bits from 1 to 0 (AND semantics).
- To set bits back to 1, the **entire page** must be erased.
- Page erase is atomic.

## Page Header (12 bytes)

Every initialized page begins with a 12-byte header:

| Offset | Size | Field          | Description                                       |
|--------|------|----------------|---------------------------------------------------|
| 0      | 4    | Magic          | `0x54 0x4B 0x56 0x31` (ASCII "TKV1")             |
| 4      | 1    | Status         | `0xFF`=erased, `0x0F`=active, `0x00`=full         |
| 5      | 2    | Sequence (LE)  | Monotonically increasing page sequence number     |
| 7      | 1    | Reserved       | Must be `0xFF`                                    |
| 8      | 4    | Erase Count(LE)| Number of times this page has been erased         |

Status transitions follow flash write rules (only clearing bits):
`0xFF` (erased) -> `0x0F` (active) -> `0x00` (full).

## Entry Format

Entries are appended sequentially after the page header. An entry consists of
a 16-byte header followed by key bytes and value bytes.

### Entry Header (16 bytes)

| Offset | Size | Field           | Description                                    |
|--------|------|-----------------|------------------------------------------------|
| 0      | 2    | Magic           | `0xAE 0x73`                                    |
| 2      | 1    | State           | `0x0F`=valid, `0x00`=invalidated               |
| 3      | 1    | Key Length      | 1-255 (0 is invalid)                           |
| 4      | 4    | Value Length(LE)| uint32, 0 is valid (empty value)               |
| 8      | 4    | Key Hash (LE)   | FNV-1a 32-bit hash of key bytes                |
| 12     | 4    | CRC32 (LE)      | Checksum (see below)                           |

### Key and Value Data

Immediately following the entry header:
- **Key**: `key_length` bytes
- **Value**: `value_length` bytes

An entry must fit entirely within a single page. If an entry does not fit in the
remaining space of the active page, the active page is marked full and a new page
is activated.

### FNV-1a 32-bit Hash

Used for the key hash field. Algorithm:

```
hash = 0x811c9dc5  (FNV offset basis)
for each byte b in key:
    hash = hash XOR b
    hash = (hash * 0x01000193) mod 2^32  (FNV prime)
return hash
```

### CRC32 Checksum

The CRC32 checksum covers the following data concatenated in order:
1. Key length (1 byte)
2. Value length (4 bytes, little-endian)
3. Key hash (4 bytes, little-endian)
4. Key bytes
5. Value bytes

**The state byte is NOT included in the CRC.** This allows invalidating an entry
(changing state from `0x0F` to `0x00`) without recomputing the checksum, which
is essential since flash writes can only clear bits.

Use standard CRC32 (ISO 3309 / zlib.crc32 in Python), masked to 32 bits.

## Operations

### FORMAT

Erase all pages. Initialize page 0 with status=active, sequence=0, and
erase_count set to the page's total erase count.

### PUT(key, value)

1. If an entry with the same key already exists (valid state), mark its state
   byte as `0x00` (invalidated). This is a single-byte flash write that only
   clears bits.
2. Find the current active page. If the entry does not fit in remaining space,
   mark the page as full (`0x00`) and activate the next available erased page.
3. Write the entry (header + key + value) to the active page.
4. Return success/failure (failure if no pages available).

### GET(key)

Return the value associated with the key, or None if not found. Uses the
in-memory index built during initialization/recovery.

### DELETE(key)

If a valid entry exists for the key, mark its state byte as `0x00`.
Return whether a key was actually deleted.

### COMPACT

1. Collect all currently valid key-value pairs from the in-memory index.
2. Erase all pages (incrementing erase counts).
3. Reinitialize starting from page 0 and rewrite all valid entries.

### RECOVERY (constructor)

When constructing a FlashKVStore from an existing flash image:

1. Scan all pages for valid page headers (correct magic, non-erased status).
2. Sort pages by sequence number (ascending).
3. For each page, scan entries sequentially:
   a. Check entry magic (`0xAE 0x73`). If wrong, stop scanning this page.
   b. Validate key_length > 0 and entry fits within page bounds. If not, stop.
   c. Read key and value bytes.
   d. Compute and verify CRC32. If mismatch, **stop scanning this page**.
   e. If state=valid (`0x0F`): add/update key in index.
   f. If state=invalid (`0x00`): remove key from index.
4. Track the active page and write offsets for continued operation.
