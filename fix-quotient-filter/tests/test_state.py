"""

Tests for the Counting Quotient Filter C shared library at /app/libcqf.so.
Loaded via ctypes; exercises every public API function.
"""

import ctypes
import ctypes.util
import math
import os
import tempfile

import pytest

LIB_PATH = "/app/libcqf.so"


@pytest.fixture(scope="session")
def lib():
    """Load libcqf.so and configure all function signatures."""
    assert os.path.exists(LIB_PATH), (
        f"Shared library not found at {LIB_PATH}. "
        "Did you create /app/cqf.c and run 'make' in /app/?"
    )
    cqf = ctypes.CDLL(LIB_PATH)

    # -- cqf_create
    cqf.cqf_create.restype = ctypes.c_void_p
    cqf.cqf_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint32]

    # -- cqf_destroy
    cqf.cqf_destroy.restype = None
    cqf.cqf_destroy.argtypes = [ctypes.c_void_p]

    # -- cqf_insert / cqf_insert_raw
    cqf.cqf_insert.restype = ctypes.c_int
    cqf.cqf_insert.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]

    cqf.cqf_insert_raw.restype = ctypes.c_int
    cqf.cqf_insert_raw.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int
    ]

    # -- cqf_query / cqf_query_raw
    cqf.cqf_query.restype = ctypes.c_int
    cqf.cqf_query.argtypes = [ctypes.c_void_p, ctypes.c_char_p]

    cqf.cqf_query_raw.restype = ctypes.c_int
    cqf.cqf_query_raw.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]

    # -- cqf_delete
    cqf.cqf_delete.restype = ctypes.c_int
    cqf.cqf_delete.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]

    # -- cqf_merge
    cqf.cqf_merge.restype = ctypes.c_void_p
    cqf.cqf_merge.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    # -- cqf_resize
    cqf.cqf_resize.restype = ctypes.c_int
    cqf.cqf_resize.argtypes = [ctypes.c_void_p]

    # -- cqf_serialize / cqf_deserialize
    cqf.cqf_serialize.restype = ctypes.c_int
    cqf.cqf_serialize.argtypes = [ctypes.c_void_p, ctypes.c_char_p]

    cqf.cqf_deserialize.restype = ctypes.c_void_p
    cqf.cqf_deserialize.argtypes = [ctypes.c_char_p]

    # -- cqf_inner_product
    cqf.cqf_inner_product.restype = ctypes.c_int64
    cqf.cqf_inner_product.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    # -- cqf_cosine_similarity
    cqf.cqf_cosine_similarity.restype = ctypes.c_double
    cqf.cqf_cosine_similarity.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    # -- accessors
    cqf.cqf_get_q_bits.restype = ctypes.c_int
    cqf.cqf_get_q_bits.argtypes = [ctypes.c_void_p]

    cqf.cqf_get_r_bits.restype = ctypes.c_int
    cqf.cqf_get_r_bits.argtypes = [ctypes.c_void_p]

    cqf.cqf_count_distinct.restype = ctypes.c_int
    cqf.cqf_count_distinct.argtypes = [ctypes.c_void_p]

    # -- cqf_get_entries
    cqf.cqf_get_entries.restype = ctypes.c_int
    cqf.cqf_get_entries.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_int,
    ]

    return cqf


def _get_entries(lib, qf):
    """Helper: return {(q, r): count} dict from a CQF handle."""
    n = lib.cqf_count_distinct(qf)
    if n <= 0:
        return {}
    qs = (ctypes.c_int * n)()
    rs = (ctypes.c_int * n)()
    cs = (ctypes.c_int * n)()
    actual = lib.cqf_get_entries(qf, qs, rs, cs, n)
    return {(qs[i], rs[i]): cs[i] for i in range(actual)}


# ====================================================================
# 1.  Library loading and lifecycle
# ====================================================================

def test_library_loads(lib):
    """The shared library loads and exports cqf_create."""
    assert lib.cqf_create is not None


