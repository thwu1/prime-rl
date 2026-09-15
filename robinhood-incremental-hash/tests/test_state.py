"""

Comprehensive tests for the hash table implementation.
Compiles /app/hashmap.c as a shared library and exercises the API via ctypes.
"""

import ctypes
import os
import random
import subprocess

import pytest

# ---------------------------------------------------------------------------
# ctypes setup
# ---------------------------------------------------------------------------

class HmStats(ctypes.Structure):
    _fields_ = [
        ("size",             ctypes.c_size_t),
        ("capacity",         ctypes.c_size_t),
        ("max_displacement", ctypes.c_size_t),
        ("avg_displacement", ctypes.c_double),
        ("memory_bytes",     ctypes.c_size_t),
        ("resize_remaining", ctypes.c_size_t),
    ]


ITER_FN = ctypes.CFUNCTYPE(
    ctypes.c_int,        # return
    ctypes.c_void_p,     # key
    ctypes.c_size_t,     # key_len
    ctypes.c_void_p,     # value
    ctypes.c_size_t,     # val_len
    ctypes.c_void_p,     # user_data
)


def _setup(lib):
    lib.hm_create.restype  = ctypes.c_void_p
    lib.hm_create.argtypes = [ctypes.c_size_t]

    lib.hm_destroy.restype  = None
    lib.hm_destroy.argtypes = [ctypes.c_void_p]

    lib.hm_insert.restype  = ctypes.c_int
    lib.hm_insert.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t,
        ctypes.c_char_p, ctypes.c_size_t,
    ]

    lib.hm_lookup.restype  = ctypes.c_int
    lib.hm_lookup.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_size_t),
    ]

    lib.hm_delete.restype  = ctypes.c_int
    lib.hm_delete.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]

    lib.hm_stats.restype  = None
    lib.hm_stats.argtypes = [ctypes.c_void_p, ctypes.POINTER(HmStats)]

    lib.hm_iterate.restype  = ctypes.c_size_t
    lib.hm_iterate.argtypes = [ctypes.c_void_p, ITER_FN, ctypes.c_void_p]


@pytest.fixture(scope="session")
def lib():
    src = "/app/hashmap.c"
    hdr = "/app/hashmap.h"
    out = "/tmp/libhashmap.so"
    assert os.path.isfile(src), f"{src} not found — implement the hash table first"
    assert os.path.isfile(hdr), f"{hdr} not found"
    result = subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2", "-std=c11", "-o", out, src, "-I/app"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Compilation failed:\n{result.stderr}"
    dl = ctypes.CDLL(out)
    _setup(dl)
    return dl


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert(lib, hm, key: bytes, val: bytes):
    return lib.hm_insert(hm, key, len(key), val, len(val))


def _lookup(lib, hm, key: bytes):
    vp = ctypes.c_void_p()
    vl = ctypes.c_size_t()
    ret = lib.hm_lookup(hm, key, len(key), ctypes.byref(vp), ctypes.byref(vl))
    if ret != 0:
        return None
    if vl.value > 0:
        return ctypes.string_at(vp.value, vl.value)
    return b""


def _delete(lib, hm, key: bytes):
    return lib.hm_delete(hm, key, len(key))


def _stats(lib, hm):
    s = HmStats()
    lib.hm_stats(hm, ctypes.byref(s))
    return s


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBasicCRUD:
    def test_create_destroy(self, lib):
        hm = lib.hm_create(16)
        assert hm is not None and hm != 0
        lib.hm_destroy(hm)

    def test_insert_lookup(self, lib):
        hm = lib.hm_create(16)
        assert _insert(lib, hm, b"foo", b"bar") == 0
        assert _lookup(lib, hm, b"foo") == b"bar"
        lib.hm_destroy(hm)

    def test_insert_update(self, lib):
        hm = lib.hm_create(16)
        assert _insert(lib, hm, b"k", b"v1") == 0
        assert _insert(lib, hm, b"k", b"v2") == 0
        assert _lookup(lib, hm, b"k") == b"v2"
        s = _stats(lib, hm)
        assert s.size == 1
        lib.hm_destroy(hm)

    def test_delete(self, lib):
        hm = lib.hm_create(16)
        _insert(lib, hm, b"a", b"1")
        assert _delete(lib, hm, b"a") == 0
        assert _lookup(lib, hm, b"a") is None
        assert _delete(lib, hm, b"a") == -1
        lib.hm_destroy(hm)

    def test_delete_nonexistent(self, lib):
        hm = lib.hm_create(16)
        assert _delete(lib, hm, b"nope") == -1
        lib.hm_destroy(hm)

    def test_empty_lookup(self, lib):
        hm = lib.hm_create(16)
        assert _lookup(lib, hm, b"x") is None
        lib.hm_destroy(hm)


