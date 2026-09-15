"""Tests for the B+tree database recovery and repair tool.

"""
import json
import os
import struct
import subprocess
import zlib

import pytest

RECOVER = "/app/recover"
PGVERIFY_SRC = "/app/tools/pgverify.c"
PGVERIFY = "/app/tools/pgverify"
DB_DIR = "/app/databases"
REPAIR_DIR = "/tmp/repaired"
PAGE_SIZE = 4096
MAGIC = b"BYODB_TBENCH_V1\x00"
BNODE_INTERNAL = 1
BNODE_LEAF = 2


@pytest.fixture(scope="session", autouse=True)
def _setup():
    """Compile pgverify and create repair output directory."""
    os.makedirs(REPAIR_DIR, exist_ok=True)
    result = subprocess.run(
        ["gcc", "-O2", "-o", PGVERIFY, PGVERIFY_SRC],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"gcc failed: {result.stderr}"


@pytest.fixture(autouse=True)
def _check_tool():
    assert os.path.isfile(RECOVER), f"{RECOVER} not found"
    assert os.access(RECOVER, os.X_OK), f"{RECOVER} not executable"


# ---- helpers ----

_CACHE = {}


def _get(db_name):
    """Run recover once per db, cache the result."""
    if db_name not in _CACHE:
        inp = os.path.join(DB_DIR, db_name)
        out = os.path.join(REPAIR_DIR, db_name)
        r = subprocess.run(
            [RECOVER, inp, out],
            capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, (
            f"recover exit {r.returncode}: {r.stderr[:500]}"
        )
        try:
            report = json.loads(r.stdout)
        except json.JSONDecodeError as exc:
            pytest.fail(f"Bad JSON: {exc}\n{r.stdout[:500]}")
        _CACHE[db_name] = (report, out)
    return _CACHE[db_name]


def _pgv(path):
    """Run compiled pgverify. Returns (exit_code, stdout)."""
    r = subprocess.run(
        [PGVERIFY, path], capture_output=True, text=True, timeout=30,
    )
    return r.returncode, r.stdout.strip()


def _read_kvs(path):
    """Read KV pairs from a structurally valid repaired database."""
    with open(path, "rb") as f:
        data = f.read()
    num_pages = struct.unpack_from("<Q", data, 24)[0]
    root = struct.unpack_from("<Q", data, 16)[0]

    def pg(n):
        return data[n * PAGE_SIZE : (n + 1) * PAGE_SIZE]

    kvs = []
    vis = set()

    def walk(pn):
        if pn in vis or pn < 1 or pn >= num_pages:
            return
        vis.add(pn)
        p = pg(pn)
        nt = struct.unpack_from("<H", p, 0)[0]
        nk = struct.unpack_from("<H", p, 2)[0]
        if nt == BNODE_LEAF:
            ob = 4 + nk * 8
            kva = 4 + nk * 10
            prev = 0
            for i in range(nk):
                cum = struct.unpack_from("<H", p, ob + i * 2)[0]
                s = kva + prev
                kl = struct.unpack_from("<H", p, s)[0]
                vl = struct.unpack_from("<H", p, s + 2)[0]
                kvs.append((
                    p[s + 4 : s + 4 + kl].decode(),
                    p[s + 4 + kl : s + 4 + kl + vl].decode(),
                ))
                prev = cum
        elif nt == BNODE_INTERNAL:
            for i in range(nk):
                walk(struct.unpack_from("<Q", p, 4 + i * 8)[0])

    walk(root)
    kvs.sort()
    return kvs


# ==================================================================
# Report tests — corruption detection
# ==================================================================


class TestValidReport:
    def test_no_errors(self):
        r, _ = _get("valid.db")
        assert len(r["errors"]) == 0

    def test_meta(self):
        r, _ = _get("valid.db")
        assert r["meta"]["checksum_valid"] is True
        assert r["meta"]["magic_valid"] is True

    def test_kvs(self):
        r, _ = _get("valid.db")
        assert len(r["recovered_kvs"]) == 100

    def test_stats(self):
        r, _ = _get("valid.db")
        assert r["stats"]["orphaned_pages"] == 0


class TestOrphanedReport:
    def test_error_type(self):
        r, _ = _get("orphaned.db")
        assert "orphaned_pages" in [e["type"] for e in r["errors"]]

    def test_stats(self):
        r, _ = _get("orphaned.db")
        assert r["stats"]["total_pages"] == 10
        assert r["stats"]["reachable_pages"] == 7
        assert r["stats"]["orphaned_pages"] == 3

    def test_kvs(self):
        r, _ = _get("orphaned.db")
        assert len(r["recovered_kvs"]) == 100


class TestBadOrderReport:
    def test_sort_violation(self):
        r, _ = _get("bad_order.db")
        assert "sort_violation" in [e["type"] for e in r["errors"]]

    def test_violation_page(self):
        r, _ = _get("bad_order.db")
        sv = [e for e in r["errors"] if e["type"] == "sort_violation"]
        assert any(e["page"] == 2 for e in sv)

    def test_kvs(self):
        r, _ = _get("bad_order.db")
        assert len(r["recovered_kvs"]) == 100


class TestDanglingReport:
    def test_dangling(self):
        r, _ = _get("dangling.db")
        assert "dangling_pointer" in [e["type"] for e in r["errors"]]

    def test_partial_recovery(self):
        r, _ = _get("dangling.db")
        assert len(r["recovered_kvs"]) == 80

    def test_boundary_keys(self):
        r, _ = _get("dangling.db")
        keys = [kv[0] for kv in r["recovered_kvs"]]
        assert "key_00079" in keys
        assert "key_00080" not in keys

    def test_orphaned_stats(self):
        r, _ = _get("dangling.db")
        assert r["stats"]["orphaned_pages"] == 1


class TestBadChecksumReport:
    def test_bad_checksum(self):
        r, _ = _get("bad_checksum.db")
        assert "bad_checksum" in [e["type"] for e in r["errors"]]

    def test_meta_invalid(self):
        r, _ = _get("bad_checksum.db")
        assert r["meta"]["checksum_valid"] is False

    def test_kvs(self):
        r, _ = _get("bad_checksum.db")
        assert len(r["recovered_kvs"]) == 100


class TestCorruptedReport:
    def test_corrupted(self):
        r, _ = _get("corrupted_node.db")
        assert "corrupted_node" in [e["type"] for e in r["errors"]]

    def test_corrupted_page(self):
        r, _ = _get("corrupted_node.db")
        cn = [e for e in r["errors"] if e["type"] == "corrupted_node"]
        assert any(e["page"] == 3 for e in cn)

    def test_partial_recovery(self):
        r, _ = _get("corrupted_node.db")
        assert len(r["recovered_kvs"]) == 80

    def test_boundary_keys(self):
        r, _ = _get("corrupted_node.db")
        keys = [kv[0] for kv in r["recovered_kvs"]]
        assert "key_00039" in keys
        assert "key_00040" not in keys
        assert "key_00060" in keys

    def test_no_orphaned(self):
        r, _ = _get("corrupted_node.db")
        assert r["stats"]["orphaned_pages"] == 0


# ==================================================================
# Repair tests — structural validity via pgverify + content
# ==================================================================


class TestValidRepair:
    def test_pgverify(self):
        _, out = _get("valid.db")
        code, msg = _pgv(out)
        assert code == 0, f"pgverify failed: {msg}"

    def test_kvs(self):
        _, out = _get("valid.db")
        kvs = _read_kvs(out)
        assert len(kvs) == 100
        assert kvs[0] == ("key_00000", "value_00000")
        assert kvs[99] == ("key_00099", "value_00099")


class TestOrphanedRepair:
    def test_pgverify(self):
        _, out = _get("orphaned.db")
        code, msg = _pgv(out)
        assert code == 0, f"pgverify failed: {msg}"

    def test_kvs(self):
        _, out = _get("orphaned.db")
        kvs = _read_kvs(out)
        assert len(kvs) == 100


class TestBadOrderRepair:
    def test_pgverify(self):
        _, out = _get("bad_order.db")
        code, msg = _pgv(out)
        assert code == 0, f"pgverify failed: {msg}"

    def test_kvs(self):
        _, out = _get("bad_order.db")
        kvs = _read_kvs(out)
        assert len(kvs) == 100


class TestDanglingRepair:
    def test_pgverify(self):
        _, out = _get("dangling.db")
        code, msg = _pgv(out)
        assert code == 0, f"pgverify failed: {msg}"

    def test_kvs(self):
        _, out = _get("dangling.db")
        kvs = _read_kvs(out)
        assert len(kvs) == 80
        keys = [k for k, _ in kvs]
        assert "key_00079" in keys
        assert "key_00080" not in keys


class TestCorruptedRepair:
    def test_pgverify(self):
        _, out = _get("corrupted_node.db")
        code, msg = _pgv(out)
        assert code == 0, f"pgverify failed: {msg}"

    def test_kvs(self):
        _, out = _get("corrupted_node.db")
        kvs = _read_kvs(out)
        assert len(kvs) == 80
        keys = [k for k, _ in kvs]
        assert "key_00039" in keys
        assert "key_00040" not in keys
        assert "key_00060" in keys


class TestBadChecksumRepair:
    def test_pgverify(self):
        _, out = _get("bad_checksum.db")
        code, msg = _pgv(out)
        assert code == 0, f"pgverify failed: {msg}"

    def test_kvs(self):
        _, out = _get("bad_checksum.db")
        kvs = _read_kvs(out)
        assert len(kvs) == 100

    def test_meta_checksum(self):
        _, out = _get("bad_checksum.db")
        with open(out, "rb") as f:
            data = f.read(PAGE_SIZE)
        stored = struct.unpack_from("<I", data, 32)[0]
        computed = zlib.crc32(data[0:32]) & 0xFFFFFFFF
        assert stored == computed, "repaired meta checksum invalid"