def test_create_destroy(lib):
    """Create and immediately destroy — no crash, no leak."""
    qf = lib.cqf_create(10, 8, 42)
    assert qf is not None
    assert lib.cqf_get_q_bits(qf) == 10
    assert lib.cqf_get_r_bits(qf) == 8
    lib.cqf_destroy(qf)


# ====================================================================
# 2.  Basic raw insert / query
# ====================================================================

def test_single_insert_query_raw(lib):
    """Insert one element via raw API, verify it is found."""
    qf = lib.cqf_create(14, 8, 42)
    assert lib.cqf_insert_raw(qf, 100, 50, 1) == 0
    assert lib.cqf_query_raw(qf, 100, 50) == 1
    assert lib.cqf_query_raw(qf, 100, 51) == 0
    assert lib.cqf_query_raw(qf, 101, 50) == 0
    lib.cqf_destroy(qf)


def test_count_accumulation_raw(lib):
    """Inserting the same (q,r) multiple times sums the counts."""
    qf = lib.cqf_create(14, 8, 42)
    for _ in range(10):
        lib.cqf_insert_raw(qf, 200, 30, 1)
    assert lib.cqf_query_raw(qf, 200, 30) == 10
    lib.cqf_destroy(qf)


# ====================================================================
# 3.  Sorted runs — same quotient, multiple remainders
# ====================================================================

def test_sorted_run_insertion(lib):
    """Three remainders with the same quotient form a sorted run."""
    qf = lib.cqf_create(10, 8, 42)
    lib.cqf_insert_raw(qf, 7, 50, 1)
    lib.cqf_insert_raw(qf, 7, 20, 1)
    lib.cqf_insert_raw(qf, 7, 80, 1)

    entries = _get_entries(lib, qf)
    for r in (20, 50, 80):
        assert entries.get((7, r)) == 1, f"r={r} missing: {entries}"
    lib.cqf_destroy(qf)


def test_increment_existing_in_run(lib):
    """Inserting the same (q,r) into an existing run increments, not duplicates."""
    qf = lib.cqf_create(10, 8, 42)
    lib.cqf_insert_raw(qf, 7, 50, 1)
    lib.cqf_insert_raw(qf, 7, 20, 1)
    lib.cqf_insert_raw(qf, 7, 50, 3)

    assert lib.cqf_query_raw(qf, 7, 50) == 4
    assert lib.cqf_query_raw(qf, 7, 20) == 1
    lib.cqf_destroy(qf)


# ====================================================================
# 4.  Cluster navigation — adjacent quotients
# ====================================================================

def test_cluster_navigation(lib):
    """Elements at adjacent quotients form a cluster; all retrievable."""
    qf = lib.cqf_create(10, 8, 42)
    lib.cqf_insert_raw(qf, 10, 5, 2)
    lib.cqf_insert_raw(qf, 11, 7, 3)
    lib.cqf_insert_raw(qf, 12, 3, 1)

    assert lib.cqf_query_raw(qf, 10, 5) == 2
    assert lib.cqf_query_raw(qf, 11, 7) == 3
    assert lib.cqf_query_raw(qf, 12, 3) == 1
    lib.cqf_destroy(qf)


def test_cluster_with_multi_remainder_runs(lib):
    """Each quotient in a cluster has several remainders."""
    qf = lib.cqf_create(10, 8, 42)

    for r in (30, 10, 50):
        lib.cqf_insert_raw(qf, 20, r, 1)
    for r in (25, 5):
        lib.cqf_insert_raw(qf, 21, r, 1)

    entries = _get_entries(lib, qf)
    for r in (10, 30, 50):
        assert entries.get((20, r)) == 1, f"q=20 r={r} missing"
    for r in (5, 25):
        assert entries.get((21, r)) == 1, f"q=21 r={r} missing"
    lib.cqf_destroy(qf)


# ====================================================================
# 5.  Delete
# ====================================================================

