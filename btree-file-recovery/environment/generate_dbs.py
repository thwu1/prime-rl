#!/usr/bin/env python3
"""Generate test B+tree database files with various integrity properties.

Run during Docker build to create /app/databases/*.db.
"""
import struct
import zlib
import os

PAGE_SIZE = 4096
BNODE_INTERNAL = 1
BNODE_LEAF = 2
MAGIC = b"BYODB_TBENCH_V1\x00"


def make_meta_page(root_ptr, num_pages):
    data = bytearray(PAGE_SIZE)
    data[0:16] = MAGIC
    struct.pack_into('<Q', data, 16, root_ptr)
    struct.pack_into('<Q', data, 24, num_pages)
    crc = zlib.crc32(bytes(data[0:32])) & 0xFFFFFFFF
    struct.pack_into('<I', data, 32, crc)
    return bytes(data)


def encode_kv(key, val):
    return struct.pack('<HH', len(key), len(val)) + key + val


def make_leaf_node(kvs):
    nkeys = len(kvs)
    data = bytearray(PAGE_SIZE)
    struct.pack_into('<HH', data, 0, BNODE_LEAF, nkeys)
    kv_parts = [encode_kv(k, v) for k, v in kvs]
    offset_start = 4 + nkeys * 8
    cumulative = 0
    for i, part in enumerate(kv_parts):
        cumulative += len(part)
        struct.pack_into('<H', data, offset_start + i * 2, cumulative)
    kv_area_start = 4 + nkeys * 10
    pos = kv_area_start
    for part in kv_parts:
        data[pos:pos + len(part)] = part
        pos += len(part)
    return bytes(data)


def make_internal_node(keys, child_ptrs):
    nkeys = len(keys)
    assert len(child_ptrs) == nkeys
    data = bytearray(PAGE_SIZE)
    struct.pack_into('<HH', data, 0, BNODE_INTERNAL, nkeys)
    for i, ptr in enumerate(child_ptrs):
        struct.pack_into('<Q', data, 4 + i * 8, ptr)
    kv_parts = [encode_kv(k, b'') for k in keys]
    offset_start = 4 + nkeys * 8
    cumulative = 0
    for i, part in enumerate(kv_parts):
        cumulative += len(part)
        struct.pack_into('<H', data, offset_start + i * 2, cumulative)
    kv_area_start = 4 + nkeys * 10
    pos = kv_area_start
    for part in kv_parts:
        data[pos:pos + len(part)] = part
        pos += len(part)
    return bytes(data)


def build_tree(kvs, max_per_leaf=20):
    """Build a B+tree bottom-up from sorted KV pairs.
    Returns (pages_dict, root_page_num, total_pages_including_meta).
    """
    pages = {}
    next_page = [1]

    def alloc(page_data):
        pnum = next_page[0]
        pages[pnum] = page_data
        next_page[0] += 1
        return pnum

    leaf_chunks = [kvs[i:i + max_per_leaf]
                   for i in range(0, len(kvs), max_per_leaf)]
    level = []
    for chunk in leaf_chunks:
        pnum = alloc(make_leaf_node(chunk))
        level.append((chunk[0][0], pnum))

    while len(level) > 1:
        groups = [level[i:i + 50] for i in range(0, len(level), 50)]
        next_level = []
        for group in groups:
            keys = [k for k, _ in group]
            ptrs = [p for _, p in group]
            pnum = alloc(make_internal_node(keys, ptrs))
            next_level.append((keys[0], pnum))
        level = next_level

    root = level[0][1]
    total = next_page[0]
    return pages, root, total


def write_db(filepath, pages, root, total_pages):
    meta = make_meta_page(root, total_pages)
    with open(filepath, 'wb') as f:
        f.write(meta)
        for i in range(1, total_pages):
            f.write(pages.get(i, b'\x00' * PAGE_SIZE))


# --------------- Database generators ---------------

def gen_valid(path, n=100):
    kvs = [(f"key_{i:05d}".encode(), f"value_{i:05d}".encode())
           for i in range(n)]
    pages, root, total = build_tree(kvs)
    write_db(path, pages, root, total)


def gen_orphaned(path, n=100):
    kvs = [(f"key_{i:05d}".encode(), f"value_{i:05d}".encode())
           for i in range(n)]
    pages, root, total = build_tree(kvs)
    write_db(path, pages, root, total + 3)


def gen_bad_order(path, n=100):
    kvs = [(f"key_{i:05d}".encode(), f"value_{i:05d}".encode())
           for i in range(n)]
    pages, root, total = build_tree(kvs)
    page2 = bytearray(pages[2])
    nkeys = struct.unpack_from('<H', page2, 2)[0]
    kv_area_start = 4 + nkeys * 10
    offset_start = 4 + nkeys * 8
    ends = [struct.unpack_from('<H', page2, offset_start + i * 2)[0]
            for i in range(nkeys)]
    starts = [0] + ends[:-1]
    pair_data = [bytes(page2[kv_area_start + starts[i]:
                              kv_area_start + ends[i]])
                 for i in range(nkeys)]
    pair_data[0], pair_data[1] = pair_data[1], pair_data[0]
    pos = kv_area_start
    cumulative = 0
    for i, pd in enumerate(pair_data):
        page2[pos:pos + len(pd)] = pd
        pos += len(pd)
        cumulative += len(pd)
        struct.pack_into('<H', page2, offset_start + i * 2, cumulative)
    pages[2] = bytes(page2)
    write_db(path, pages, root, total)


def gen_dangling(path, n=100):
    kvs = [(f"key_{i:05d}".encode(), f"value_{i:05d}".encode())
           for i in range(n)]
    pages, root, total = build_tree(kvs)
    root_page = bytearray(pages[root])
    nkeys = struct.unpack_from('<H', root_page, 2)[0]
    struct.pack_into('<Q', root_page, 4 + (nkeys - 1) * 8, 9999)
    pages[root] = bytes(root_page)
    write_db(path, pages, root, total)


def gen_bad_checksum(path, n=100):
    kvs = [(f"key_{i:05d}".encode(), f"value_{i:05d}".encode())
           for i in range(n)]
    pages, root, total = build_tree(kvs)
    write_db(path, pages, root, total)
    with open(path, 'r+b') as f:
        f.seek(32)
        f.write(struct.pack('<I', 0xDEADBEEF))


def gen_corrupted_node(path, n=100):
    kvs = [(f"key_{i:05d}".encode(), f"value_{i:05d}".encode())
           for i in range(n)]
    pages, root, total = build_tree(kvs)
    page3 = bytearray(pages[3])
    struct.pack_into('<H', page3, 2, 500)
    pages[3] = bytes(page3)
    write_db(path, pages, root, total)


if __name__ == '__main__':
    os.makedirs('/app/databases', exist_ok=True)
    gen_valid('/app/databases/valid.db', 100)
    gen_orphaned('/app/databases/orphaned.db', 100)
    gen_bad_order('/app/databases/bad_order.db', 100)
    gen_dangling('/app/databases/dangling.db', 100)
    gen_bad_checksum('/app/databases/bad_checksum.db', 100)
    gen_corrupted_node('/app/databases/corrupted_node.db', 100)
    print("Generated all test databases")
