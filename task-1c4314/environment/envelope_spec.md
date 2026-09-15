# DERP Capture File Format (DPCAP v1)

## Overview

A DERP capture file (`.bin`) contains multiplexed DERP protocol frames recorded
from multiple client connections to a single DERP relay server. Each record in
the file represents one DERP frame, tagged with the connection it belongs to
and the direction of transmission.

## File Structure

### File Header

The file begins with an 8-byte magic identifier:

```
Offset  Length  Description
0       5       ASCII string "DPCAP"  (bytes: 44 50 43 41 50)
5       1       Version: 0x01
6       2       Reserved: 0x00 0x00
```

Full magic bytes: `44 50 43 41 50 01 00 00`

### Record Sequence

Following the 8-byte header is a sequence of records, concatenated until EOF.
Each record has the following layout:

```
+------------------+-------------+-----------------------------+
| Conn ID (2B, BE) | Dir (1B)    | DERP Frame (variable)       |
+------------------+-------------+-----------------------------+
```

#### Record Fields

| Field       | Size    | Encoding         | Description                              |
|-------------|---------|------------------|------------------------------------------|
| conn_id     | 2 bytes | big-endian uint16| Connection identifier (unique per client) |
| direction   | 1 byte  | unsigned byte    | `0x00` = client→server, `0x01` = server→client |
| derp_frame  | 5+N bytes | (see below)   | Standard DERP frame                      |

#### Embedded DERP Frame

Each record's DERP frame follows the standard DERP wire format:

| Field       | Size    | Encoding         | Description                      |
|-------------|---------|------------------|----------------------------------|
| frame_type  | 1 byte  | unsigned byte    | DERP frame type identifier       |
| payload_len | 4 bytes | big-endian uint32| Length of following payload       |
| payload     | N bytes | raw bytes        | Frame-type-specific payload      |

Refer to `derp_spec.md` for the meaning of each frame type and its payload
structure.

## Parsing Algorithm

To parse a DPCAP file:

1. Read and verify the 8-byte file magic
2. Repeat until EOF:
   a. Read 2 bytes → connection ID (big-endian uint16)
   b. Read 1 byte → direction
   c. Read 1 byte → DERP frame type
   d. Read 4 bytes → payload length (big-endian uint32)
   e. Read `payload_length` bytes → frame payload
3. If fewer bytes are available than expected at any step, stop (truncated file)

## Notes

- Records appear in chronological order
- Different connection IDs represent different TCP connections to the same
  DERP server
- A single DPCAP file may contain frames from the complete lifecycle of
  multiple client sessions (handshake through disconnect)
- The connection ID namespace is local to the capture file