class TestVariableLength:
    def test_variable_key_lengths(self, lib):
        hm = lib.hm_create(64)
        for length in [1, 2, 7, 15, 16, 31, 64, 128, 200]:
            k = bytes([length & 0xFF]) * length
            v = b"val"
            assert _insert(lib, hm, k, v) == 0
        for length in [1, 2, 7, 15, 16, 31, 64, 128, 200]:
            k = bytes([length & 0xFF]) * length
            assert _lookup(lib, hm, k) == b"val"
        lib.hm_destroy(hm)

    def test_zero_length_value(self, lib):
        hm = lib.hm_create(16)
        assert _insert(lib, hm, b"empty_val", b"") == 0
        result = _lookup(lib, hm, b"empty_val")
        assert result == b""
        s = _stats(lib, hm)
        assert s.size == 1
        lib.hm_destroy(hm)

    def test_large_values(self, lib):
        hm = lib.hm_create(16)
        big = b"X" * 4096
        assert _insert(lib, hm, b"big", big) == 0
        assert _lookup(lib, hm, b"big") == big
        lib.hm_destroy(hm)


class TestIteration:
    def test_iterate_all(self, lib):
        hm = lib.hm_create(16)
        expected = {}
        for i in range(30):
            k = f"k{i}".encode()
            v = f"v{i}".encode()
            _insert(lib, hm, k, v)
            expected[k] = v

        collected = []

        @ITER_FN
        def cb(key, klen, val, vlen, ud):
            k = ctypes.string_at(key, klen)
            v = ctypes.string_at(val, vlen) if vlen > 0 else b""
            collected.append((k, v))
            return 0

        count = lib.hm_iterate(hm, cb, None)
        assert count == 30
        assert len(collected) == 30
        for k, v in collected:
            assert expected[k] == v, f"mismatch for {k}"
        lib.hm_destroy(hm)

    def test_iterate_early_stop(self, lib):
        hm = lib.hm_create(16)
        for i in range(20):
            _insert(lib, hm, f"k{i}".encode(), b"v")

        visited = [0]

        @ITER_FN
        def cb(key, klen, val, vlen, ud):
            visited[0] += 1
            return 1 if visited[0] >= 5 else 0  # stop after 5

        count = lib.hm_iterate(hm, cb, None)
        assert count == 5
        assert visited[0] == 5
        lib.hm_destroy(hm)


class TestTableGrowth:
    def test_resize_is_gradual(self, lib):
        """After a resize triggers, resize_remaining must decrease by
        at most HM_RESIZE_BATCH (8) per mutating operation."""
        hm = lib.hm_create(16)  # small cap -> quick resize

        # Fill to ~70 % of 16 -> ~11 entries should trigger resize
        for i in range(11):
            _insert(lib, hm, f"base{i}".encode(), b"x")

        s = _stats(lib, hm)
        # Might not have resized yet; push one more if needed
        if s.resize_remaining == 0:
            _insert(lib, hm, b"trigger", b"x")
            s = _stats(lib, hm)

        # Resize should now be active
        assert s.resize_remaining > 0, "expected active resize"

        prev = s.resize_remaining
        for i in range(200):
            _insert(lib, hm, f"extra{i}".encode(), b"y")
            s = _stats(lib, hm)
            if s.resize_remaining == 0:
                break
            delta = prev - s.resize_remaining
            assert 0 <= delta <= 8, (
                f"migration moved {delta} entries in one step (max 8)")
            prev = s.resize_remaining

        # All original entries still accessible
        for i in range(11):
            assert _lookup(lib, hm, f"base{i}".encode()) == b"x"
        lib.hm_destroy(hm)

    def test_multiple_resize_cycles(self, lib):
        """Grow the table through at least three resize cycles."""
        hm = lib.hm_create(16)
        resizes_seen = 0
        was_resizing = False

        for i in range(2000):
            _insert(lib, hm, f"k{i:05d}".encode(), f"v{i}".encode())
            s = _stats(lib, hm)
            if s.resize_remaining > 0 and not was_resizing:
                resizes_seen += 1
                was_resizing = True
            elif s.resize_remaining == 0:
                was_resizing = False

        assert resizes_seen >= 3, f"only saw {resizes_seen} resize cycles"

        # Every entry still accessible
        for i in range(2000):
            val = _lookup(lib, hm, f"k{i:05d}".encode())
            assert val == f"v{i}".encode(), f"lost entry k{i:05d}"
        lib.hm_destroy(hm)


