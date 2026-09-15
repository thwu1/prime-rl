#!/usr/bin/env python3
"""B+Tree database recovery and repair tool.

Analyzes a binary B+tree database file for integrity violations,
recovers parseable key-value pairs, and rebuilds a structurally
valid B+tree database file from the recovered data.

"""
import json
import struct
import sys
import zlib

PAGE_SIZE = 4096
BNODE_INTERNAL = 1
BNODE_LEAF = 2
MAGIC = b"BYODB_TBENCH_V1\x00"


# ==================================================================
# Analysis — parse and validate
# ==================================================================


def read_pages(filepath):
    with open(filepath, "rb") as f:
        data = f.read()
    pages = []
    for i in range(0, len(data), PAGE_SIZE):
        page = data[i : i + PAGE_SIZE]
        if len(page) < PAGE_SIZE:
            page = page + b"\x00" * (PAGE_SIZE - len(page))
        pages.append(page)
    return pages


def parse_meta(page):
    magic = page[0:16]
    root_page = struct.unpack_from("<Q", page, 16)[0]
    num_pages = struct.unpack_from("<Q", page, 24)[0]
    stored_crc = struct.unpack_from("<I", page, 32)[0]
    computed_crc = zlib.crc32(page[0:32]) & 0xFFFFFFFF
    return {
        "magic_valid": magic == MAGIC,
        "root_page": int(root_page),
        "num_pages": int(num_pages),
        "checksum_valid": stored_crc == computed_crc,
    }


def parse_node(page, page_num, num_pages):
    errors = []
    node_type = struct.unpack_from("<H", page, 0)[0]
    nkeys = struct.unpack_from("<H", page, 2)[0]

    if node_type not in (BNODE_INTERNAL, BNODE_LEAF):
        errors.append({
            "type": "corrupted_node",
            "page": page_num,
            "detail": f"Invalid node type {node_type}",
        })
        return None, errors

    min_fixed = 4 + nkeys * 10
    if min_fixed > PAGE_SIZE:
        errors.append({
            "type": "corrupted_node",
            "page": page_num,
            "detail": (
                f"nkeys={nkeys} causes fixed area "
                f"({min_fixed}B) to exceed page size"
            ),
        })
        return None, errors

    pointers = []
    for i in range(nkeys):
        ptr = struct.unpack_from("<Q", page, 4 + i * 8)[0]
        pointers.append(ptr)

    offset_base = 4 + nkeys * 8
    offsets = []
    for i in range(nkeys):
        off = struct.unpack_from("<H", page, offset_base + i * 2)[0]
        offsets.append(off)

    kv_area_start = 4 + nkeys * 10
    kvs = []
    prev_end = 0
    for i in range(nkeys):
        kv_start = kv_area_start + prev_end
        kv_end_abs = kv_area_start + offsets[i]
        if kv_start + 4 > PAGE_SIZE or kv_end_abs > PAGE_SIZE:
            errors.append({
                "type": "corrupted_node",
                "page": page_num,
                "detail": f"KV pair {i} extends beyond page boundary",
            })
            return None, errors
        klen = struct.unpack_from("<H", page, kv_start)[0]
        vlen = struct.unpack_from("<H", page, kv_start + 2)[0]
        data_end = kv_start + 4 + klen + vlen
        if data_end > PAGE_SIZE:
            errors.append({
                "type": "corrupted_node",
                "page": page_num,
                "detail": f"KV pair {i} data extends beyond page",
            })
            return None, errors
        key = page[kv_start + 4 : kv_start + 4 + klen]
        val = page[kv_start + 4 + klen : kv_start + 4 + klen + vlen]
        kvs.append((key, val))
        prev_end = offsets[i]

    for i in range(1, len(kvs)):
        if kvs[i][0] <= kvs[i - 1][0]:
            errors.append({
                "type": "sort_violation",
                "page": page_num,
                "detail": (
                    f"Key at index {i} ({kvs[i][0]!r}) "
                    f"<= key at index {i-1} ({kvs[i-1][0]!r})"
                ),
            })
            break

    bad_ptrs = set()
    if node_type == BNODE_INTERNAL:
        for i, ptr in enumerate(pointers):
            if ptr >= num_pages or ptr == 0:
                errors.append({
                    "type": "dangling_pointer",
                    "page": page_num,
                    "detail": (
                        f"Child pointer[{i}] = {ptr} "
                        f"out of valid range (1..{num_pages-1})"
                    ),
                })
                bad_ptrs.add(i)

    return {
        "type": node_type,
        "nkeys": nkeys,
        "pointers": pointers,
        "kvs": kvs,
        "bad_ptrs": bad_ptrs,
    }, errors


# ==================================================================
# Rebuild — construct a valid B+tree from sorted KV pairs
# ==================================================================


def encode_kv(key, val):
    return struct.pack("<HH", len(key), len(val)) + key + val


def make_leaf_node(kvs):
    nkeys = len(kvs)
    data = bytearray(PAGE_SIZE)
    struct.pack_into("<HH", data, 0, BNODE_LEAF, nkeys)
    kv_parts = [encode_kv(k, v) for k, v in kvs]
    offset_start = 4 + nkeys * 8
    cumulative = 0
    for i, part in enumerate(kv_parts):
        cumulative += len(part)
        struct.pack_into("<H", data, offset_start + i * 2, cumulative)
    kv_area_start = 4 + nkeys * 10
    pos = kv_area_start
    for part in kv_parts:
        data[pos : pos + len(part)] = part
        pos += len(part)
    return bytes(data)


