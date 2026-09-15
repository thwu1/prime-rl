
import ctypes
import math
import os
import subprocess
import pytest

LIB_PATH = "/tmp/libhashtable.so"

VALGRIND_TEST_C = r'''
#include "hashtable.h"
#include <stdio.h>
#include <string.h>

int main(void) {
    /* empty create/destroy */
    block_hashtable_t *ht = bht_create(4096, 4);
    if (!ht) return 1;
    bht_destroy(ht);

    /* insert many to trigger resize, delete half, lookup rest, destroy */
    ht = bht_create(4096, 4);
    for (int i = 0; i < 2000; i++) {
        char key[32], val[64];
        snprintf(key, sizeof(key), "key_%d", i);
        snprintf(val, sizeof(val), "value_%d_padding", i);
        bht_insert(ht, key, strlen(key), val, strlen(val));
    }
    for (int i = 0; i < 1000; i++) {
        char key[32];
        snprintf(key, sizeof(key), "key_%d", i);
        bht_delete(ht, key, strlen(key));
    }
    for (int i = 1000; i < 2000; i++) {
        char key[32], buf[128];
        size_t vlen;
        snprintf(key, sizeof(key), "key_%d", i);
        bht_lookup(ht, key, strlen(key), buf, sizeof(buf), &vlen);
    }
    bht_destroy(ht);

    /* oversized record in small block */
    ht = bht_create(256, 2);
    char bigval[500];
    memset(bigval, 'X', sizeof(bigval));
    bht_insert(ht, "big", 3, bigval, sizeof(bigval));
    bht_destroy(ht);

    return 0;
}
'''


@pytest.fixture(scope="session")
def lib():
    result = subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2", "-o", LIB_PATH, "/app/hashtable.c"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Compilation failed:\n{result.stderr}"
    lib = ctypes.CDLL(LIB_PATH)

    lib.bht_create.restype = ctypes.c_void_p
    lib.bht_create.argtypes = [ctypes.c_size_t, ctypes.c_size_t]

    lib.bht_destroy.restype = None
    lib.bht_destroy.argtypes = [ctypes.c_void_p]

    lib.bht_insert.restype = ctypes.c_int
    lib.bht_insert.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_char_p,
        ctypes.c_size_t,
    ]

    lib.bht_lookup.restype = ctypes.c_int
    lib.bht_lookup.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]

    lib.bht_delete.restype = ctypes.c_int
    lib.bht_delete.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]

    lib.bht_count.restype = ctypes.c_size_t
    lib.bht_count.argtypes = [ctypes.c_void_p]

    lib.bht_block_count.restype = ctypes.c_size_t
    lib.bht_block_count.argtypes = [ctypes.c_void_p]

    lib.bht_block_size.restype = ctypes.c_size_t
    lib.bht_block_size.argtypes = [ctypes.c_void_p]

    lib.bht_max_psl.restype = ctypes.c_size_t
    lib.bht_max_psl.argtypes = [ctypes.c_void_p]

    lib.bht_uses_incremental_resize.restype = ctypes.c_int
    lib.bht_uses_incremental_resize.argtypes = [ctypes.c_void_p]

    return lib


def _insert(lib, ht, key: bytes, value: bytes):
    return lib.bht_insert(ht, key, len(key), value, len(value))


def _lookup(lib, ht, key: bytes, buf_size=8192):
    buf = ctypes.create_string_buffer(buf_size)
    vlen = ctypes.c_size_t(0)
    ret = lib.bht_lookup(ht, key, len(key), buf, buf_size, ctypes.byref(vlen))
    if ret == 0:
        return buf.raw[: vlen.value]
    return None


