# B+Tree Database File Format Specification


## Overview

This document describes the binary format of a persistent B+tree key-value store. The database is stored as a single file composed of fixed-size pages. All multi-byte integers use **little-endian** byte order.

## Constants

| Name | Value | Description |
|------|-------|-------------|
| PAGE_SIZE | 4096 | Size of each page in bytes |
| BNODE_INTERNAL | 1 | Internal (non-leaf) B+tree node type |
| BNODE_LEAF | 2 | Leaf B+tree node type |
| SIGNATURE | `BYO_DB_MAGIC_V01` | 16-byte ASCII file signature |
| FREE_LIST_CAP | 511 | Maximum items per free list page: `(PAGE_SIZE - 8) / 8` |

## File Layout

The file is a contiguous sequence of pages, each exactly PAGE_SIZE bytes. Page 0 is always the meta page. Pages 1 through `pages_used - 1` contain B+tree nodes, free list nodes, or may be unused (zero-filled).

---

## Page 0: Meta Page

| Offset | Size | Type | Field | Description |
|--------|------|------|-------|-------------|
| 0 | 16 | bytes | signature | Must equal `BYO_DB_MAGIC_V01` (ASCII) |
| 16 | 8 | uint64 | root_ptr | Page number of the current B+tree root node |
| 24 | 8 | uint64 | pages_used | Total number of pages in the file |
| 32 | 8 | uint64 | fl_head_page | Page number of the free list head node |
| 40 | 8 | uint64 | fl_head_seq | Free list head sequence number |
| 48 | 8 | uint64 | fl_tail_page | Page number of the free list tail node |
| 56 | 8 | uint64 | fl_tail_seq | Free list tail sequence number |
| 64 | 4032 | - | (reserved) | Zero-filled padding to PAGE_SIZE |

---

## B+Tree Node Format

Both internal and leaf nodes share the same binary layout within a page:

```
+--------+--------+-------------------+------------------+---------------------+
| type   | nkeys  | pointers          | offsets          | KV data             |
| 2 bytes| 2 bytes| nkeys * 8 bytes   | nkeys * 2 bytes  | variable length     |
+--------+--------+-------------------+------------------+---------------------+
```

### Header (4 bytes)

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0 | 2 | uint16 | type: `BNODE_INTERNAL` (1) or `BNODE_LEAF` (2) |
| 2 | 2 | uint16 | nkeys: number of keys stored in this node |

### Pointers Array

Starting at byte offset 4, the pointers array contains `nkeys` entries, each a uint64 (8 bytes).

- For **internal nodes**: each pointer is the page number of a child node.
- For **leaf nodes**: all pointers are 0 (the space is still allocated in the layout).

Pointer `i` is at byte offset `4 + 8 * i`.

### Offset Array

Starting at byte offset `4 + nkeys * 8`, the offset array contains `nkeys` entries, each a uint16 (2 bytes). These offsets enable O(1) random access into the variable-length KV data section.

The offset array entry at index `i` (0-indexed) stores the **cumulative byte size** of KV pairs 0 through `i` — equivalently, the byte offset from the start of the KV data section to the **end** of KV pair `i` (which is also the **start** of KV pair `i+1`).

To locate KV pair at position `idx`:

```
kv_data_start = 4 + nkeys * 8 + nkeys * 2

if idx == 0:
    kv_pos = kv_data_start
else:
    kv_pos = kv_data_start + offset_array[idx - 1]
```

where `offset_array[j]` is the uint16 at byte offset `4 + nkeys * 8 + 2 * j`.

The total byte size of all KV data is `offset_array[nkeys - 1]`.

### Key-Value Pair Format

Each KV pair is encoded sequentially within the KV data section:

| Relative Offset | Size | Type | Field |
|-----------------|------|------|-------|
| 0 | 2 | uint16 | key_len: length of the key in bytes |
| 2 | 2 | uint16 | val_len: length of the value in bytes |
| 4 | key_len | bytes | key: the key data |
| 4 + key_len | val_len | bytes | val: the value data |

The total size of one KV pair is `4 + key_len + val_len` bytes.

**Internal nodes**: `val_len` is always 0. The key stored at position `i` is the first (smallest) key reachable in the subtree rooted at child pointer `i`.

**Leaf nodes**: Both key and value contain actual stored data. Values may contain trailing null bytes (0x00) used as padding.

### Node Size

The total number of meaningful bytes in a node is:

```
nbytes = kv_data_start + offset_array[nkeys - 1]
```

This value must not exceed PAGE_SIZE. Bytes between `nbytes` and PAGE_SIZE are unused padding.

---

## Free List Format

The free list is a singly-linked list of pages. Each free list page can store up to `FREE_LIST_CAP` (511) page numbers representing deallocated pages available for reuse.

### Free List Node Layout

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0 | 8 | uint64 | next_ptr: page number of next free list node, or 0 if this is the last node |
| 8 | FREE_LIST_CAP * 8 | uint64[] | items: array of freed page numbers |

Item `i` is at byte offset `8 + i * 8` within the page.

### Sequence-Based Indexing

The free list uses monotonically increasing sequence numbers rather than simple array indices. The meta page stores:

- `fl_head_seq`: sequence number of the oldest active (unconsumed) item
- `fl_tail_seq`: sequence number one past the newest item (exclusive upper bound)

Active freed items have sequence numbers in the half-open range `[fl_head_seq, fl_tail_seq)`.

To map a sequence number to a position within a free list page:

```
index = seq % FREE_LIST_CAP
```

Items are distributed across the linked pages. As sequence numbers advance past the capacity boundary of one page, subsequent items reside on the next page in the linked list (accessed via `next_ptr`).

---

## Copy-on-Write Semantics

This database uses copy-on-write (COW) updates. When a key-value pair is inserted, updated, or deleted:

1. New copies of all modified B+tree nodes (from the affected leaf up to the root) are written to newly allocated pages.
2. The meta page is updated atomically to point to the new root.
3. Old nodes that are no longer reachable are added to the free list for future reuse.

As a result, the database file may contain several categories of pages:

- **Current pages**: Reachable from the current root via B+tree pointer traversal
- **Free list structure pages**: Pages forming the free list linked list itself
- **Freed pages**: Pages listed as items in the free list, available for reuse (may still contain old B+tree data from a previous version)
- **Orphaned pages**: Pages containing valid B+tree node data from previous tree versions that are neither reachable from the current root nor recorded in the free list (e.g., due to incomplete cleanup after a crash or update)
- **Unused pages**: Pages containing no valid data (typically zero-filled)

### B+Tree Invariants

A well-formed B+tree satisfies the following structural constraints:

1. **Key ordering**: Keys within each node are in strictly ascending lexicographic order.
2. **Key-child consistency**: In an internal node, `key[i]` must equal the first (smallest) key in the subtree rooted at `pointer[i]`.
3. **Separation**: No page should be simultaneously reachable from the current tree AND listed as freed in the free list.
4. **Reference integrity**: All child pointers in reachable internal nodes must reference valid pages within `[1, pages_used)`.