def make_internal_node(keys, child_ptrs):
    nkeys = len(keys)
    data = bytearray(PAGE_SIZE)
    struct.pack_into("<HH", data, 0, BNODE_INTERNAL, nkeys)
    for i, ptr in enumerate(child_ptrs):
        struct.pack_into("<Q", data, 4 + i * 8, ptr)
    kv_parts = [encode_kv(k, b"") for k in keys]
    offset_start = 4 + nkeys * 8
    cumulative = 0
    for i, part in enumerate(kv_parts):
        cumulative += len(part)
        struct.pack_into("<H", data, offset_start + i * 2, cumulative)
    kv_area_start = 4 + nkeys * 10
    pos = kv_area_start
    for part in kv_parts:
        data[pos : pos + len(part)] = part
        pos += len(part)
    return bytes(data)


def make_meta_page(root_ptr, num_pages):
    data = bytearray(PAGE_SIZE)
    data[0:16] = MAGIC
    struct.pack_into("<Q", data, 16, root_ptr)
    struct.pack_into("<Q", data, 24, num_pages)
    crc = zlib.crc32(bytes(data[0:32])) & 0xFFFFFFFF
    struct.pack_into("<I", data, 32, crc)
    return bytes(data)


def build_tree(kvs, max_per_leaf=20):
    pages = {}
    next_page = [1]

    def alloc(page_data):
        pnum = next_page[0]
        pages[pnum] = page_data
        next_page[0] += 1
        return pnum

    leaf_chunks = [
        kvs[i : i + max_per_leaf]
        for i in range(0, len(kvs), max_per_leaf)
    ]
    level = []
    for chunk in leaf_chunks:
        pnum = alloc(make_leaf_node(chunk))
        level.append((chunk[0][0], pnum))

    while len(level) > 1:
        groups = [level[i : i + 50] for i in range(0, len(level), 50)]
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


def write_repaired_db(filepath, pages, root, total_pages):
    meta = make_meta_page(root, total_pages)
    with open(filepath, "wb") as f:
        f.write(meta)
        for i in range(1, total_pages):
            f.write(pages.get(i, b"\x00" * PAGE_SIZE))


# ==================================================================
# Main — analyze, recover, rebuild
# ==================================================================


def recover(filepath, output_path):
    pages = read_pages(filepath)
    if not pages:
        return {
            "meta": {
                "magic_valid": False,
                "root_page": 0,
                "num_pages": 0,
                "checksum_valid": False,
            },
            "errors": [
                {"type": "corrupted_node", "page": None, "detail": "Empty file"}
            ],
            "recovered_kvs": [],
            "stats": {
                "total_pages": 0,
                "reachable_pages": 0,
                "orphaned_pages": 0,
            },
        }

    meta = parse_meta(pages[0])
    all_errors = []

    if not meta["checksum_valid"]:
        all_errors.append({
            "type": "bad_checksum",
            "page": 0,
            "detail": "Meta page CRC-32 checksum mismatch",
        })

    if not meta["magic_valid"]:
        all_errors.append({
            "type": "corrupted_node",
            "page": 0,
            "detail": "Invalid magic string in meta page",
        })

    num_pages = meta["num_pages"]
    root_page = meta["root_page"]

    recovered_bytes = []   # (key_bytes, val_bytes) for rebuild
    recovered_strs = []    # [key_str, val_str] for JSON report
    reachable = {0}

    def walk(page_num):
        if page_num in reachable:
            return
        if page_num >= num_pages or page_num >= len(pages):
            return

        reachable.add(page_num)
        node, errors = parse_node(pages[page_num], page_num, num_pages)
        all_errors.extend(errors)

        if node is None:
            return

        if node["type"] == BNODE_LEAF:
            for key, val in node["kvs"]:
                recovered_bytes.append((key, val))
                try:
                    recovered_strs.append(
                        [key.decode("utf-8"), val.decode("utf-8")]
                    )
                except UnicodeDecodeError:
                    recovered_strs.append([key.hex(), val.hex()])
        elif node["type"] == BNODE_INTERNAL:
            for i, ptr in enumerate(node["pointers"]):
                if i not in node["bad_ptrs"]:
                    walk(ptr)

    if root_page < num_pages and root_page < len(pages):
        walk(root_page)

    orphaned = num_pages - len(reachable)
    if orphaned > 0:
        all_errors.append({
            "type": "orphaned_pages",
            "page": None,
            "detail": f"{orphaned} page(s) not reachable from root",
        })

    recovered_bytes.sort(key=lambda kv: kv[0])
    recovered_strs.sort(key=lambda kv: kv[0])

    # Rebuild a valid B+tree from recovered data
    if recovered_bytes:
        r_pages, r_root, r_total = build_tree(recovered_bytes)
        write_repaired_db(output_path, r_pages, r_root, r_total)

    return {
        "meta": meta,
        "errors": all_errors,
        "recovered_kvs": recovered_strs,
        "stats": {
            "total_pages": int(num_pages),
            "reachable_pages": len(reachable),
            "orphaned_pages": int(orphaned),
        },
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            f"Usage: {sys.argv[0]} <input.db> <output.db>",
            file=sys.stderr,
        )
        sys.exit(1)
    result = recover(sys.argv[1], sys.argv[2])
    print(json.dumps(result, indent=2))
