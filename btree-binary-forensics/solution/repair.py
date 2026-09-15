#!/usr/bin/env python3

"""B+Tree Database Corruption Repair Tool.

Diagnoses structural violations in a B+tree database file, repairs
all corruptions, and produces a diagnostic report and repaired database.
"""

import json
import struct

PAGE_SIZE = 4096
BNODE_INTERNAL = 1
BNODE_LEAF = 2
FREE_LIST_CAP = (PAGE_SIZE - 8) // 8  # 511


def read_db(path):
    with open(path, "rb") as f:
        return bytearray(f.read())


def pg(data, p):
    return data[p * PAGE_SIZE : (p + 1) * PAGE_SIZE]


def get_type(page):
    return struct.unpack_from("<H", page, 0)[0]


def get_nkeys(page):
    return struct.unpack_from("<H", page, 2)[0]


def get_ptr(page, i):
    return struct.unpack_from("<Q", page, 4 + 8 * i)[0]


def get_key(page, idx):
    nkeys = get_nkeys(page)
    kv_start = 4 + 8 * nkeys + 2 * nkeys
    if idx == 0:
        pos = kv_start
    else:
        off = struct.unpack_from("<H", page, 4 + 8 * nkeys + 2 * (idx - 1))[0]
        pos = kv_start + off
    klen = struct.unpack_from("<H", page, pos)[0]
    return page[pos + 4 : pos + 4 + klen].decode()


def get_kv(page, idx):
    nkeys = get_nkeys(page)
    kv_start = 4 + 8 * nkeys + 2 * nkeys
    if idx == 0:
        pos = kv_start
    else:
        off = struct.unpack_from("<H", page, 4 + 8 * nkeys + 2 * (idx - 1))[0]
        pos = kv_start + off
    klen = struct.unpack_from("<H", page, pos)[0]
    vlen = struct.unpack_from("<H", page, pos + 2)[0]
    k = page[pos + 4 : pos + 4 + klen].decode()
    v = page[pos + 4 + klen : pos + 4 + klen + vlen].rstrip(b"\x00").decode()
    return k, v


def try_parse(page):
    t = get_type(page)
    n = get_nkeys(page)
    if t not in (BNODE_INTERNAL, BNODE_LEAF) or n == 0 or n > 500:
        return None
    return {"type": t, "nkeys": n}


def encode_internal(keys_ptrs):
    nkeys = len(keys_ptrs)
    buf = bytearray(PAGE_SIZE)
    struct.pack_into("<HH", buf, 0, BNODE_INTERNAL, nkeys)
    for i, (key, ptr) in enumerate(keys_ptrs):
        struct.pack_into("<Q", buf, 4 + 8 * i, ptr)
    kv_start = 4 + 8 * nkeys + 2 * nkeys
    cum = 0
    for i, (key, ptr) in enumerate(keys_ptrs):
        k = key.encode() if isinstance(key, str) else key
        pos = kv_start + cum
        struct.pack_into("<HH", buf, pos, len(k), 0)
        buf[pos + 4 : pos + 4 + len(k)] = k
        cum += 4 + len(k)
        struct.pack_into("<H", buf, 4 + 8 * nkeys + 2 * i, cum)
    return bytes(buf)


