
"""
Tests for block-packed hash table with incremental dynamic expansion.
Verifies correctness via ctypes against the compiled libblockht.so.
"""

import ctypes
import os
import subprocess
import random
import pytest


# ---------------------------------------------------------------------------
# ctypes setup
# ---------------------------------------------------------------------------

class BHTStats(ctypes.Structure):
    _fields_ = [
        ("total_slots",           ctypes.c_uint32),
        ("active_slots",          ctypes.c_uint32),
        ("total_records",         ctypes.c_uint32),
        ("total_blocks",          ctypes.c_uint32),
        ("max_probe_distance",    ctypes.c_uint32),
        ("total_data_bytes",      ctypes.c_uint64),
        ("total_allocated_bytes", ctypes.c_uint64),
    ]


@pytest.fixture(scope="session", autouse=True)
def build_library():
    """Compile the shared library once per test session."""
    subprocess.run(["make", "-C", "/app", "clean"],
                   capture_output=True)
    r = subprocess.run(["make", "-C", "/app"],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"Compilation failed:\n{r.stderr}\n{r.stdout}"


def _load():
    """Load libblockht.so and set up function signatures."""
    lib = ctypes.CDLL("/app/libblockht.so")

    lib.bht_create.restype  = ctypes.c_void_p
    lib.bht_create.argtypes = [ctypes.c_uint32, ctypes.c_uint32]

    lib.bht_destroy.restype  = None
    lib.bht_destroy.argtypes = [ctypes.c_void_p]

    lib.bht_insert.restype  = ctypes.c_int
    lib.bht_insert.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                ctypes.c_uint32, ctypes.c_char_p,
                                ctypes.c_uint32]

    lib.bht_lookup.restype  = ctypes.c_void_p
    lib.bht_lookup.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                ctypes.c_uint32,
                                ctypes.POINTER(ctypes.c_uint32)]

    lib.bht_delete.restype  = ctypes.c_int
    lib.bht_delete.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                ctypes.c_uint32]

    lib.bht_stats.restype  = None
    lib.bht_stats.argtypes = [ctypes.c_void_p,
                               ctypes.POINTER(BHTStats)]
    return lib


def _lookup(lib, ht, key):
    """Helper: returns (value_bytes, value_len) or (None, 0)."""
    vlen = ctypes.c_uint32()
    p = lib.bht_lookup(ht, key, len(key), ctypes.byref(vlen))
    if p is None:
        return None, 0
    return ctypes.string_at(p, vlen.value), vlen.value


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_compile():
    """Library file exists and exports the required symbols."""
    assert os.path.exists("/app/libblockht.so"), "libblockht.so not found"
    lib = _load()
    for name in ("bht_create", "bht_destroy", "bht_insert",
                 "bht_lookup", "bht_delete", "bht_stats"):
        assert getattr(lib, name, None) is not None, f"missing symbol: {name}"


def test_basic_insert_lookup_delete():
    """Insert, lookup, update, and delete a single key."""
    lib = _load()
    ht = lib.bht_create(8, 6)
    assert ht is not None

    # insert
    assert lib.bht_insert(ht, b"hello", 5, b"world", 5) == 0

    # lookup
    val, vlen = _lookup(lib, ht, b"hello")
    assert val == b"world" and vlen == 5

    # update (same length -- in-place path)
    assert lib.bht_insert(ht, b"hello", 5, b"earth", 5) == 0
    val, _ = _lookup(lib, ht, b"hello")
    assert val == b"earth"

    # update (different length -- remove+re-insert path)
    assert lib.bht_insert(ht, b"hello", 5, b"universe!", 9) == 0
    val, vlen = _lookup(lib, ht, b"hello")
    assert val == b"universe!" and vlen == 9

    # delete
    assert lib.bht_delete(ht, b"hello", 5) == 0
    val, _ = _lookup(lib, ht, b"hello")
    assert val is None

    lib.bht_destroy(ht)


def test_nonexistent_key():
    """Lookup and delete of absent keys must return the right signals."""
    lib = _load()
    ht = lib.bht_create(8, 6)

    val, _ = _lookup(lib, ht, b"nope")
    assert val is None
    assert lib.bht_delete(ht, b"nope", 4) == -1

    lib.bht_destroy(ht)


