# TAG_PACKED (0x03) Binary Format Specification

## Overview

TAG_PACKED is a compact binary format for encoding PPN (Process-Per-Node)
rank assignment maps.  It exploits patterns in rank placement — contiguous
sequences, constant-stride sequences, and arbitrary assignments — to
minimize encoding size for structured HPC topologies.

## Wire Format

All multi-byte integers use **little-endian** byte ordering.

### Top-Level Layout

| Offset | Size | Type     | Field   | Description                 |
|--------|------|----------|---------|-----------------------------|
| 0      | 1    | uint8_t  | tag     | Format tag: `0x03`          |
| 1      | 2    | uint16_t | nnodes  | Number of compute nodes     |
| 3      | var  | —        | nodes[] | Sequence of node descriptors|

### Node Descriptor

Each node descriptor begins with a fixed 3-byte header followed by a
variable-length payload:

| Offset | Size | Type     | Field    | Description                |
|--------|------|----------|----------|----------------------------|
| 0      | 2    | uint16_t | nranks   | Number of ranks on node    |
| 2      | 1    | uint8_t  | enc_type | Encoding type (see below)  |
| 3      | var  | —        | payload  | Depends on enc_type        |

### Encoding Types

#### CONTIGUOUS (enc_type = 0x00)

Ranks form a consecutive sequence: `first`, `first+1`, …, `first+nranks-1`.

| Offset | Size | Type     | Field      | Description             |
|--------|------|----------|------------|-------------------------|
| 0      | 4    | uint32_t | first_rank | First rank in sequence  |

Per-node payload: **4 bytes**.

#### STRIDED (enc_type = 0x01)

Ranks have constant spacing: `first`, `first+stride`, `first+2*stride`, …,
`first+(nranks-1)*stride`.

| Offset | Size | Type     | Field      | Description             |
|--------|------|----------|------------|-------------------------|
| 0      | 4    | uint32_t | first_rank | First rank in sequence  |
| 4      | 2    | int16_t  | stride     | Constant rank spacing   |

Per-node payload: **6 bytes**.

A node with `nranks <= 1` **MUST NOT** use STRIDED encoding — use CONTIGUOUS
instead.  A node whose ranks have stride 1 **MUST** use CONTIGUOUS, not
STRIDED.

#### EXPLICIT (enc_type = 0x02)

Ranks have no regular pattern and are listed individually.

| Offset     | Size     | Type       | Field   | Description           |
|------------|----------|------------|---------|-----------------------|
| 0          | 4*nranks | uint32_t[] | ranks[] | Individual rank values|

Per-node payload: **4 × nranks bytes**.

### Encoding Type Selection Rules

The encoder **MUST** choose the most compact per-node encoding:

1. If `nranks <= 1`, or ranks are consecutive with stride 1: use **CONTIGUOUS**
   (4 bytes payload).
2. Else if `nranks >= 2` and all successive rank-to-rank differences are equal
   (constant non-unit stride): use **STRIDED** (6 bytes payload).
3. Otherwise: use **EXPLICIT** (4 × nranks bytes payload).

### Node ID Assignment

Node IDs are assigned sequentially (0, 1, 2, …) in the order nodes appear
in the encoded stream.  They are **not** encoded explicitly.

## Example

A 3-node map with 9 contiguous processes (3 per node):

```
Node 0: ranks [0, 1, 2]   → CONTIGUOUS, first_rank=0
Node 1: ranks [3, 4, 5]   → CONTIGUOUS, first_rank=3
Node 2: ranks [6, 7, 8]   → CONTIGUOUS, first_rank=6
```

Wire bytes (hex):
```
03                     -- TAG_PACKED
03 00                  -- nnodes = 3
03 00 00 00 00 00 00   -- node 0: nranks=3, enc=CONTIGUOUS, first=0
03 00 00 03 00 00 00   -- node 1: nranks=3, enc=CONTIGUOUS, first=3
03 00 00 06 00 00 00   -- node 2: nranks=3, enc=CONTIGUOUS, first=6
```

Total: **24 bytes** vs TAG_RAW "0,1,2;3,4,5;6,7,8" = **19 bytes**.
For this small map TAG_RAW is smaller; the auto-selector should pick TAG_RAW.
TAG_PACKED becomes advantageous as per-node rank counts grow.
