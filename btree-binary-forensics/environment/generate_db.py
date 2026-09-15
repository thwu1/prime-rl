#!/usr/bin/env python3
"""Generate a corrupted B+tree database file for the repair task.

Page layout (20 pages):
  Page 0:  Meta page (root=12, pages_used=20, free list at pages 13->19)
           CORRUPTION: fl_tail_seq=513 instead of 512 (phantom entry reads meta page 0)
  Page 1:  Leaf k0001-k0010 (current, original values)
  Page 2:  Leaf k0011-k0020 (current, original values)
  Page 3:  Leaf k0021-k0030 (v1 old values, FREED)
  Page 4:  Leaf k0031-k0040 (v1 old values, FREED, BUT also reachable from corrupted root)
  Page 5:  Leaf k0041-k0050 (current, original values)
  Page 6:  Leaf k0051-k0060 (current, original values)
  Page 7:  Leaf k0061-k0070 (current, original values)
  Page 8:  Leaf k0071-k0080 (current, original values)
  Page 9:  v1 internal root (FREED)
  Page 10: Leaf k0021-k0030 (v2 updated values, current)
  Page 11: Leaf k0031-k0040 (v2 updated values, SHOULD be current but orphaned due to stale ptr)
  Page 12: v2 internal root (CURRENT ROOT)
           CORRUPTION: key[2]="k0020" instead of "k0021" (stale key boundary)
           CORRUPTION: ptr[3]=4 instead of 11 (stale pointer to freed page)
  Page 13: Free list node 1 (next=19, items at seq-indices 509,510 -> [3,4])
  Page 14: Orphaned v0 leaf k0081-k0090
  Page 15: Orphaned v0 leaf k0091-k0100
  Page 16: Unused (zeros)
  Page 17: Unused (zeros)
  Page 18: Orphaned v0 internal (points to pages 14,15)
  Page 19: Free list node 2 (next=0, item at seq-index 0 -> [9])
"""

import struct
import os

PAGE_SIZE = 4096
BNODE_INTERNAL = 1
BNODE_LEAF = 2
SIGNATURE = b"BYO_DB_MAGIC_V01"
FREE_LIST_CAP = (PAGE_SIZE - 8) // 8  # 511
VAL_SIZE = 200
NUM_PAGES = 20


def pad_value(s, length=VAL_SIZE):
    """Pad string to exactly `length` bytes with null bytes."""
    b = s.encode("utf-8")
    if len(b) >= length:
        return b[:length]
    return b + b"\x00" * (length - len(b))


def encode_leaf(keys_vals):
    """Encode a B+tree leaf node. keys_vals: list of (key_bytes, val_bytes)."""
    nkeys = len(keys_vals)
    buf = bytearray(PAGE_SIZE)
    struct.pack_into("<HH", buf, 0, BNODE_LEAF, nkeys)

    # Pointers (all zero for leaves)
    for i in range(nkeys):
        struct.pack_into("<Q", buf, 4 + 8 * i, 0)

    # KV data + offset array
    kv_start = 4 + 8 * nkeys + 2 * nkeys
    cumulative = 0
    for i in range(nkeys):
        key, val = keys_vals[i]
        if isinstance(key, str):
            key = key.encode()
        if isinstance(val, str):
            val = val.encode()

        pos = kv_start + cumulative
        struct.pack_into("<HH", buf, pos, len(key), len(val))
        buf[pos + 4 : pos + 4 + len(key)] = key
        buf[pos + 4 + len(key) : pos + 4 + len(key) + len(val)] = val

        cumulative += 4 + len(key) + len(val)
        struct.pack_into("<H", buf, 4 + 8 * nkeys + 2 * i, cumulative)

    return bytes(buf)


def encode_internal(keys_ptrs):
    """Encode an internal B+tree node. keys_ptrs: list of (key_bytes, child_page)."""
    nkeys = len(keys_ptrs)
    buf = bytearray(PAGE_SIZE)
    struct.pack_into("<HH", buf, 0, BNODE_INTERNAL, nkeys)

    # Pointers
    for i in range(nkeys):
        struct.pack_into("<Q", buf, 4 + 8 * i, keys_ptrs[i][1])

    # KV data (val_len=0 for internal nodes)
    kv_start = 4 + 8 * nkeys + 2 * nkeys
    cumulative = 0
    for i in range(nkeys):
        key = keys_ptrs[i][0]
        if isinstance(key, str):
            key = key.encode()

        pos = kv_start + cumulative
        struct.pack_into("<HH", buf, pos, len(key), 0)
        buf[pos + 4 : pos + 4 + len(key)] = key

        cumulative += 4 + len(key)
        struct.pack_into("<H", buf, 4 + 8 * nkeys + 2 * i, cumulative)

    return bytes(buf)