def test_variable_length_records():
    """Records with widely varying key/value sizes."""
    lib = _load()
    ht = lib.bht_create(16, 10)

    cases = [
        (b"a",          b"x"),
        (b"ab",         b"xy" * 50),           # 100-byte value
        (b"key" * 20,   b"v"),                  # 60-byte key
        (b"k" * 100,    b"v" * 500),
        (b"k" * 200,    b"v" * 1800),           # nearly fills a block
    ]

    for key, val in cases:
        assert lib.bht_insert(ht, key, len(key), val, len(val)) == 0

    for key, val in cases:
        got, got_len = _lookup(lib, ht, key)
        assert got is not None, f"missing key len={len(key)}"
        assert got_len == len(val)
        assert got == val

    lib.bht_destroy(ht)


def test_mass_insert_50k():
    """Insert 50 000 records and verify every one is retrievable."""
    lib = _load()
    ht = lib.bht_create(8, 6)

    N = 50_000
    records = {}
    for i in range(N):
        key = f"k{i:08d}".encode()
        val = f"v{i:08d}{'x' * (i % 47)}".encode()
        records[key] = val
        r = lib.bht_insert(ht, key, len(key), val, len(val))
        assert r == 0, f"insert failed at i={i}"

    for key, expected in records.items():
        got, got_len = _lookup(lib, ht, key)
        assert got is not None, f"lost {key}"
        assert got_len == len(expected), f"bad len for {key}"
        assert got == expected, f"bad value for {key}"

    stats = BHTStats()
    lib.bht_stats(ht, ctypes.byref(stats))
    assert stats.total_records == N

    lib.bht_destroy(ht)


def test_mass_insert_delete_cycle():
    """Insert 30 000 records, delete even-indexed, verify odd-indexed remain."""
    lib = _load()
    ht = lib.bht_create(8, 6)

    N = 30_000
    pairs = []
    for i in range(N):
        key = f"d{i:08d}".encode()
        val = f"w{i:08d}".encode()
        pairs.append((key, val))
        lib.bht_insert(ht, key, len(key), val, len(val))

    for i in range(0, N, 2):
        assert lib.bht_delete(ht, pairs[i][0], len(pairs[i][0])) == 0

    for i in range(1, N, 2):
        got, _ = _lookup(lib, ht, pairs[i][0])
        assert got == pairs[i][1], f"record {i} corrupted after deletions"

    for i in range(0, N, 2):
        got, _ = _lookup(lib, ht, pairs[i][0])
        assert got is None, f"record {i} not deleted"

    stats = BHTStats()
    lib.bht_stats(ht, ctypes.byref(stats))
    assert stats.total_records == N // 2

    lib.bht_destroy(ht)


def test_expansion_preserves_records():
    """Small initial size forces many expansions; verify no data loss."""
    lib = _load()
    ht = lib.bht_create(2, 3)      # tiny: 2 slots, threshold 3

    random.seed(42)
    N = 10_000
    records = {}
    for i in range(N):
        key = f"e{i:06d}".encode()
        val = f"q{i:06d}".encode()
        records[key] = val
        lib.bht_insert(ht, key, len(key), val, len(val))

        if i > 0 and i % 2000 == 0:
            sample = random.sample(sorted(records.keys()), min(200, len(records)))
            for k in sample:
                got, _ = _lookup(lib, ht, k)
                assert got is not None, f"lost {k} after {i} inserts"
                assert got == records[k]

    for key, val in records.items():
        got, _ = _lookup(lib, ht, key)
        assert got is not None, f"lost {key} in final check"
        assert got == val

    lib.bht_destroy(ht)


def test_expansion_stats_timing():
    """Verify the expansion schedule matches the specified countdown."""
    lib = _load()
    ht = lib.bht_create(4, 4)

    stats = BHTStats()
    lib.bht_stats(ht, ctypes.byref(stats))
    assert stats.active_slots == 4
    assert stats.total_slots  == 4

    # Insert 4*4 = 16 records -> first expansion (double to 8, active=5)
    for i in range(16):
        key = f"t{i:04d}".encode()
        lib.bht_insert(ht, key, len(key), b"v", 1)

    lib.bht_stats(ht, ctypes.byref(stats))
    assert stats.total_records == 16
    assert stats.total_slots   == 8, f"expected 8, got {stats.total_slots}"
    assert stats.active_slots  == 5, f"expected 5, got {stats.active_slots}"

    # 4 more inserts -> second expansion (active=6)
    for i in range(16, 20):
        key = f"t{i:04d}".encode()
        lib.bht_insert(ht, key, len(key), b"v", 1)

    lib.bht_stats(ht, ctypes.byref(stats))
    assert stats.total_records == 20
    assert stats.active_slots  == 6, f"expected 6, got {stats.active_slots}"
    assert stats.total_slots   == 8

    # 4 more -> active=7
    for i in range(20, 24):
        key = f"t{i:04d}".encode()
        lib.bht_insert(ht, key, len(key), b"v", 1)

    lib.bht_stats(ht, ctypes.byref(stats))
    assert stats.active_slots == 7
    assert stats.total_slots  == 8

    lib.bht_destroy(ht)