def _delete(lib, ht, key: bytes):
    return lib.bht_delete(ht, key, len(key))


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------
class TestBasicCRUD:
    def test_insert_and_lookup(self, lib):
        ht = lib.bht_create(4096, 4)
        assert ht is not None
        assert _insert(lib, ht, b"hello", b"world") == 0
        assert _lookup(lib, ht, b"hello") == b"world"
        lib.bht_destroy(ht)

    def test_multiple_inserts(self, lib):
        ht = lib.bht_create(4096, 4)
        for i in range(100):
            key = f"key_{i:04d}".encode()
            val = f"value_{i:04d}".encode()
            assert _insert(lib, ht, key, val) == 0
        assert lib.bht_count(ht) == 100
        for i in range(100):
            key = f"key_{i:04d}".encode()
            val = f"value_{i:04d}".encode()
            assert _lookup(lib, ht, key) == val
        lib.bht_destroy(ht)

    def test_not_found(self, lib):
        ht = lib.bht_create(4096, 4)
        assert _lookup(lib, ht, b"nonexistent") is None
        lib.bht_destroy(ht)

    def test_delete(self, lib):
        ht = lib.bht_create(4096, 4)
        _insert(lib, ht, b"key1", b"val1")
        _insert(lib, ht, b"key2", b"val2")
        assert _delete(lib, ht, b"key1") == 0
        assert _lookup(lib, ht, b"key1") is None
        assert _lookup(lib, ht, b"key2") == b"val2"
        assert lib.bht_count(ht) == 1
        lib.bht_destroy(ht)

    def test_update(self, lib):
        ht = lib.bht_create(4096, 4)
        _insert(lib, ht, b"key", b"val1")
        _insert(lib, ht, b"key", b"val2_updated")
        assert _lookup(lib, ht, b"key") == b"val2_updated"
        assert lib.bht_count(ht) == 1
        lib.bht_destroy(ht)

    def test_delete_nonexistent(self, lib):
        ht = lib.bht_create(4096, 4)
        assert _delete(lib, ht, b"nope") == -1
        lib.bht_destroy(ht)

    def test_insert_delete_reinsert(self, lib):
        ht = lib.bht_create(4096, 4)
        _insert(lib, ht, b"abc", b"111")
        assert _delete(lib, ht, b"abc") == 0
        assert _lookup(lib, ht, b"abc") is None
        _insert(lib, ht, b"abc", b"222")
        assert _lookup(lib, ht, b"abc") == b"222"
        assert lib.bht_count(ht) == 1
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# Variable-length keys and values
# ---------------------------------------------------------------------------
class TestVariableLength:
    def test_single_byte_key(self, lib):
        ht = lib.bht_create(4096, 4)
        _insert(lib, ht, b"a", b"x")
        assert _lookup(lib, ht, b"a") == b"x"
        lib.bht_destroy(ht)

    def test_medium_key_value(self, lib):
        ht = lib.bht_create(4096, 4)
        key = b"k" * 200
        val = b"v" * 500
        _insert(lib, ht, key, val)
        assert _lookup(lib, ht, key) == val
        lib.bht_destroy(ht)

    def test_large_key_value(self, lib):
        ht = lib.bht_create(4096, 8)
        key = b"K" * 2000
        val = b"V" * 3500
        _insert(lib, ht, key, val)
        assert _lookup(lib, ht, key) == val
        lib.bht_destroy(ht)

    def test_mixed_sizes(self, lib):
        ht = lib.bht_create(4096, 8)
        pairs = []
        for i in range(50):
            prefix = f"mx_{i:04d}_".encode()
            extra_k = (i * 37 + 7) % 400
            extra_v = (i * 53 + 13) % 800
            key = prefix + b"K" * extra_k
            val = prefix + b"V" * extra_v
            pairs.append((key, val))
            _insert(lib, ht, key, val)
        for key, val in pairs:
            assert _lookup(lib, ht, key) == val
        lib.bht_destroy(ht)

    def test_empty_value(self, lib):
        ht = lib.bht_create(4096, 4)
        _insert(lib, ht, b"emptyval", b"")
        result = _lookup(lib, ht, b"emptyval")
        assert result == b""
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# Probe-distance bound
# ---------------------------------------------------------------------------
class TestProbeDistance:
    def test_psl_bounded(self, lib):
        """After inserting N elements, max PSL should be O(log N)."""
        ht = lib.bht_create(4096, 16)
        n = 10000
        for i in range(n):
            key = f"probe_{i:06d}".encode()
            val = f"pval_{i:06d}".encode()
            _insert(lib, ht, key, val)

        max_psl = lib.bht_max_psl(ht)
        bound = int(5 * math.log2(n)) + 10  # ~77
        assert max_psl < bound, f"max PSL {max_psl} exceeds bound {bound}"
        assert max_psl > 0, "max PSL is 0 — probing not working?"
        lib.bht_destroy(ht)

    def test_psl_bounded_after_deletes(self, lib):
        """PSL must remain bounded after heavy deletion."""
        ht = lib.bht_create(4096, 16)
        n = 5000
        for i in range(n):
            key = f"pdel_{i:06d}".encode()
            val = f"pval_{i:06d}".encode()
            _insert(lib, ht, key, val)
        for i in range(0, n, 2):
            _delete(lib, ht, f"pdel_{i:06d}".encode())

        max_psl = lib.bht_max_psl(ht)
        bound = int(5 * math.log2(n)) + 10
        assert max_psl < bound, f"max PSL {max_psl} after deletes exceeds {bound}"
        # Remaining entries still accessible
        for i in range(1, n, 2):
            assert _lookup(lib, ht, f"pdel_{i:06d}".encode()) is not None
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# Block storage introspection
# ---------------------------------------------------------------------------
class TestBlockStorage:
    def test_block_size_returned(self, lib):
        ht = lib.bht_create(8192, 2)
        assert lib.bht_block_size(ht) == 8192
        lib.bht_destroy(ht)

    def test_blocks_grow(self, lib):
        ht = lib.bht_create(4096, 4)
        initial_blocks = lib.bht_block_count(ht)
        # Insert enough data to exceed initial blocks
        for i in range(500):
            key = f"blk_{i:04d}".encode()
            val = b"X" * 200
            _insert(lib, ht, key, val)
        assert lib.bht_block_count(ht) > initial_blocks, (
            "Block count did not grow after heavy insertion"
        )
        lib.bht_destroy(ht)

    def test_oversized_record(self, lib):
        """A record larger than block_size must still be stored correctly."""
        ht = lib.bht_create(256, 2)
        key = b"big_key"
        val = b"B" * 500  # exceeds block_size
        assert _insert(lib, ht, key, val) == 0
        assert _lookup(lib, ht, key) == val
        # Normal records still work afterward
        for i in range(20):
            k = f"n_{i}".encode()
            v = f"v_{i}".encode()
            _insert(lib, ht, k, v)
        assert _lookup(lib, ht, key) == val
        for i in range(20):
            assert _lookup(lib, ht, f"n_{i}".encode()) == f"v_{i}".encode()
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# Incremental resize
# ---------------------------------------------------------------------------
class TestIncrementalResize:
    def test_resize_is_incremental(self, lib):
        """Resize flag must persist across 2+ consecutive operations,
        proving migration is spread over multiple calls (not all-at-once)."""
        ht = lib.bht_create(4096, 4)
        flags = []
        for i in range(3000):
            key = f"resize_{i:05d}".encode()
            val = f"rval_{i:05d}".encode()
            _insert(lib, ht, key, val)
            flags.append(lib.bht_uses_incremental_resize(ht))

        assert any(f == 1 for f in flags), (
            "bht_uses_incremental_resize never returned 1 during 3000 insertions"
        )

        # Check that the flag was 1 for at least 2 consecutive inserts
        max_consecutive = 0
        run = 0
        for f in flags:
            if f == 1:
                run += 1
                if run > max_consecutive:
                    max_consecutive = run
            else:
                run = 0

        assert max_consecutive >= 2, (
            f"Resize flag was 1 for at most {max_consecutive} consecutive insert(s). "
            "Migration does not appear to be incremental."
        )
        lib.bht_destroy(ht)

    def test_correctness_during_resize(self, lib):
        """All entries must remain accessible throughout incremental resize."""
        ht = lib.bht_create(4096, 4)
        entries = {}
        for i in range(3000):
            key = f"dur_{i:05d}".encode()
            val = f"dval_{i:05d}".encode()
            _insert(lib, ht, key, val)
            entries[key] = val
            # Periodically check a sample
            if i % 500 == 499:
                for k, v in list(entries.items())[:100]:
                    assert _lookup(lib, ht, k) == v, (
                        f"Entry {k} missing at i={i}"
                    )

        for k, v in entries.items():
            assert _lookup(lib, ht, k) == v, f"Entry {k} missing at end"
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# Large dataset
# ---------------------------------------------------------------------------
class TestLargeDataset:
    def test_50k_entries(self, lib):
        ht = lib.bht_create(4096, 16)
        n = 50000
        for i in range(n):
            key = f"lg_{i:06d}".encode()
            val = f"lv_{i:06d}".encode()
            _insert(lib, ht, key, val)

        assert lib.bht_count(ht) == n

        # Verify every entry
        for i in range(n):
            key = f"lg_{i:06d}".encode()
            val = f"lv_{i:06d}".encode()
            assert _lookup(lib, ht, key) == val, f"Missing key lg_{i:06d}"
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# Delete and reinsert cycles
# ---------------------------------------------------------------------------
class TestDeleteAndReinsert:
    def test_delete_half_reinsert(self, lib):
        ht = lib.bht_create(4096, 8)
        for i in range(500):
            _insert(lib, ht, f"dr_{i:04d}".encode(), f"v1_{i:04d}".encode())

        # Delete even-numbered entries
        for i in range(0, 500, 2):
            _delete(lib, ht, f"dr_{i:04d}".encode())

        assert lib.bht_count(ht) == 250

        # Reinsert with different values
        for i in range(0, 500, 2):
            _insert(lib, ht, f"dr_{i:04d}".encode(), f"v2_{i:04d}".encode())

        assert lib.bht_count(ht) == 500

        # Verify all
        for i in range(500):
            key = f"dr_{i:04d}".encode()
            if i % 2 == 0:
                assert _lookup(lib, ht, key) == f"v2_{i:04d}".encode()
            else:
                assert _lookup(lib, ht, key) == f"v1_{i:04d}".encode()
        lib.bht_destroy(ht)

    def test_repeated_insert_delete_cycle(self, lib):
        """Insert and delete the same keys repeatedly."""
        ht = lib.bht_create(4096, 4)
        for cycle in range(5):
            for i in range(200):
                k = f"cyc_{i:04d}".encode()
                v = f"c{cycle}_{i:04d}".encode()
                _insert(lib, ht, k, v)
            assert lib.bht_count(ht) == 200
            for i in range(200):
                k = f"cyc_{i:04d}".encode()
                v = f"c{cycle}_{i:04d}".encode()
                assert _lookup(lib, ht, k) == v
            for i in range(200):
                _delete(lib, ht, f"cyc_{i:04d}".encode())
            assert lib.bht_count(ht) == 0
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# Update during resize
# ---------------------------------------------------------------------------
class TestUpdateDuringResize:
    def test_update_keys_during_active_resize(self, lib):
        """Update values while incremental resize is in progress."""
        ht = lib.bht_create(4096, 4)
        n = 500
        for i in range(n):
            _insert(lib, ht, f"ur_{i:04d}".encode(), f"old_{i:04d}".encode())

        # Now update all entries — some will be during resize
        for i in range(n):
            _insert(lib, ht, f"ur_{i:04d}".encode(), f"new_{i:04d}".encode())

        assert lib.bht_count(ht) == n
        for i in range(n):
            assert _lookup(lib, ht, f"ur_{i:04d}".encode()) == f"new_{i:04d}".encode()
        lib.bht_destroy(ht)


