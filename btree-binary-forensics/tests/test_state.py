
import json
import os
import struct
import subprocess

import pytest

PAGE_SIZE = 4096
BNODE_INTERNAL = 1
BNODE_LEAF = 2
FREE_LIST_CAP = (PAGE_SIZE - 8) // 8


# ── Helpers ──────────────────────────────────────────────────────


def _get_page(data, pg):
    return data[pg * PAGE_SIZE : (pg + 1) * PAGE_SIZE]


def _get_nkeys(page):
    return struct.unpack_from("<H", page, 2)[0]


def _get_type(page):
    return struct.unpack_from("<H", page, 0)[0]


def _get_ptr(page, i):
    return struct.unpack_from("<Q", page, 4 + 8 * i)[0]


def _get_key(page, idx):
    nkeys = _get_nkeys(page)
    kv_start = 4 + 8 * nkeys + 2 * nkeys
    if idx == 0:
        pos = kv_start
    else:
        off = struct.unpack_from("<H", page, 4 + 8 * nkeys + 2 * (idx - 1))[0]
        pos = kv_start + off
    klen = struct.unpack_from("<H", page, pos)[0]
    return page[pos + 4 : pos + 4 + klen].decode()


def _get_kv(page, idx):
    nkeys = _get_nkeys(page)
    kv_start = 4 + 8 * nkeys + 2 * nkeys
    if idx == 0:
        pos = kv_start
    else:
        off = struct.unpack_from("<H", page, 4 + 8 * nkeys + 2 * (idx - 1))[0]
        pos = kv_start + off
    klen = struct.unpack_from("<H", page, pos)[0]
    vlen = struct.unpack_from("<H", page, pos + 2)[0]
    key = page[pos + 4 : pos + 4 + klen].decode()
    val = page[pos + 4 + klen : pos + 4 + klen + vlen].rstrip(b"\x00").decode()
    return key, val


def _traverse_tree_kv(data):
    """Walk the B+tree in `data` and return {key: value}."""
    root = struct.unpack_from("<Q", data, 16)[0]
    pages_used = struct.unpack_from("<Q", data, 24)[0]
    kv = {}
    visited = set()

    def visit(pg):
        if pg in visited or pg >= pages_used:
            return
        visited.add(pg)
        page = _get_page(data, pg)
        ntype = _get_type(page)
        nkeys = _get_nkeys(page)
        if ntype == BNODE_INTERNAL:
            for i in range(nkeys):
                visit(_get_ptr(page, i))
        elif ntype == BNODE_LEAF:
            for i in range(nkeys):
                k, v = _get_kv(page, i)
                kv[k] = v

    visit(root)
    return kv


def _get_reachable(data):
    root = struct.unpack_from("<Q", data, 16)[0]
    pages_used = struct.unpack_from("<Q", data, 24)[0]
    reachable = set()

    def visit(pg):
        if pg in reachable or pg >= pages_used:
            return
        reachable.add(pg)
        page = _get_page(data, pg)
        if _get_type(page) == BNODE_INTERNAL:
            for i in range(_get_nkeys(page)):
                visit(_get_ptr(page, i))

    visit(root)
    return reachable


def _get_freed(data):
    fl_head_page = struct.unpack_from("<Q", data, 32)[0]
    fl_head_seq = struct.unpack_from("<Q", data, 40)[0]
    fl_tail_seq = struct.unpack_from("<Q", data, 56)[0]
    freed = set()
    cur = fl_head_page
    seq = fl_head_seq
    while seq < fl_tail_seq:
        idx = seq % FREE_LIST_CAP
        page = _get_page(data, cur)
        item = struct.unpack_from("<Q", page, 8 + 8 * idx)[0]
        if 0 < item < 10000:
            freed.add(item)
        seq += 1
        if seq < fl_tail_seq and seq % FREE_LIST_CAP == 0:
            cur = struct.unpack_from("<Q", page, 0)[0]
    return freed


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def report():
    with open("/app/report.json", "r") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def repaired_data():
    with open("/app/database_repaired.db", "rb") as f:
        return f.read()


# ══════════════════════════════════════════════════════════════════
# REPORT TESTS — diagnostic analysis of the corrupted database
# ══════════════════════════════════════════════════════════════════


def test_report_file_exists():
    assert os.path.exists("/app/report.json"), "/app/report.json not found"


def test_report_has_required_keys(report):
    for key in ("violations", "page_map", "tree_stats"):
        assert key in report, f"Missing top-level key: {key}"


