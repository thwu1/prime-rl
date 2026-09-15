# SB2 Firmware Update Format Reference

## Overview

The SB2 format is used for secure firmware updates on embedded devices. An
update file consists of a fixed-size header followed by encrypted command
blocks. The parser validates the header and authenticates the update before
processing any commands.

## Block Size

All block-number fields in the header reference 16-byte blocks. Block 0
starts at file offset 0, block 1 at offset 16, and so on.

## Header Structure (64 bytes, little-endian)

| Offset | Size | Field             | Description                               |
|--------|------|-------------------|-------------------------------------------|
| 0      | 4    | `magic`           | Format identifier: `0x53423221` ("SB2!")   |
| 4      | 2    | `major_version`   | Major version, must be 2                   |
| 6      | 2    | `minor_version`   | Minor version, must be 1                   |
| 8      | 4    | `flags`           | Processing flags (reserved, set to 0)      |
| 12     | 4    | `image_blocks`    | Total number of blocks in firmware image   |
| 16     | 4    | `first_boot_block`| Block number of first executable block     |
| 20     | 4    | `cert_offset`     | Byte offset to certificate block           |
| 24     | 2    | `header_blocks`   | Number of blocks occupied by header (typ. 8)|
| 26     | 2    | `key_blob_block`  | Block number where key blob data begins    |
| 28     | 2    | `key_blob_count`  | Number of blocks in key blob               |
| 30     | 2    | `max_section_mac` | Maximum MAC entries per section             |
| 32     | 32   | `reserved`        | Reserved for future use, must be zero      |

## Processing Order

1. Read and validate header magic and version fields
2. Load header data into internal processing buffer
3. Verify update authentication/signature
4. If authenticated, process firmware command blocks
5. Apply firmware changes

## Authentication

The update file is authenticated using a signature derived from the header
contents. Only authenticated updates are processed. The signature
verification algorithm operates on the first 64 bytes of the loaded header
data.

## Notes

- The parser rejects files smaller than the header size (64 bytes).
- Invalid magic or version values cause immediate rejection.
- Authentication failure produces an "auth failed" error.
- All multi-byte fields use little-endian byte order.