def main():
    data = read_db("/app/database.db")

    # Parse meta
    root_ptr = struct.unpack_from("<Q", data, 16)[0]
    pages_used = struct.unpack_from("<Q", data, 24)[0]
    fl_head_page = struct.unpack_from("<Q", data, 32)[0]
    fl_head_seq = struct.unpack_from("<Q", data, 40)[0]
    fl_tail_seq = struct.unpack_from("<Q", data, 56)[0]

    # ── Phase 1: Walk B+tree ──
    reachable = set()
    current_data = {}
    violations = []

    def walk(p):
        if p in reachable or p >= pages_used:
            return
        reachable.add(p)
        page = pg(data, p)
        t = get_type(page)
        n = get_nkeys(page)
        if t == BNODE_INTERNAL:
            for i in range(n):
                child = get_ptr(page, i)
                if child == 0 or child >= pages_used:
                    continue
                pkey = get_key(page, i)
                cpage = pg(data, child)
                cfirst = get_key(cpage, 0)
                if pkey != cfirst:
                    violations.append({
                        "type": "KEY_BOUNDARY_MISMATCH",
                        "page": int(p),
                        "description": (
                            f"key[{i}]='{pkey}' does not match "
                            f"child page {child} first_key='{cfirst}'"
                        ),
                    })
                walk(child)
        elif t == BNODE_LEAF:
            for i in range(n):
                k, v = get_kv(page, i)
                current_data[k] = v

    walk(root_ptr)

    # ── Phase 2: Walk free list ──
    freed = []
    fl_nodes = set()
    cur = fl_head_page
    seq = fl_head_seq

    while seq < fl_tail_seq:
        fl_nodes.add(cur)
        idx = seq % FREE_LIST_CAP
        page = pg(data, cur)
        item = struct.unpack_from("<Q", page, 8 + 8 * idx)[0]

        if item == 0:
            violations.append({
                "type": "FREELIST_REFERENCES_META",
                "page": int(cur),
                "description": f"seq={seq} idx={idx} references meta page 0",
            })
        elif item in reachable:
            violations.append({
                "type": "DOUBLE_ALLOCATION",
                "page": int(item),
                "description": (
                    f"page {item} is both reachable from tree "
                    f"and freed (seq={seq})"
                ),
            })

        freed.append(int(item))
        seq += 1
        if seq < fl_tail_seq and seq % FREE_LIST_CAP == 0:
            nxt = struct.unpack_from("<Q", page, 0)[0]
            cur = nxt

    freed_set = set(f for f in freed if 0 < f < pages_used)

    # ── Phase 3: Classify pages ──
    page_map = {}
    for i in range(pages_used):
        if i == 0:
            page_map[str(i)] = "meta"
        elif i in reachable:
            p = pg(data, i)
            page_map[str(i)] = "internal" if get_type(p) == BNODE_INTERNAL else "leaf"
        elif i in fl_nodes:
            page_map[str(i)] = "free_list"
        elif i in freed_set:
            page_map[str(i)] = "free"
        else:
            p = pg(data, i)
            nd = try_parse(p)
            if nd:
                page_map[str(i)] = (
                    "orphaned_internal" if nd["type"] == BNODE_INTERNAL
                    else "orphaned_leaf"
                )
            else:
                page_map[str(i)] = "unused"

    # ── Phase 4: Tree stats ──
    depth = 1
    p = root_ptr
    while True:
        page = pg(data, p)
        if get_type(page) == BNODE_LEAF:
            break
        depth += 1
        p = get_ptr(page, 0)

    tree_stats = {
        "depth": depth,
        "internal_nodes": sum(1 for v in page_map.values() if v == "internal"),
        "leaf_nodes": sum(1 for v in page_map.values() if v == "leaf"),
        "total_keys": len(current_data),
    }

    # ══ REPAIR ══════════════════════════════════════════════════

    repaired = bytearray(data)

    # Fix 1: Rebuild root with corrected key boundaries from children
    root_page = pg(data, root_ptr)
    nkeys = get_nkeys(root_page)
    keys_ptrs = []
    for i in range(nkeys):
        ptr = get_ptr(root_page, i)
        child_page = pg(data, ptr)
        correct_key = get_key(child_page, 0)
        keys_ptrs.append((correct_key, ptr))

    # Fix 2: Replace pointers to freed pages with correct orphaned pages
    for i, (key, ptr) in enumerate(keys_ptrs):
        if ptr in freed_set:
            # Find the orphaned leaf with matching first key
            for pg_num in range(pages_used):
                if page_map.get(str(pg_num)) != "orphaned_leaf":
                    continue
                orphan = pg(data, pg_num)
                if get_key(orphan, 0) == key:
                    keys_ptrs[i] = (key, pg_num)
                    break

    new_root = encode_internal(keys_ptrs)
    off = root_ptr * PAGE_SIZE
    repaired[off : off + PAGE_SIZE] = new_root

    # Fix 3: Correct fl_tail_seq by excluding phantom entries
    correct_tail = fl_head_seq
    cur = fl_head_page
    s = fl_head_seq
    while s < fl_tail_seq:
        idx = s % FREE_LIST_CAP
        page = pg(data, cur)
        item = struct.unpack_from("<Q", page, 8 + 8 * idx)[0]
        if item == 0 or item >= pages_used:
            break
        correct_tail = s + 1
        s += 1
        if s < fl_tail_seq and s % FREE_LIST_CAP == 0:
            nxt = struct.unpack_from("<Q", page, 0)[0]
            cur = nxt

    struct.pack_into("<Q", repaired, 56, correct_tail)

    # Write outputs
    with open("/app/database_repaired.db", "wb") as f:
        f.write(repaired)

    report = {
        "violations": violations,
        "page_map": page_map,
        "tree_stats": tree_stats,
    }
    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Violations found: {len(violations)}")
    for v in violations:
        print(f"  [{v['type']}] page {v['page']}: {v['description']}")
    print(f"Repaired database written to /app/database_repaired.db")
    print(f"Report written to /app/report.json")


if __name__ == "__main__":
    main()