# ---------------------------------------------------------------------------
# ELF symbol visibility
# ---------------------------------------------------------------------------
class TestSymbolVisibility:
    """The agent-compiled shared library must only export bht_* symbols."""

    def test_agent_library_exists(self):
        assert os.path.exists("/app/libhashtable.so"), (
            "/app/libhashtable.so not found — the compiled library must be placed there"
        )

    def test_no_internal_symbols_exported(self):
        so_path = "/app/libhashtable.so"
        if not os.path.exists(so_path):
            pytest.skip("Agent-compiled library not found at /app/libhashtable.so")
        result = subprocess.run(
            ["nm", "-D", "--defined-only", so_path],
            capture_output=True, text=True,
        )
        text_symbols = []
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "T":
                text_symbols.append(parts[2])

        non_public = [s for s in text_symbols if not s.startswith("bht_")]
        assert len(non_public) == 0, (
            f"Internal symbols leaked to dynamic symbol table: {non_public}"
        )

    def test_all_public_symbols_present(self):
        so_path = "/app/libhashtable.so"
        if not os.path.exists(so_path):
            pytest.skip("Agent-compiled library not found at /app/libhashtable.so")
        result = subprocess.run(
            ["nm", "-D", "--defined-only", so_path],
            capture_output=True, text=True,
        )
        found = set()
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "T":
                found.add(parts[2])

        expected = {
            "bht_create", "bht_destroy", "bht_insert", "bht_lookup",
            "bht_delete", "bht_count", "bht_block_count", "bht_block_size",
            "bht_max_psl", "bht_uses_incremental_resize",
        }
        missing = expected - found
        assert not missing, f"Missing public symbols in dynamic table: {missing}"


# ---------------------------------------------------------------------------
# Memory safety (valgrind)
# ---------------------------------------------------------------------------
class TestMemorySafety:
    """The implementation must be free of memory leaks under valgrind."""

    def test_valgrind_no_leaks(self):
        with open("/tmp/valgrind_test.c", "w") as f:
            f.write(VALGRIND_TEST_C)

        compile_result = subprocess.run(
            ["gcc", "-O2", "-g", "-o", "/tmp/valgrind_test",
             "/tmp/valgrind_test.c", "/app/hashtable.c", "-I/app"],
            capture_output=True, text=True,
        )
        assert compile_result.returncode == 0, (
            f"Cannot compile valgrind test: {compile_result.stderr}"
        )

        result = subprocess.run(
            ["valgrind", "--leak-check=full", "--errors-for-leak-kinds=all",
             "--error-exitcode=1", "/tmp/valgrind_test"],
            capture_output=True, text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"Valgrind detected memory issues:\n{result.stderr}"
        )
