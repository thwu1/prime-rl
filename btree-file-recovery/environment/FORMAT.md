# B+Tree Database File Format Specification

## Overview

A database file is a sequence of fixed-size **pages** of 4096 bytes each. Page 0 is the **meta page**; all other pages are **B+tree nodes**.

## Constants

- `PAGE_SIZE = 4096`
- `BNODE_INTERNAL = 1` (internal node type)
- `BNODE_LEAF = 2` (leaf node type)

## Page 0: Meta Page

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0 | 16 | bytes | Magic: ASCII `BYODB_TBENCH_V1` followed by a null byte (`\x00`), totaling 16 bytes |
| 16 | 8 | uint64 LE | `root_page`: page number of the B+tree root node |
| 24 | 8 | uint64 LE | `num_pages`: total number of pages in the file (including this meta page) |
| 32 | 4 | uint32 LE | `checksum`: CRC-32 (zlib / ISO 3309) computed over bytes 0–31 of this page |
| 36 | 4060 | — | Reserved (zero-filled) |

The checksum covers exactly the 32 bytes before it (magic + root\_page + num\_pages). It does **not** include itself.

## Pages 1+: B+Tree Nodes

Each node occupies exactly one page. Unused trailing bytes within the page are zero-filled. A node consists of four sections laid out contiguously:

### 1. Header (4 bytes)

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0 | 2 | uint16 LE | `node_type`: 1 = internal node, 2 = leaf node |
| 2 | 2 | uint16 LE | `nkeys`: number of keys in this node |

### 2. Pointer Array (`nkeys × 8` bytes, starting at byte offset 4)

Each entry `pointers[i]` is a **uint64 LE**.

- **Internal nodes**: `pointers[i]` is the page number of child subtree `i`.
- **Leaf nodes**: all entries are zero (unused).

### 3. Offset Array (`nkeys × 2` bytes, starting at byte offset `4 + nkeys × 8`)

Each entry `offsets[i]` is a **uint16 LE**. It equals the **total byte length of KV pairs 0 through `i` combined** (cumulative size).

To locate KV pair `i` within the KV data area:
- **Start byte**: `offsets[i-1]` (or `0` when `i = 0`)
- **End byte**: `offsets[i]` (exclusive)
- **Byte length**: `offsets[i] - offsets[i-1]` (or `offsets[0]` when `i = 0`)

### 4. KV Data Area (variable length, starting at byte offset `4 + nkeys × 10`)

KV pairs are concatenated sequentially with no gaps. Each KV pair has this internal layout:

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0 | 2 | uint16 LE | `klen`: key length in bytes |
| 2 | 2 | uint16 LE | `vlen`: value length in bytes |
| 4 | klen | bytes | Key data (UTF-8 encoded) |
| 4+klen | vlen | bytes | Value data (UTF-8 encoded) |

So each KV pair occupies `4 + klen + vlen` bytes.

For **internal nodes**, values are empty (`vlen = 0`); only keys are stored.

## Invariants

1. Keys within any node are in **strictly ascending** lexicographic (byte) order.
2. In an internal node, `key[i]` equals the smallest key in the subtree rooted at `pointers[i]`.
3. All leaf nodes are at the **same depth** from the root.
4. Every pointer in an internal node satisfies `0 < pointers[i] < num_pages`.
5. Leaf node pointers are all zero.
6. The fixed-size portions of a node must fit within a page: `4 + nkeys × 10 ≤ PAGE_SIZE`.

## Worked Example

A leaf node containing two key-value pairs: `("ab", "xyz")` and `("cd", "w")`.

```
Header (4 bytes):
  Bytes 0-1:   02 00              node_type = 2 (leaf)
  Bytes 2-3:   02 00              nkeys = 2

Pointer array (2 × 8 = 16 bytes):
  Bytes 4-19:  00 00 ... 00       all zeros (leaf node)

Offset array (2 × 2 = 4 bytes):
  Bytes 20-21: 09 00              offsets[0] = 9  (KV pair 0 is 9 bytes)
  Bytes 22-23: 10 00              offsets[1] = 16 (KV pairs 0+1 total 16 bytes)

KV data area (starts at byte 4 + 2×10 = 24):
  Bytes 24-32:                    KV pair 0:
    02 00                           klen = 2
    03 00                           vlen = 3
    61 62                           key = "ab"
    78 79 7A                        val = "xyz"
  Bytes 33-39:                    KV pair 1:
    02 00                           klen = 2
    01 00                           vlen = 1
    63 64                           key = "cd"
    77                              val = "w"

Padding:
  Bytes 40-4095: 00 00 ... 00     zero-filled
```
