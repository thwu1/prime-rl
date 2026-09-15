#!/usr/bin/env python3

"""B+Tree Database Binary Forensics Analyzer.

Reads a B+tree database file and produces a JSON report containing:
- current_data: KV pairs reachable from the current root
- orphaned_data: KV pairs in orphaned leaf pages
- page_map: classification of every page
- free_list_pages: page numbers stored as freed items in the free list
- tree_stats: depth, node counts, key count for the current tree
"""

import json
import struct

PAGE_SIZE = 4096
BNODE_INTERNAL = 1
BNODE_LEAF = 2
SIGNATURE = b"BYO_DB_MAGIC_V01"
FREE_LIST_CAP = (PAGE_SIZE - 8) // 8  # 511


def read_all_pages(filepath):
    with open(filepath, "rb") as f:
        data = f.read()
    n = len(data) // PAGE_SIZE
    return [data[i * PAGE_SIZE : (i + 1) * PAGE_SIZE] for i in range(n)]


def parse_meta(page):
    sig = page[0:16]
    if sig != SIGNATURE:
        raise ValueError(f"Invalid signature: {sig!r}")
    return {
        "root_ptr": struct.unpack_from("<Q", page, 16)[0],
        "pages_used": struct.unpack_from("<Q", page, 24)[0],
        "fl_head_page": struct.unpack_from("<Q", page, 32)[0],
        "fl_head_seq": struct.unpack_from("<Q", page, 40)[0],
        "fl_tail_page": struct.unpack_from("<Q", page, 48)[0],
        "fl_tail_seq": struct.unpack_from("<Q", page, 56)[0],
    }


def try_parse_node(page):
    """Attempt to parse a page as a B+tree node. Returns dict or None."""
    btype = struct.unpack_from("<H", page, 0)[0]
    nkeys = struct.unpack_from("<H", page, 2)[0]

    if btype not in (BNODE_INTERNAL, BNODE_LEAF):
        return None
    if nkeys == 0 or nkeys > 500:
        return None

    # Sanity: check that header + pointers + offsets fit in page
    header_size = 4 + 8 * nkeys + 2 * nkeys
    if header_size > PAGE_SIZE:
        return None

    # Read pointers
    ptrs = []
    for i in range(nkeys):
        ptrs.append(struct.unpack_from("<Q", page, 4 + 8 * i)[0])

    # Read KV pairs via offset array
    kv_data_start = header_size
    kvs = []
    for idx in range(nkeys):
        if idx == 0:
            kv_pos = kv_data_start
        else:
            # offset_array[idx-1] at byte offset 4 + 8*nkeys + 2*(idx-1)
            off = struct.unpack_from("<H", page, 4 + 8 * nkeys + 2 * (idx - 1))[0]
            kv_pos = kv_data_start + off

        if kv_pos + 4 > PAGE_SIZE:
            return None

        klen = struct.unpack_from("<H", page, kv_pos)[0]
        vlen = struct.unpack_from("<H", page, kv_pos + 2)[0]

        if kv_pos + 4 + klen + vlen > PAGE_SIZE:
            return None

        key = page[kv_pos + 4 : kv_pos + 4 + klen]
        val = page[kv_pos + 4 + klen : kv_pos + 4 + klen + vlen]
        kvs.append((key, val))

    return {"type": btype, "nkeys": nkeys, "ptrs": ptrs, "kvs": kvs}


def traverse_tree(pages, root_ptr):
    """Walk the B+tree from root_ptr. Returns (data_dict, reachable_page_set)."""
    data = {}
    reachable = set()

    def visit(pg):
        if pg in reachable or pg >= len(pages):
            return
        reachable.add(pg)
        node = try_parse_node(pages[pg])
        if node is None:
            return
        if node["type"] == BNODE_LEAF:
            for k, v in node["kvs"]:
                data[k.decode("utf-8")] = v.rstrip(b"\x00").decode("utf-8")
        elif node["type"] == BNODE_INTERNAL:
            for ptr in node["ptrs"]:
                if ptr > 0:
                    visit(ptr)

    visit(root_ptr)
    return data, reachable


