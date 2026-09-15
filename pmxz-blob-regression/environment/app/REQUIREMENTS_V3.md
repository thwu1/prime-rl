# PMXZ v3 Format Specification

## Overview

PMXZ v3 extends the process map blob format with integrity checking, explicit compressed-length tracking, and support for multiple compression algorithms. It replaces v1 and v2 as the preferred storage format for serialized process maps.

## Header Layout (18 bytes total)

| Offset | Size (bytes) | Field             | Description                                                |
|--------|-------------|-------------------|------------------------------------------------------------|
| 0      | 4           | Magic             | ASCII `"PMXZ"` (`0x504D585A`)                              |
| 4      | 1           | Version           | `3`                                                        |
| 5      | 1           | Flags             | Bits 0-1: algorithm (0=zlib, 1=lzma, 2=zstd); Bit 2: checksummed (always 1 for v3); Bits 3-7: reserved (must be 0) |
| 6      | 4           | Uncompressed Len  | Big-endian `uint32`: byte length of the original UTF-8 data |
| 10     | 4           | CRC32             | Big-endian `uint32`: `zlib.crc32()` of the uncompressed UTF-8 data |
| 14     | 4           | Compressed Len    | Big-endian `uint32`: byte length of the compressed payload  |
| 18     | variable    | Compressed Data   | The compressed payload                                     |

## Serialization Rules

1. `serialize_procmap_v3(procmap_str, algorithm='zlib')` MUST always produce a v3 blob, regardless of data size (no raw-format fallback).
2. The `algorithm` parameter accepts `'zlib'` (default), `'lzma'`, or `'zstd'`.
3. The flags byte MUST have bit 2 set (`flags & 0x04 != 0`), indicating the blob is checksummed.
4. Bits 0-1 of flags encode the algorithm: `0b00` for zlib, `0b01` for lzma, `0b10` for zstd.
5. CRC32 is computed on the raw UTF-8 encoded process map bytes using `zlib.crc32()`, masked to 32 bits (`& 0xFFFFFFFF`).
6. The compressed-length field enables precise extraction of the payload without relying on reading to EOF or trusting the stream length.
7. Use `struct.pack(">4sBBIII", ...)` or equivalent to produce the 18-byte header with no padding.
8. When `algorithm='zstd'`, the compressed payload MUST be a valid standalone zstd frame (i.e. decompressable by `zstd -d`).

## Deserialization Rules

1. `deserialize_procmap(data)` MUST auto-detect format: raw (`b"raw:"`), PMXZ v1, PMXZ v2, or PMXZ v3.
2. For v3 blobs, after decompression:
   - Verify that the decompressed length matches the Uncompressed Len field.
   - Compute `zlib.crc32()` of the decompressed bytes and compare to the stored CRC32. On mismatch, raise `ValueError` with a message containing the substring `"CRC32"`.
3. Select the decompressor based on bits 0-1 of the flags byte: `0b00` → `zlib.decompress`, `0b01` → `lzma.decompress`, `0b10` → zstandard decompression.
4. Use the Compressed Len field to slice exactly that many bytes from offset 18.

## Version Detection Heuristic

For any PMXZ blob (data starting with `b"PMXZ"`), byte 4 determines the version:

- **2 – 127 (inclusive)**: treat as the format version number. v2 has value `2`, v3 has value `3`.
- **0, 1, or > 127**: the blob is **v1 format**, which predates version tagging. In v1, byte 4 is the most-significant byte of the big-endian `uint32` uncompressed-length field.

This heuristic is safe because v1's uncompressed length is always less than 16 MB for process maps (MSB is `0x00`), and version `1` was never assigned as a version-byte value since v1 predates the version-byte convention.

### Per-version layouts for reference

- **v1**: `magic(4) + uncompressed_len(4) + zlib_data` — 8-byte header, zlib only
- **v2**: `magic(4) + version(1) + uncompressed_len(4) + zlib_data` — 9-byte header, zlib only
- **v3**: `magic(4) + version(1) + flags(1) + uncomp_len(4) + crc32(4) + comp_len(4) + data` — 18-byte header, zlib/lzma/zstd