class TestDuringResize:
    def test_operations_during_resize(self, lib):
        """Insert, lookup, update, and delete must all work while the
        table is actively migrating entries between internal structures."""
        hm = lib.hm_create(16)

        n = 12
        for i in range(n):
            _insert(lib, hm, f"op{i}".encode(), f"v{i}".encode())

        s = _stats(lib, hm)
        if s.resize_remaining == 0:
            _insert(lib, hm, b"extra_trigger", b"x")
            n += 1
            s = _stats(lib, hm)

        assert s.resize_remaining > 0, "resize must be active for this test"

        # Lookup all original entries (some may be in old storage,
        # some already migrated to new storage)
        for i in range(12):
            val = _lookup(lib, hm, f"op{i}".encode())
            assert val is not None, f"op{i} not found during resize"

        # Update a subset (entry may live in either internal structure)
        for i in range(0, 12, 3):
            assert _insert(lib, hm, f"op{i}".encode(), b"updated") == 0

        for i in range(0, 12, 3):
            assert _lookup(lib, hm, f"op{i}".encode()) == b"updated"

        # Delete a different subset
        deleted = 0
        for i in range(1, 12, 3):
            if _delete(lib, hm, f"op{i}".encode()) == 0:
                deleted += 1

        for i in range(1, 12, 3):
            assert _lookup(lib, hm, f"op{i}".encode()) is None

        # Survivors still present
        for i in range(2, 12, 3):
            val = _lookup(lib, hm, f"op{i}".encode())
            assert val is not None, f"op{i} lost after sibling ops during resize"

        s = _stats(lib, hm)
        assert s.size == n - deleted
        lib.hm_destroy(hm)

    def test_iterate_during_resize(self, lib):
        """Iteration while migration is in progress must visit every
        entry exactly once with no duplicates and no omissions."""
        hm = lib.hm_create(16)

        entries = {}
        for i in range(12):
            k = f"it{i}".encode()
            v = f"val{i}".encode()
            _insert(lib, hm, k, v)
            entries[k] = v

        s = _stats(lib, hm)
        if s.resize_remaining == 0:
            _insert(lib, hm, b"it_extra", b"ev")
            entries[b"it_extra"] = b"ev"
            s = _stats(lib, hm)

        assert s.resize_remaining > 0, "resize must be active for this test"

        collected = []

        @ITER_FN
        def cb(key, klen, val, vlen, ud):
            k = ctypes.string_at(key, klen)
            v = ctypes.string_at(val, vlen) if vlen > 0 else b""
            collected.append((k, v))
            return 0

        count = lib.hm_iterate(hm, cb, None)
        assert count == len(entries), (
            f"visited {count} but expected {len(entries)}")
        assert len(collected) == len(entries)

        seen = {}
        for k, v in collected:
            assert k not in seen, f"duplicate key {k} during iteration"
            seen[k] = v

        for k, v in entries.items():
            assert k in seen, f"{k} not visited during iteration"
            assert seen[k] == v

        lib.hm_destroy(hm)