def test_delete_decrement(lib):
    """Deleting reduces count without removing the element."""
    qf = lib.cqf_create(14, 8, 42)
    lib.cqf_insert(qf, b"hello", 5)
    lib.cqf_delete(qf, b"hello", 2)
    assert lib.cqf_query(qf, b"hello") == 3
    lib.cqf_destroy(qf)


def test_delete_to_zero(lib):
    """Deleting all occurrences makes the element return count 0."""
    qf = lib.cqf_create(14, 8, 42)
    lib.cqf_insert(qf, b"hello", 3)
    lib.cqf_delete(qf, b"hello", 3)
    assert lib.cqf_query(qf, b"hello") == 0
    lib.cqf_destroy(qf)


# ====================================================================
# 6.  Merge
# ====================================================================

def test_merge_sums_counts(lib):
    """Merging two filters sums counts for shared elements."""
    a = lib.cqf_create(14, 8, 42)
    b = lib.cqf_create(14, 8, 42)

    lib.cqf_insert(a, b"shared", 3)
    lib.cqf_insert(a, b"only_a", 2)
    lib.cqf_insert(b, b"shared", 5)
    lib.cqf_insert(b, b"only_b", 4)

    merged = lib.cqf_merge(a, b)
    assert merged is not None
    assert lib.cqf_query(merged, b"shared") == 8
    assert lib.cqf_query(merged, b"only_a") == 2
    assert lib.cqf_query(merged, b"only_b") == 4

    lib.cqf_destroy(merged)
    lib.cqf_destroy(a)
    lib.cqf_destroy(b)


def test_merge_disjoint(lib):
    """Merging disjoint filters preserves all elements."""
    a = lib.cqf_create(14, 8, 42)
    b = lib.cqf_create(14, 8, 42)

    for i in range(10):
        lib.cqf_insert(a, f"a_{i}".encode(), i + 1)
    for i in range(10):
        lib.cqf_insert(b, f"b_{i}".encode(), i + 1)

    merged = lib.cqf_merge(a, b)
    for i in range(10):
        assert lib.cqf_query(merged, f"a_{i}".encode()) == i + 1
        assert lib.cqf_query(merged, f"b_{i}".encode()) == i + 1

    lib.cqf_destroy(merged)
    lib.cqf_destroy(a)
    lib.cqf_destroy(b)


# ====================================================================
# 7.  Resize
# ====================================================================

def test_resize_preserves_all(lib):
    """After resize every element is still queryable with correct count."""
    qf = lib.cqf_create(16, 8, 42)
    items = {}
    for i in range(20):
        count = (i % 5) + 1
        key = f"item_{i}".encode()
        lib.cqf_insert(qf, key, count)
        items[key] = count

    # Pre-resize sanity
    for k, v in items.items():
        got = lib.cqf_query(qf, k)
        assert got == v, f"Pre-resize: {k} expected {v}, got {got}"

    assert lib.cqf_resize(qf) == 0
    assert lib.cqf_get_q_bits(qf) == 17
    assert lib.cqf_get_r_bits(qf) == 7

    for k, v in items.items():
        got = lib.cqf_query(qf, k)
        assert got == v, f"Post-resize: {k} expected {v}, got {got}"

    lib.cqf_destroy(qf)


# ====================================================================
# 8.  Inner product / cosine similarity
# ====================================================================

def test_inner_product(lib):
    """Inner product = sum of pairwise count products."""
    a = lib.cqf_create(14, 8, 42)
    b = lib.cqf_create(14, 8, 42)

    lib.cqf_insert(a, b"x", 3)
    lib.cqf_insert(a, b"y", 2)
    lib.cqf_insert(a, b"z", 1)  # only in a

    lib.cqf_insert(b, b"x", 4)
    lib.cqf_insert(b, b"y", 5)
    lib.cqf_insert(b, b"w", 6)  # only in b

    # Expected: 3*4 + 2*5 = 22
    ip = lib.cqf_inner_product(a, b)
    assert ip == 22, f"Inner product expected 22, got {ip}"

    lib.cqf_destroy(a)
    lib.cqf_destroy(b)


