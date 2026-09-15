# eMMC Flash Dump Binary Format (Partial Datasheet Extract)

All multi-byte fields are **little-endian**. No alignment padding is used between fields.

**Note:** This document is a partial extract from the vendor datasheet. Some sections reference vendor-specific extensions that are not covered in this excerpt.

## 1. Header (64 bytes)

| Offset | Size | Type   | Field                  | Description                                      |
|--------|------|--------|------------------------|--------------------------------------------------|
| 0      | 4    | uint32 | magic                  | `0x464C5348` (ASCII "FLSH")                      |
| 4      | 2    | uint16 | version                | Format version (currently 1)                     |
| 6      | 2    | uint16 | page_size              | Flash page size in bytes                         |
| 8      | 2    | uint16 | pages_per_block        | Number of pages per erase block                  |
| 10     | 2    | uint16 | total_blocks           | Total number of erase blocks                     |
| 12     | 4    | uint32 | journal_entry_count    | Number of entries in the I/O journal              |
| 16     | 4    | uint32 | process_count          | Number of entries in the process attribution table|
| 20     | 8    | uint64 | tbw_rating_bytes       | Device Total Bytes Written endurance rating       |
| 28     | 4    | uint32 | manufacture_timestamp  | Unix timestamp of device manufacture              |
| 32     | 4    | uint32 | current_timestamp      | Unix timestamp when dump was captured             |
| 36     | 28   | —      | reserved               | Zero-filled                                       |

## 2. Block Mapping Table

Starts immediately after the header (offset 64). Contains `total_blocks` entries, one per logical block in ascending order.

| Offset | Size | Type   | Field            | Description                              |
|--------|------|--------|------------------|------------------------------------------|
| 0      | 2    | uint16 | logical_block_id | Logical block number (0-indexed)         |
| 2      | 2    | uint16 | physical_block_id| Physical block this logical block maps to|

Each entry is 4 bytes. Total section size: `total_blocks * 4` bytes.

The mapping is a bijection: each physical block is referenced exactly once.

## 3. Erase Count Table

Starts immediately after the Block Mapping Table. Contains `total_blocks` entries, one per physical block in ascending order (physical block 0, 1, 2, ...).

| Offset | Size | Type   | Field       | Description                                 |
|--------|------|--------|-------------|---------------------------------------------|
| 0      | 4    | uint32 | erase_count | Cumulative erase cycle count for this block |

Each entry is 4 bytes. Total section size: `total_blocks * 4` bytes.

## 4. I/O Journal

Starts immediately after the Erase Count Table. Contains `journal_entry_count` entries.

Each entry is 32 bytes:

| Offset | Size | Type   | Field              | Description                                          |
|--------|------|--------|--------------------|------------------------------------------------------|
| 0      | 4    | uint32 | timestamp_offset   | Seconds since manufacture_timestamp                   |
| 4      | 2    | uint16 | logical_block      | Target logical block number                           |
| 6      | 2    | uint16 | start_page         | Starting page within the block                        |
| 8      | 2    | uint16 | page_count         | Number of pages involved in this operation             |
| 10     | 2    | uint16 | pid                | Process ID that initiated this I/O                     |
| 12     | 4    | uint32 | op_type            | Operation type (vendor-specific encoding, see note)    |
| 16     | 8    | uint64 | data_fingerprint   | Data fingerprint (0 for non-write operations)          |
| 24     | 4    | uint32 | integrity          | Per-entry integrity check (vendor-specific, see note)  |
| 28     | 4    | uint32 | reserved           | Zero-filled                                            |

**Note on op_type:** The `op_type` field uses a vendor-specific encoding to distinguish I/O operation types (reads, writes, erases). The specific values are not documented in this datasheet extract.

**Note on integrity:** The `integrity` field implements a per-entry corruption detection mechanism. The checksum algorithm and the input byte range it covers are vendor-specific and not documented in this extract. Entries whose integrity check does not validate should be considered corrupted and excluded from analysis.

## 5. Process Attribution Table

Starts immediately after the I/O Journal. Contains `process_count` entries.

The entry format for this table is vendor-specific and not documented in this datasheet extract.

## Section Layout Summary

```
[Header: 64 bytes]
[Block Mapping Table: total_blocks * 4 bytes]
[Erase Count Table: total_blocks * 4 bytes]
[I/O Journal: journal_entry_count * 32 bytes]
[Process Attribution Table: process_count * ? bytes]
```

All documented sections are contiguous with no gaps or padding between them.