class TestProbeEfficiency:
    def test_bounded_displacement(self, lib):
        """Max displacement should stay well bounded (O(log n))."""
        hm = lib.hm_create(16)
        n = 5000
        for i in range(n):
            _insert(lib, hm, f"entry{i:06d}".encode(), b"val")
        s = _stats(lib, hm)
        assert s.size == n
        # With a good collision-resolution strategy and decent hash,
        # max displacement << sqrt(n)
        assert s.max_displacement < 64, (
            f"max_displacement {s.max_displacement} is too high for {n} entries")
        lib.hm_destroy(hm)

    def test_deletion_preserves_reachability(self, lib):
        """After deleting entries from a cluster, remaining entries
        must still be reachable."""
        hm = lib.hm_create(16)
        keys = [f"cl{i}".encode() for i in range(12)]
        for k in keys:
            _insert(lib, hm, k, b"present")

        # Delete every other key
        for i in range(0, 12, 2):
            assert _delete(lib, hm, keys[i]) == 0

        # Remaining keys still present
        for i in range(1, 12, 2):
            assert _lookup(lib, hm, keys[i]) == b"present", (
                f"{keys[i]} lost after deleting neighbours")

        # Deleted keys really gone
        for i in range(0, 12, 2):
            assert _lookup(lib, hm, keys[i]) is None
        lib.hm_destroy(hm)


class TestDeleteReinsert:
    def test_delete_and_reinsert(self, lib):
        hm = lib.hm_create(32)
        n = 100
        for i in range(n):
            _insert(lib, hm, f"dr{i}".encode(), f"orig{i}".encode())

        # Delete all
        for i in range(n):
            assert _delete(lib, hm, f"dr{i}".encode()) == 0

        s = _stats(lib, hm)
        assert s.size == 0

        # Reinsert with new values
        for i in range(n):
            _insert(lib, hm, f"dr{i}".encode(), f"new{i}".encode())

        for i in range(n):
            assert _lookup(lib, hm, f"dr{i}".encode()) == f"new{i}".encode()
        s = _stats(lib, hm)
        assert s.size == n
        lib.hm_destroy(hm)


class TestStats:
    def test_stats_accuracy(self, lib):
        hm = lib.hm_create(32)
        _insert(lib, hm, b"a", b"1")
        _insert(lib, hm, b"b", b"22")
        _insert(lib, hm, b"c", b"333")

        s = _stats(lib, hm)
        assert s.size == 3
        assert s.capacity >= 32
        assert s.memory_bytes > 0
        assert s.resize_remaining == 0
        assert s.avg_displacement >= 0.0

        _delete(lib, hm, b"b")
        s = _stats(lib, hm)
        assert s.size == 2
        lib.hm_destroy(hm)

    def test_stats_during_resize(self, lib):
        """Stats must be accurate mid-resize."""
        hm = lib.hm_create(16)
        for i in range(12):
            _insert(lib, hm, f"sr{i}".encode(), b"v")
        s = _stats(lib, hm)
        # After 12 inserts into cap=16, resize may have started
        assert s.size == 12
        # Regardless of resize state, size must be consistent
        lib.hm_destroy(hm)


class TestManyEntries:
    def test_five_thousand(self, lib):
        """Insert 5000 entries with various key patterns, verify all."""
        hm = lib.hm_create(16)
        entries = {}
        for i in range(5000):
            k = f"item-{i:06d}".encode()
            v = f"payload-{i * 7}".encode()
            _insert(lib, hm, k, v)
            entries[k] = v

        s = _stats(lib, hm)
        assert s.size == 5000

        for k, v in entries.items():
            got = _lookup(lib, hm, k)
            assert got == v, f"mismatch for {k}: expected {v!r}, got {got!r}"
        lib.hm_destroy(hm)


class TestStress:
    def test_random_ops(self, lib):
        """Deterministic random mix of insert / lookup / delete."""
        rng = random.Random(12345)
        hm = lib.hm_create(16)
        mirror = {}  # ground-truth

        for _ in range(10000):
            op = rng.choices(["insert", "lookup", "delete"],
                             weights=[5, 3, 2])[0]
            key = f"s{rng.randint(0, 499)}".encode()

            if op == "insert":
                val = f"v{rng.randint(0, 99999)}".encode()
                assert _insert(lib, hm, key, val) == 0
                mirror[key] = val

            elif op == "lookup":
                got = _lookup(lib, hm, key)
                if key in mirror:
                    assert got == mirror[key], (
                        f"lookup {key}: expected {mirror[key]!r}, got {got!r}")
                else:
                    assert got is None

            else:  # delete
                ret = _delete(lib, hm, key)
                if key in mirror:
                    assert ret == 0
                    del mirror[key]
                else:
                    assert ret == -1

        # Final consistency check
        s = _stats(lib, hm)
        assert s.size == len(mirror)

        for k, v in mirror.items():
            assert _lookup(lib, hm, k) == v

        lib.hm_destroy(hm)