def generate():
    pages = [bytearray(PAGE_SIZE) for _ in range(NUM_PAGES)]

    # --- Current tree leaves (original values) ---
    for pg, start in [(1, 1), (2, 11), (5, 41), (6, 51), (7, 61), (8, 71)]:
        data = [
            (f"k{i:04d}".encode(), pad_value(f"original_val_{i:04d}"))
            for i in range(start, start + 10)
        ]
        pages[pg] = encode_leaf(data)

    # --- v1 old leaves (FREED via free list) ---
    for pg, start in [(3, 21), (4, 31)]:
        data = [
            (f"k{i:04d}".encode(), pad_value(f"v1_old_val_{i:04d}"))
            for i in range(start, start + 10)
        ]
        pages[pg] = encode_leaf(data)

    # --- v1 internal root (FREED) ---
    pages[9] = encode_internal(
        [
            (b"k0001", 1),
            (b"k0011", 2),
            (b"k0021", 3),
            (b"k0031", 4),
            (b"k0041", 5),
            (b"k0051", 6),
            (b"k0061", 7),
            (b"k0071", 8),
        ]
    )

    # --- v2 updated leaves (current) ---
    for pg, start in [(10, 21), (11, 31)]:
        data = [
            (f"k{i:04d}".encode(), pad_value(f"v2_updated_{i:04d}"))
            for i in range(start, start + 10)
        ]
        pages[pg] = encode_leaf(data)

    # --- v2 internal root (CURRENT ROOT — CORRUPTED) ---
    # CORRUPTION 1: key[2]="k0020" instead of "k0021" (stale key boundary)
    # CORRUPTION 2: ptr[3]=4 instead of 11 (stale pointer to freed page)
    pages[12] = encode_internal(
        [
            (b"k0001", 1),
            (b"k0011", 2),
            (b"k0020", 10),  # CORRUPTION: key should be "k0021"
            (b"k0031", 4),   # CORRUPTION: ptr should be 11, not 4
            (b"k0041", 5),
            (b"k0051", 6),
            (b"k0061", 7),
            (b"k0071", 8),
        ]
    )

    # --- Free list node 1 (page 13) ---
    # Items at indices 509 and 510 (near end of page capacity).
    # next_ptr -> page 19
    fl1 = bytearray(PAGE_SIZE)
    struct.pack_into("<Q", fl1, 0, 19)  # next = page 19
    struct.pack_into("<Q", fl1, 8 + 509 * 8, 3)  # freed page 3
    struct.pack_into("<Q", fl1, 8 + 510 * 8, 4)  # freed page 4
    pages[13] = bytes(fl1)

    # --- Orphaned v0 leaves ---
    for pg, start in [(14, 81), (15, 91)]:
        data = [
            (f"k{i:04d}".encode(), pad_value(f"v0_ancient_{i:04d}"))
            for i in range(start, start + 10)
        ]
        pages[pg] = encode_leaf(data)

    # --- Pages 16, 17: unused (already zero-filled) ---

    # --- Orphaned v0 internal (page 18) ---
    pages[18] = encode_internal(
        [
            (b"k0081", 14),
            (b"k0091", 15),
        ]
    )

    # --- Free list node 2 (page 19) ---
    # Item at index 0. next_ptr = 0 (end of list).
    fl2 = bytearray(PAGE_SIZE)
    struct.pack_into("<Q", fl2, 0, 0)  # next = 0 (end)
    struct.pack_into("<Q", fl2, 8, 9)  # item at index 0 = page 9
    pages[19] = bytes(fl2)

    # --- Meta page (page 0) ---
    # Free list: head_page=13, head_seq=509, tail_page=19, tail_seq=513
    # CORRUPTION 3: fl_tail_seq=513 instead of 512
    #   seq 509 -> idx 509 in page 13 -> value 3
    #   seq 510 -> idx 510 in page 13 -> value 4
    #   seq 511 -> idx 0 in page 19 (511 % 511 = 0, cross boundary) -> value 9
    #   seq 512 -> idx 1 in page 19 (512 % 511 = 1) -> value 0 (PHANTOM: meta page!)
    meta = bytearray(PAGE_SIZE)
    meta[0:16] = SIGNATURE
    struct.pack_into("<Q", meta, 16, 12)   # root_ptr
    struct.pack_into("<Q", meta, 24, 20)   # pages_used
    struct.pack_into("<Q", meta, 32, 13)   # fl_head_page
    struct.pack_into("<Q", meta, 40, 509)  # fl_head_seq
    struct.pack_into("<Q", meta, 48, 19)   # fl_tail_page
    struct.pack_into("<Q", meta, 56, 513)  # fl_tail_seq (CORRUPTION: should be 512)
    pages[0] = bytes(meta)

    # Write database
    os.makedirs("/app", exist_ok=True)
    with open("/app/database.db", "wb") as f:
        for pg in pages:
            f.write(bytes(pg))

    total_bytes = NUM_PAGES * PAGE_SIZE
    print(f"Generated database: {NUM_PAGES} pages, {total_bytes} bytes")


if __name__ == "__main__":
    generate()