def walk_free_list(pages, meta):
    """Parse the free list. Returns (freed_page_numbers, free_list_node_pages)."""
    freed = []
    fl_nodes = set()

    head_page = meta["fl_head_page"]
    head_seq = meta["fl_head_seq"]
    tail_seq = meta["fl_tail_seq"]

    if head_page == 0 or head_seq >= tail_seq:
        return freed, fl_nodes

    cur_page = head_page
    seq = head_seq

    while seq < tail_seq:
        fl_nodes.add(cur_page)
        idx = seq % FREE_LIST_CAP
        item = struct.unpack_from("<Q", pages[cur_page], 8 + 8 * idx)[0]
        freed.append(int(item))
        seq += 1
        if seq < tail_seq and seq % FREE_LIST_CAP == 0:
            next_ptr = struct.unpack_from("<Q", pages[cur_page], 0)[0]
            cur_page = int(next_ptr)

    # Ensure the last visited page is in the set
    if cur_page not in fl_nodes:
        fl_nodes.add(cur_page)

    return freed, fl_nodes


def compute_depth(pages, pg):
    """Compute tree depth starting from page pg."""
    node = try_parse_node(pages[pg])
    if node is None or node["type"] == BNODE_LEAF:
        return 1
    # Follow the first child pointer
    child = node["ptrs"][0]
    if child == 0 or child >= len(pages):
        return 1
    return 1 + compute_depth(pages, child)


def analyze(db_path, output_path):
    pages = read_all_pages(db_path)
    meta = parse_meta(pages[0])
    pages_used = int(meta["pages_used"])

    # Step 1: traverse current tree
    current_data, reachable = traverse_tree(pages, meta["root_ptr"])

    # Step 2: walk free list
    freed_pages, fl_node_pages = walk_free_list(pages, meta)
    freed_set = set(freed_pages)

    # Step 3: classify every page
    page_map = {}
    orphaned_data = {}

    for i in range(pages_used):
        if i == 0:
            page_map[str(i)] = "meta"
        elif i in reachable:
            node = try_parse_node(pages[i])
            if node and node["type"] == BNODE_INTERNAL:
                page_map[str(i)] = "internal"
            else:
                page_map[str(i)] = "leaf"
        elif i in fl_node_pages:
            page_map[str(i)] = "free_list"
        elif i in freed_set:
            page_map[str(i)] = "free"
        else:
            node = try_parse_node(pages[i])
            if node is not None:
                if node["type"] == BNODE_INTERNAL:
                    page_map[str(i)] = "orphaned_internal"
                else:
                    page_map[str(i)] = "orphaned_leaf"
                    for k, v in node["kvs"]:
                        orphaned_data[k.decode("utf-8")] = (
                            v.rstrip(b"\x00").decode("utf-8")
                        )
            else:
                page_map[str(i)] = "unused"

    # Step 4: tree statistics
    depth = compute_depth(pages, meta["root_ptr"])
    internal_count = sum(1 for v in page_map.values() if v == "internal")
    leaf_count = sum(1 for v in page_map.values() if v == "leaf")

    report = {
        "current_data": dict(sorted(current_data.items())),
        "orphaned_data": dict(sorted(orphaned_data.items())),
        "page_map": page_map,
        "free_list_pages": sorted(freed_pages),
        "tree_stats": {
            "depth": depth,
            "internal_nodes": internal_count,
            "leaf_nodes": leaf_count,
            "total_keys": len(current_data),
        },
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {output_path}")
    print(f"  Current keys: {len(current_data)}")
    print(f"  Orphaned keys: {len(orphaned_data)}")
    print(f"  Free list items: {sorted(freed_pages)}")
    print(f"  Tree depth: {depth}")


if __name__ == "__main__":
    analyze("/app/database.db", "/app/report.json")