def test_at_least_3_violations(report):
    assert len(report["violations"]) >= 3, (
        f"Expected >= 3 violations, got {len(report['violations'])}"
    )


def test_violation_types_distinct(report):
    types = set(v.get("type", "") for v in report["violations"])
    assert len(types) >= 2, "Must identify at least 2 distinct violation types"


def test_violation_on_page_12(report):
    """Root internal node (page 12) has a stale key boundary."""
    pages = [v.get("page") for v in report["violations"]]
    assert 12 in pages, "Must report a violation on page 12 (key boundary mismatch)"


def test_violation_on_page_4(report):
    """Page 4 is double-allocated: reachable from tree AND in free list."""
    pages = [v.get("page") for v in report["violations"]]
    assert 4 in pages, "Must report a violation involving page 4 (double allocation)"


def test_violation_freelist_corruption(report):
    """Free list contains a phantom entry referencing meta page 0."""
    found = False
    for v in report["violations"]:
        vtype = v.get("type", "").upper()
        desc = v.get("description", "").upper()
        if "META" in vtype or "META" in desc or "FREELIST" in vtype or "INVALID" in vtype:
            found = True
            break
    assert found, "Must detect free list corruption (phantom meta page entry)"


# ── Tree stats ───────────────────────────────────────────────────


def test_tree_stats_depth(report):
    assert report["tree_stats"]["depth"] == 2


def test_tree_stats_internal(report):
    assert report["tree_stats"]["internal_nodes"] == 1


def test_tree_stats_leaves(report):
    assert report["tree_stats"]["leaf_nodes"] == 8


def test_tree_stats_keys(report):
    assert report["tree_stats"]["total_keys"] == 80


# ── Page map (unambiguous pages only) ────────────────────────────


def test_page_map_completeness(report):
    for i in range(20):
        assert str(i) in report["page_map"], f"Page {i} not classified"


def test_page_map_meta(report):
    assert report["page_map"]["0"] == "meta"


def test_page_map_internal(report):
    assert report["page_map"]["12"] == "internal"


def test_page_map_free_list_nodes(report):
    assert report["page_map"]["13"] == "free_list"
    assert report["page_map"]["19"] == "free_list"


def test_page_map_free_pages(report):
    assert report["page_map"]["3"] == "free"
    assert report["page_map"]["9"] == "free"


def test_page_map_unused(report):
    assert report["page_map"]["16"] == "unused"
    assert report["page_map"]["17"] == "unused"


def test_page_map_current_leaves(report):
    for pg in ["1", "2", "5", "6", "7", "8", "10"]:
        assert report["page_map"][pg] == "leaf", (
            f"Page {pg} should be 'leaf', got '{report['page_map'][pg]}'"
        )


def test_page_map_orphaned_v0_leaves(report):
    assert report["page_map"]["14"] == "orphaned_leaf"
    assert report["page_map"]["15"] == "orphaned_leaf"


def test_page_map_orphaned_internal(report):
    assert report["page_map"]["18"] == "orphaned_internal"


def test_page_map_page_11_orphaned(report):
    """Page 11 has correct v2 data but is orphaned due to stale root pointer."""
    assert report["page_map"]["11"] == "orphaned_leaf", (
        f"Page 11 should be 'orphaned_leaf', got '{report['page_map']['11']}'"
    )


# ══════════════════════════════════════════════════════════════════
# REPAIR TESTS — verifying the corrected database file
# ══════════════════════════════════════════════════════════════════


def test_repaired_exists():
    assert os.path.exists("/app/database_repaired.db"), "database_repaired.db not found"


def test_repaired_size():
    size = os.path.getsize("/app/database_repaired.db")
    assert size == 20 * PAGE_SIZE, f"Expected {20*PAGE_SIZE} bytes, got {size}"


def test_repaired_signature(repaired_data):
    assert repaired_data[:16] == b"BYO_DB_MAGIC_V01"


def test_repaired_meta_root_ptr(repaired_data):
    root = struct.unpack_from("<Q", repaired_data, 16)[0]
    assert root == 12, f"Root should be page 12, got {root}"


def test_repaired_meta_pages_used(repaired_data):
    pu = struct.unpack_from("<Q", repaired_data, 24)[0]
    assert pu == 20, f"pages_used should be 20, got {pu}"


def test_repaired_meta_fl_tail_seq(repaired_data):
    tail_seq = struct.unpack_from("<Q", repaired_data, 56)[0]
    assert tail_seq == 512, f"fl_tail_seq should be 512, got {tail_seq}"