def test_expansion_invariants():
    """total_slots is always a power of two; active_slots <= total_slots."""
    lib = _load()
    ht = lib.bht_create(4, 5)

    stats = BHTStats()
    for i in range(5000):
        key = f"i{i:06d}".encode()
        lib.bht_insert(ht, key, len(key), b"val", 3)

        if i % 500 == 499:
            lib.bht_stats(ht, ctypes.byref(stats))
            ts = stats.total_slots
            assert ts & (ts - 1) == 0, f"total_slots={ts} not power of 2"
            assert stats.active_slots <= ts
            assert stats.total_records == i + 1

    lib.bht_destroy(ht)


def test_large_records_overflow():
    """Records close to block capacity force overflow to a second block."""
    lib = _load()
    ht = lib.bht_create(8, 2)

    big_val = b"X" * 3000
    assert lib.bht_insert(ht, b"big1", 4, big_val, len(big_val)) == 0

    big_val2 = b"Y" * 3000
    assert lib.bht_insert(ht, b"big2", 4, big_val2, len(big_val2)) == 0

    got1, l1 = _lookup(lib, ht, b"big1")
    assert got1 is not None and l1 == 3000 and got1 == big_val

    got2, l2 = _lookup(lib, ht, b"big2")
    assert got2 is not None and l2 == 3000 and got2 == big_val2

    lib.bht_destroy(ht)


def test_stats_accuracy():
    """bht_stats reports consistent, plausible values."""
    lib = _load()
    ht = lib.bht_create(8, 6)

    total_data = 0
    N = 5000
    for i in range(N):
        key = f"m{i:06d}".encode()
        val = f"n{i:06d}".encode()
        total_data += len(key) + len(val)
        lib.bht_insert(ht, key, len(key), val, len(val))

    stats = BHTStats()
    lib.bht_stats(ht, ctypes.byref(stats))

    assert stats.total_records == N
    assert stats.total_data_bytes == total_data
    assert stats.total_blocks > 0
    assert stats.total_allocated_bytes == stats.total_blocks * 4096
    assert stats.max_probe_distance >= 1       # at least one block per chain

    efficiency = stats.total_data_bytes / stats.total_allocated_bytes
    assert 0.01 < efficiency <= 1.0, f"implausible efficiency {efficiency}"

    ts = stats.total_slots
    assert ts & (ts - 1) == 0
    assert stats.active_slots <= ts

    lib.bht_destroy(ht)


def test_update_does_not_trigger_expansion():
    """Re-inserting the same key must NOT decrement the expansion countdown."""
    lib = _load()
    ht = lib.bht_create(4, 4)   # countdown starts at 16

    # Insert 15 unique keys (countdown -> 1)
    for i in range(15):
        key = f"u{i:04d}".encode()
        lib.bht_insert(ht, key, len(key), b"a", 1)

    # Update 5 of those keys with different-length values
    # (should NOT trigger expansion)
    for i in range(5):
        key = f"u{i:04d}".encode()
        new_val = f"updated_{i:04d}".encode()
        lib.bht_insert(ht, key, len(key), new_val, len(new_val))

    stats = BHTStats()
    lib.bht_stats(ht, ctypes.byref(stats))
    assert stats.active_slots == 4, (
        f"updates triggered expansion: active_slots={stats.active_slots}"
    )
    assert stats.total_slots == 4

    # One more NEW key -> countdown reaches 0, expansion fires
    lib.bht_insert(ht, b"trigger!", 8, b"go", 2)

    lib.bht_stats(ht, ctypes.byref(stats))
    assert stats.active_slots == 5, (
        f"expected expansion to active_slots=5, got {stats.active_slots}"
    )

    lib.bht_destroy(ht)