def test_cosine_identical(lib):
    """Cosine similarity of a filter with itself is 1.0."""
    qf = lib.cqf_create(14, 8, 42)
    lib.cqf_insert(qf, b"a", 3)
    lib.cqf_insert(qf, b"b", 4)
    sim = lib.cqf_cosine_similarity(qf, qf)
    assert abs(sim - 1.0) < 1e-9, f"Expected 1.0, got {sim}"
    lib.cqf_destroy(qf)


def test_cosine_orthogonal(lib):
    """Filters with no shared elements have cosine similarity 0."""
    a = lib.cqf_create(14, 8, 42)
    b = lib.cqf_create(14, 8, 42)
    lib.cqf_insert(a, b"only_a", 5)
    lib.cqf_insert(b, b"only_b", 5)
    sim = lib.cqf_cosine_similarity(a, b)
    assert abs(sim) < 1e-9, f"Expected 0.0, got {sim}"
    lib.cqf_destroy(a)
    lib.cqf_destroy(b)


# ====================================================================
# 9.  Serialization round-trip
# ====================================================================

def test_serialize_deserialize(lib):
    """Serialize a CQF, deserialize it, verify all data matches."""
    qf = lib.cqf_create(12, 8, 99)
    items = {}
    for i in range(15):
        count = (i % 4) + 1
        key = f"ser_{i}".encode()
        lib.cqf_insert(qf, key, count)
        items[key] = count

    with tempfile.NamedTemporaryFile(suffix=".cqf", delete=False) as f:
        path = f.name

    try:
        assert lib.cqf_serialize(qf, path.encode()) == 0
        qf2 = lib.cqf_deserialize(path.encode())
        assert qf2 is not None

        assert lib.cqf_get_q_bits(qf2) == 12
        assert lib.cqf_get_r_bits(qf2) == 8

        for k, v in items.items():
            got = lib.cqf_query(qf2, k)
            assert got == v, f"Deserialized: {k} expected {v}, got {got}"

        lib.cqf_destroy(qf2)
    finally:
        os.unlink(path)

    lib.cqf_destroy(qf)


# ====================================================================
# 10.  String-based API (hash integration)
# ====================================================================

def test_string_insert_query(lib):
    """String-based insert/query roundtrip."""
    qf = lib.cqf_create(14, 8, 42)
    lib.cqf_insert(qf, b"alpha", 1)
    lib.cqf_insert(qf, b"beta", 7)
    lib.cqf_insert(qf, b"alpha", 2)

    assert lib.cqf_query(qf, b"alpha") == 3
    assert lib.cqf_query(qf, b"beta") == 7
    assert lib.cqf_query(qf, b"gamma") == 0
    lib.cqf_destroy(qf)


# ====================================================================
# 11.  Stress test
# ====================================================================

def test_stress_insert_query(lib):
    """Insert 200 elements and verify all queryable."""
    qf = lib.cqf_create(12, 8, 42)
    items = {}
    for i in range(200):
        c = (i % 5) + 1
        key = f"stress_{i}".encode()
        lib.cqf_insert(qf, key, c)
        items[key] = c

    for k, v in items.items():
        got = lib.cqf_query(qf, k)
        assert got == v, f"{k}: expected {v}, got {got}"
    lib.cqf_destroy(qf)


# ====================================================================
# 12.  Entry enumeration
# ====================================================================

def test_get_entries(lib):
    """cqf_get_entries returns all live entries."""
    qf = lib.cqf_create(10, 8, 42)
    lib.cqf_insert_raw(qf, 5, 10, 2)
    lib.cqf_insert_raw(qf, 5, 30, 3)
    lib.cqf_insert_raw(qf, 8, 15, 1)

    assert lib.cqf_count_distinct(qf) == 3
    entries = _get_entries(lib, qf)
    assert entries[(5, 10)] == 2
    assert entries[(5, 30)] == 3
    assert entries[(8, 15)] == 1
    lib.cqf_destroy(qf)