def test_repaired_root_key_2(repaired_data):
    """Root internal node key[2] must be 'k0021' (not stale 'k0020')."""
    page = _get_page(repaired_data, 12)
    key = _get_key(page, 2)
    assert key == "k0021", f"Root key[2] should be 'k0021', got '{key}'"


def test_repaired_root_ptr_3(repaired_data):
    """Root ptr[3] must point to page 11 (v2 data), not page 4 (freed)."""
    page = _get_page(repaired_data, 12)
    ptr = _get_ptr(page, 3)
    assert ptr == 11, f"Root ptr[3] should be 11, got {ptr}"


def test_repaired_tree_80_keys(repaired_data):
    kv = _traverse_tree_kv(repaired_data)
    assert len(kv) == 80, f"Expected 80 keys, got {len(kv)}"


def test_repaired_all_keys_present(repaired_data):
    kv = _traverse_tree_kv(repaired_data)
    for i in range(1, 81):
        key = f"k{i:04d}"
        assert key in kv, f"Missing key {key}"


def test_repaired_original_values(repaired_data):
    """k0001-k0020 and k0041-k0080 should have original values."""
    kv = _traverse_tree_kv(repaired_data)
    for i in list(range(1, 21)) + list(range(41, 81)):
        key = f"k{i:04d}"
        assert kv[key].startswith("original_val_"), (
            f"{key} should have original value, got: {kv[key][:30]}"
        )


def test_repaired_v2_updated_values(repaired_data):
    """k0021-k0040 must have v2_updated values (NOT stale v1_old)."""
    kv = _traverse_tree_kv(repaired_data)
    for i in range(21, 41):
        key = f"k{i:04d}"
        assert kv[key].startswith("v2_updated_"), (
            f"{key} should have v2_updated value, got: {kv[key][:30]}"
        )


def test_repaired_no_v1_old_in_tree(repaired_data):
    """No key in the repaired tree should have stale v1_old values."""
    kv = _traverse_tree_kv(repaired_data)
    for k, v in kv.items():
        assert not v.startswith("v1_old_"), (
            f"{k} has stale v1_old value in repaired tree: {v[:30]}"
        )


def test_repaired_no_double_allocation(repaired_data):
    """No page should be both reachable from tree and in free list."""
    reachable = _get_reachable(repaired_data)
    freed = _get_freed(repaired_data)
    overlap = reachable & freed
    assert len(overlap) == 0, f"Double-allocated pages: {overlap}"


def test_repaired_free_list_entries(repaired_data):
    """Repaired free list should contain exactly pages {3, 4, 9}."""
    freed = _get_freed(repaired_data)
    assert freed == {3, 4, 9}, f"Expected freed={{3,4,9}}, got {freed}"


def test_repaired_key_boundary_consistency(repaired_data):
    """All key boundaries in the root must match child subtree first keys."""
    root_page = _get_page(repaired_data, 12)
    nkeys = _get_nkeys(root_page)
    for i in range(nkeys):
        parent_key = _get_key(root_page, i)
        child_ptr = _get_ptr(root_page, i)
        child_page = _get_page(repaired_data, child_ptr)
        child_first_key = _get_key(child_page, 0)
        assert parent_key == child_first_key, (
            f"key[{i}]='{parent_key}' != child page {child_ptr} first key '{child_first_key}'"
        )


# ── Go verifier ──────────────────────────────────────────────────


def test_go_verifier_passes_on_repaired(repaired_data):
    """Reference Go verifier must output CONSISTENT for repaired database."""
    ref_binary = "/tmp/btverify_ref"
    if not os.path.exists(ref_binary):
        pytest.skip("Reference Go verifier not compiled")
    result = subprocess.run(
        [ref_binary, "verify", "/app/database_repaired.db"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Go verifier failed (rc={result.returncode}):\n{result.stdout}\n{result.stderr}"
    )
    assert "CONSISTENT" in result.stdout


def test_go_verifier_detects_corrupted(repaired_data):
    """Reference Go verifier must detect violations in the original database."""
    ref_binary = "/tmp/btverify_ref"
    if not os.path.exists(ref_binary):
        pytest.skip("Reference Go verifier not compiled")
    result = subprocess.run(
        [ref_binary, "verify", "/app/database.db"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0, "Go verifier should fail on corrupted database"
    assert "violation" in result.stdout.lower() or "MISMATCH" in result.stdout or "ALLOCATION" in result.stdout
