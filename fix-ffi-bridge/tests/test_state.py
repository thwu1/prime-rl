
import ctypes
import os
import subprocess
import threading
import pytest

LIB_PATH = "/app/rust-sortedset/target/release/librust_sortedset.so"

# Callback type: int (*)(const char*, double, void*)
ITER_CALLBACK = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_char_p, ctypes.c_double, ctypes.c_void_p
)


class ZRangeResult(ctypes.Structure):
    """Matches the C header: count, members, scores (in that order)."""

    _fields_ = [
        ("count", ctypes.c_size_t),
        ("members", ctypes.POINTER(ctypes.c_char_p)),
        ("scores", ctypes.POINTER(ctypes.c_double)),
    ]


@pytest.fixture(scope="session")
def lib():
    """Build the Rust crate and load the shared library."""
    result = subprocess.run(
        ["cargo", "build", "--release"],
        cwd="/app/rust-sortedset",
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"Cargo build failed:\n{result.stderr}"
    assert os.path.exists(LIB_PATH), f"Shared library not found at {LIB_PATH}"

    lib = ctypes.CDLL(LIB_PATH)

    lib.zset_new.restype = ctypes.c_void_p
    lib.zset_new.argtypes = []

    lib.zset_free.restype = None
    lib.zset_free.argtypes = [ctypes.c_void_p]

    lib.zset_clone.restype = ctypes.c_void_p
    lib.zset_clone.argtypes = [ctypes.c_void_p]

    lib.zset_add.restype = ctypes.c_int32
    lib.zset_add.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double]

    lib.zset_remove.restype = ctypes.c_int32
    lib.zset_remove.argtypes = [ctypes.c_void_p, ctypes.c_char_p]

    lib.zset_score.restype = ctypes.c_int32
    lib.zset_score.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_double),
    ]

    lib.zset_card.restype = ctypes.c_size_t
    lib.zset_card.argtypes = [ctypes.c_void_p]

    lib.zset_rank.restype = ctypes.c_int32
    lib.zset_rank.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_size_t),
    ]

    lib.zset_range_by_score.restype = ctypes.POINTER(ZRangeResult)
    lib.zset_range_by_score.argtypes = [
        ctypes.c_void_p,
        ctypes.c_double,
        ctypes.c_double,
    ]

    lib.zset_range_by_rank.restype = ctypes.POINTER(ZRangeResult)
    lib.zset_range_by_rank.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
    ]

    lib.zset_range_free.restype = None
    lib.zset_range_free.argtypes = [ctypes.POINTER(ZRangeResult)]

    lib.zset_foreach.restype = ctypes.c_size_t
    lib.zset_foreach.argtypes = [ctypes.c_void_p, ITER_CALLBACK, ctypes.c_void_p]

    return lib


@pytest.fixture
def zset(lib):
    """Create a fresh sorted set for each test."""
    zs = lib.zset_new()
    assert zs is not None and zs != 0
    yield zs
    lib.zset_free(zs)


# ---------------------------------------------------------------------------
# Basic operations
# ---------------------------------------------------------------------------


class TestBasicOperations:
    def test_create_and_destroy(self, lib):
        zs = lib.zset_new()
        assert zs is not None and zs != 0
        lib.zset_free(zs)

    def test_add_new_member(self, lib, zset):
        assert lib.zset_add(zset, b"alice", 10.0) == 1

    def test_add_update_existing(self, lib, zset):
        assert lib.zset_add(zset, b"alice", 10.0) == 1
        assert lib.zset_add(zset, b"alice", 15.0) == 0

    def test_card_empty(self, lib, zset):
        assert lib.zset_card(zset) == 0

    def test_card_after_adds(self, lib, zset):
        lib.zset_add(zset, b"a", 1.0)
        lib.zset_add(zset, b"b", 2.0)
        assert lib.zset_card(zset) == 2

    def test_remove_existing(self, lib, zset):
        lib.zset_add(zset, b"alice", 10.0)
        assert lib.zset_remove(zset, b"alice") == 1
        assert lib.zset_card(zset) == 0

    def test_remove_nonexistent(self, lib, zset):
        assert lib.zset_remove(zset, b"nobody") == 0


# ---------------------------------------------------------------------------
# Score retrieval
# ---------------------------------------------------------------------------


class TestScore:
    def test_score_found(self, lib, zset):
        lib.zset_add(zset, b"alice", 42.5)
        score = ctypes.c_double(-999.0)
        found = lib.zset_score(zset, b"alice", ctypes.byref(score))
        assert found == 1
        assert score.value == 42.5, (
            f"Expected score 42.5 but got {score.value}. "
            "The FFI function likely does not write to out_score."
        )

    def test_score_after_update(self, lib, zset):
        lib.zset_add(zset, b"alice", 10.0)
        lib.zset_add(zset, b"alice", 99.0)
        score = ctypes.c_double(-1.0)
        found = lib.zset_score(zset, b"alice", ctypes.byref(score))
        assert found == 1
        assert score.value == 99.0

    def test_score_not_found(self, lib, zset):
        score = ctypes.c_double(-999.0)
        found = lib.zset_score(zset, b"nobody", ctypes.byref(score))
        assert found == 0

    def test_score_multiple_members(self, lib, zset):
        lib.zset_add(zset, b"a", 1.5)
        lib.zset_add(zset, b"b", 2.5)
        lib.zset_add(zset, b"c", 3.5)

        score = ctypes.c_double(0.0)
        for name, expected in [(b"a", 1.5), (b"b", 2.5), (b"c", 3.5)]:
            lib.zset_score(zset, name, ctypes.byref(score))
            assert score.value == expected, (
                f"Score for {name}: expected {expected}, got {score.value}"
            )


# ---------------------------------------------------------------------------
# Rank
# ---------------------------------------------------------------------------


class TestRank:
    def test_rank_ordering(self, lib, zset):
        lib.zset_add(zset, b"eve", 5.0)
        lib.zset_add(zset, b"alice", 10.0)
        lib.zset_add(zset, b"charlie", 15.0)
        lib.zset_add(zset, b"bob", 20.0)

        rank = ctypes.c_size_t(999)

        lib.zset_rank(zset, b"eve", ctypes.byref(rank))
        assert rank.value == 0

        lib.zset_rank(zset, b"alice", ctypes.byref(rank))
        assert rank.value == 1

        lib.zset_rank(zset, b"charlie", ctypes.byref(rank))
        assert rank.value == 2

        lib.zset_rank(zset, b"bob", ctypes.byref(rank))
        assert rank.value == 3

    def test_rank_not_found(self, lib, zset):
        lib.zset_add(zset, b"alice", 10.0)
        rank = ctypes.c_size_t(999)
        found = lib.zset_rank(zset, b"nobody", ctypes.byref(rank))
        assert found == 0


# ---------------------------------------------------------------------------
# Range by score
# ---------------------------------------------------------------------------


class TestRangeByScore:
    def test_range_by_score_basic(self, lib, zset):
        lib.zset_add(zset, b"eve", 5.0)
        lib.zset_add(zset, b"alice", 10.0)
        lib.zset_add(zset, b"charlie", 15.0)
        lib.zset_add(zset, b"bob", 20.0)
        lib.zset_add(zset, b"dave", 25.0)

        result = lib.zset_range_by_score(zset, 10.0, 20.0)
        assert result

        r = result.contents
        assert r.count == 3, (
            f"Expected count=3 but got count={r.count}. "
            "Possible struct field layout mismatch between Rust repr(C) and C header."
        )

        assert r.members[0] == b"alice", (
            f"Expected 'alice' but got {r.members[0]!r}. "
            "Possible dangling pointer from CString being dropped too early."
        )
        assert r.members[1] == b"charlie"
        assert r.members[2] == b"bob"

        assert r.scores[0] == 10.0
        assert r.scores[1] == 15.0
        assert r.scores[2] == 20.0

        lib.zset_range_free(result)

    def test_range_by_score_empty_result(self, lib, zset):
        lib.zset_add(zset, b"alice", 10.0)
        result = lib.zset_range_by_score(zset, 50.0, 100.0)
        assert result
        assert result.contents.count == 0
        lib.zset_range_free(result)

    def test_range_by_score_single(self, lib, zset):
        lib.zset_add(zset, b"only", 7.0)
        result = lib.zset_range_by_score(zset, 5.0, 10.0)
        assert result
        r = result.contents
        assert r.count == 1
        assert r.members[0] == b"only"
        assert r.scores[0] == 7.0
        lib.zset_range_free(result)

    def test_range_by_score_boundary_inclusive(self, lib, zset):
        lib.zset_add(zset, b"lo", 10.0)
        lib.zset_add(zset, b"hi", 20.0)
        lib.zset_add(zset, b"mid", 15.0)

        result = lib.zset_range_by_score(zset, 10.0, 20.0)
        r = result.contents
        assert r.count == 3
        lib.zset_range_free(result)

    def test_range_by_score_empty_set(self, lib, zset):
        result = lib.zset_range_by_score(zset, 0.0, 100.0)
        assert result
        assert result.contents.count == 0
        lib.zset_range_free(result)


# ---------------------------------------------------------------------------
# Range by rank
# ---------------------------------------------------------------------------


class TestRangeByRank:
    def test_range_by_rank_basic(self, lib, zset):
        lib.zset_add(zset, b"eve", 5.0)
        lib.zset_add(zset, b"alice", 10.0)
        lib.zset_add(zset, b"charlie", 15.0)
        lib.zset_add(zset, b"bob", 20.0)
        lib.zset_add(zset, b"dave", 25.0)

        result = lib.zset_range_by_rank(zset, 1, 3)
        assert result

        r = result.contents
        assert r.count == 3, (
            f"Expected 3 elements for rank range [1,3] but got {r.count}. "
            "The stop index must be inclusive."
        )

        assert r.members[0] == b"alice"
        assert r.members[1] == b"charlie"
        assert r.members[2] == b"bob"

        lib.zset_range_free(result)

    def test_range_by_rank_all(self, lib, zset):
        lib.zset_add(zset, b"a", 1.0)
        lib.zset_add(zset, b"b", 2.0)
        lib.zset_add(zset, b"c", 3.0)

        result = lib.zset_range_by_rank(zset, 0, 2)
        r = result.contents
        assert r.count == 3
        assert r.members[0] == b"a"
        assert r.members[1] == b"b"
        assert r.members[2] == b"c"
        lib.zset_range_free(result)

    def test_range_by_rank_single(self, lib, zset):
        lib.zset_add(zset, b"x", 1.0)
        lib.zset_add(zset, b"y", 2.0)
        lib.zset_add(zset, b"z", 3.0)

        result = lib.zset_range_by_rank(zset, 1, 1)
        r = result.contents
        assert r.count == 1
        assert r.members[0] == b"y"
        lib.zset_range_free(result)

    def test_range_by_rank_first_element(self, lib, zset):
        lib.zset_add(zset, b"x", 1.0)
        lib.zset_add(zset, b"y", 2.0)

        result = lib.zset_range_by_rank(zset, 0, 0)
        r = result.contents
        assert r.count == 1
        assert r.members[0] == b"x"
        lib.zset_range_free(result)

    def test_range_by_rank_last_element(self, lib, zset):
        lib.zset_add(zset, b"x", 1.0)
        lib.zset_add(zset, b"y", 2.0)
        lib.zset_add(zset, b"z", 3.0)

        result = lib.zset_range_by_rank(zset, 2, 2)
        r = result.contents
        assert r.count == 1
        assert r.members[0] == b"z"
        lib.zset_range_free(result)


# ---------------------------------------------------------------------------
# Range free — memory management
# ---------------------------------------------------------------------------


class TestRangeFree:
    def test_free_does_not_crash(self, lib, zset):
        lib.zset_add(zset, b"test", 1.0)
        for _ in range(100):
            result = lib.zset_range_by_score(zset, 0.0, 10.0)
            assert result.contents.count == 1
            lib.zset_range_free(result)

    def test_free_releases_memory(self, lib, zset):
        """Detect memory leaks by monitoring RSS over many alloc/free cycles."""
        long_name = b"x" * 500
        lib.zset_add(zset, long_name, 1.0)

        # Warm up allocator
        for _ in range(1000):
            result = lib.zset_range_by_score(zset, 0.0, 10.0)
            lib.zset_range_free(result)

        def get_rss_kb():
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1])
            return 0

        rss_before = get_rss_kb()

        for _ in range(50000):
            result = lib.zset_range_by_score(zset, 0.0, 10.0)
            lib.zset_range_free(result)

        rss_after = get_rss_kb()
        growth_kb = rss_after - rss_before

        assert growth_kb < 10000, (
            f"RSS grew by {growth_kb} KB after 50K alloc/free cycles. "
            "zset_range_free likely does not release allocated memory."
        )

    def test_free_null_is_safe(self, lib):
        lib.zset_range_free(None)


# ---------------------------------------------------------------------------
# Foreach — callback-based iteration
# ---------------------------------------------------------------------------


class TestForeach:
    def test_foreach_collects_all(self, lib, zset):
        """Foreach should visit all members in score-ascending order."""
        lib.zset_add(zset, b"charlie", 15.0)
        lib.zset_add(zset, b"alice", 10.0)
        lib.zset_add(zset, b"bob", 20.0)

        collected = []

        @ITER_CALLBACK
        def callback(member, score, _user_data):
            collected.append((member, score))
            return 0  # continue

        visited = lib.zset_foreach(zset, callback, None)
        assert visited == 3
        assert len(collected) == 3
        # Must be in score-ascending order
        assert collected[0] == (b"alice", 10.0)
        assert collected[1] == (b"charlie", 15.0)
        assert collected[2] == (b"bob", 20.0)

    def test_foreach_early_stop(self, lib, zset):
        """Callback returning non-zero should stop iteration early."""
        lib.zset_add(zset, b"a", 1.0)
        lib.zset_add(zset, b"b", 2.0)
        lib.zset_add(zset, b"c", 3.0)
        lib.zset_add(zset, b"d", 4.0)

        collected = []

        @ITER_CALLBACK
        def callback(member, score, _user_data):
            collected.append((member, score))
            # Stop after visiting 2 entries
            return 1 if len(collected) >= 2 else 0

        visited = lib.zset_foreach(zset, callback, None)
        assert visited == 2, (
            f"Expected 2 visited with early stop, got {visited}. "
            "Callback return value may not be honored."
        )
        assert len(collected) == 2

    def test_foreach_empty_set(self, lib, zset):
        @ITER_CALLBACK
        def callback(member, score, _user_data):
            return 0

        visited = lib.zset_foreach(zset, callback, None)
        assert visited == 0

    def test_foreach_user_data_passthrough(self, lib, zset):
        """The void* user_data must be passed through to the callback."""
        lib.zset_add(zset, b"x", 1.0)
        lib.zset_add(zset, b"y", 2.0)

        # Use a ctypes int as user_data to accumulate score sum
        accumulator = ctypes.c_double(0.0)

        @ITER_CALLBACK
        def callback(member, score, user_data):
            # Cast the void* back to a c_double pointer
            acc_ptr = ctypes.cast(user_data, ctypes.POINTER(ctypes.c_double))
            acc_ptr.contents.value += score
            return 0

        lib.zset_foreach(zset, callback, ctypes.cast(ctypes.byref(accumulator), ctypes.c_void_p))
        assert accumulator.value == 3.0, (
            f"Expected accumulated score 3.0, got {accumulator.value}. "
            "user_data may not be passed through correctly."
        )

    def test_foreach_single_element(self, lib, zset):
        lib.zset_add(zset, b"only", 42.0)

        collected = []

        @ITER_CALLBACK
        def callback(member, score, _user_data):
            collected.append((member, score))
            return 0

        visited = lib.zset_foreach(zset, callback, None)
        assert visited == 1
        assert collected == [(b"only", 42.0)]


# ---------------------------------------------------------------------------
# Clone — deep copy
# ---------------------------------------------------------------------------


class TestClone:
    def test_clone_has_same_data(self, lib, zset):
        lib.zset_add(zset, b"alice", 10.0)
        lib.zset_add(zset, b"bob", 20.0)

        clone = lib.zset_clone(zset)
        assert clone is not None and clone != 0

        assert lib.zset_card(clone) == 2

        score = ctypes.c_double(0.0)
        lib.zset_score(clone, b"alice", ctypes.byref(score))
        assert score.value == 10.0
        lib.zset_score(clone, b"bob", ctypes.byref(score))
        assert score.value == 20.0

        lib.zset_free(clone)

    def test_clone_is_independent(self, lib, zset):
        """Mutating the clone must not affect the original."""
        lib.zset_add(zset, b"alice", 10.0)
        lib.zset_add(zset, b"bob", 20.0)

        clone = lib.zset_clone(zset)
        assert clone is not None and clone != 0

        # Add to clone
        lib.zset_add(clone, b"charlie", 30.0)
        assert lib.zset_card(clone) == 3
        assert lib.zset_card(zset) == 2  # original unchanged

        # Remove from clone
        lib.zset_remove(clone, b"alice")
        assert lib.zset_card(clone) == 2
        assert lib.zset_card(zset) == 2  # original still has alice

        score = ctypes.c_double(0.0)
        found = lib.zset_score(zset, b"alice", ctypes.byref(score))
        assert found == 1  # original still has alice

        lib.zset_free(clone)

    def test_clone_original_mutation_does_not_affect_clone(self, lib, zset):
        """Mutating the original must not affect the clone."""
        lib.zset_add(zset, b"a", 1.0)
        lib.zset_add(zset, b"b", 2.0)

        clone = lib.zset_clone(zset)

        # Mutate original
        lib.zset_remove(zset, b"a")
        lib.zset_add(zset, b"c", 3.0)

        # Clone should be unaffected
        assert lib.zset_card(clone) == 2
        score = ctypes.c_double(0.0)
        found = lib.zset_score(clone, b"a", ctypes.byref(score))
        assert found == 1
        assert score.value == 1.0

        lib.zset_free(clone)

    def test_clone_null(self, lib):
        result = lib.zset_clone(None)
        assert result is None or result == 0


# ---------------------------------------------------------------------------
# Thread safety — concurrent access
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_adds(self, lib):
        """Multiple threads adding unique keys concurrently."""
        zs = lib.zset_new()
        assert zs is not None and zs != 0
        errors = []
        num_threads = 4
        adds_per_thread = 100

        def writer(thread_id):
            try:
                for i in range(adds_per_thread):
                    name = f"t{thread_id}_{i}".encode()
                    lib.zset_add(zs, name, float(thread_id * 1000 + i))
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(tid,))
            for tid in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        expected = num_threads * adds_per_thread
        actual = lib.zset_card(zs)
        assert actual == expected, (
            f"Expected {expected} members after concurrent adds, got {actual}. "
            "The FFI bridge is not thread-safe."
        )
        lib.zset_free(zs)

    def test_concurrent_reads_and_writes(self, lib):
        """Mix of readers and writers operating concurrently."""
        zs = lib.zset_new()
        # Pre-populate
        for i in range(50):
            lib.zset_add(zs, f"init_{i}".encode(), float(i))

        errors = []

        def writer(thread_id):
            try:
                for i in range(50):
                    name = f"w{thread_id}_{i}".encode()
                    lib.zset_add(zs, name, float(thread_id * 1000 + i))
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(50):
                    lib.zset_card(zs)
                    score = ctypes.c_double(0.0)
                    lib.zset_score(zs, b"init_0", ctypes.byref(score))
                    result = lib.zset_range_by_rank(zs, 0, 5)
                    if result:
                        lib.zset_range_free(result)
            except Exception as e:
                errors.append(e)

        threads = []
        for tid in range(2):
            threads.append(threading.Thread(target=writer, args=(tid,)))
        for _ in range(2):
            threads.append(threading.Thread(target=reader))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        # 50 initial + 2 writers * 50 = 150
        assert lib.zset_card(zs) == 150
        lib.zset_free(zs)

    def test_concurrent_foreach(self, lib):
        """Foreach should work safely under concurrent access."""
        zs = lib.zset_new()
        for i in range(20):
            lib.zset_add(zs, f"item_{i}".encode(), float(i))

        errors = []
        counts = []

        @ITER_CALLBACK
        def count_cb(member, score, _user_data):
            return 0

        def foreach_worker():
            try:
                visited = lib.zset_foreach(zs, count_cb, None)
                counts.append(visited)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=foreach_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        # All threads should see 20 items (no concurrent mutation)
        assert all(c == 20 for c in counts), f"Inconsistent foreach counts: {counts}"
        lib.zset_free(zs)


# ---------------------------------------------------------------------------
# Null pointer safety
# ---------------------------------------------------------------------------


class TestNullSafety:
    def test_add_null_store(self, lib):
        assert lib.zset_add(None, b"test", 1.0) == -1

    def test_card_null_store(self, lib):
        assert lib.zset_card(None) == 0

    def test_free_null_store(self, lib):
        lib.zset_free(None)

    def test_score_null_store(self, lib):
        score = ctypes.c_double(0.0)
        assert lib.zset_score(None, b"test", ctypes.byref(score)) == 0

    def test_range_by_score_null_store(self, lib):
        result = lib.zset_range_by_score(None, 0.0, 10.0)
        assert not result

    def test_range_by_rank_null_store(self, lib):
        result = lib.zset_range_by_rank(None, 0, 5)
        assert not result

    def test_clone_null_store(self, lib):
        result = lib.zset_clone(None)
        assert result is None or result == 0

    def test_foreach_null_store(self, lib):
        @ITER_CALLBACK
        def callback(member, score, _user_data):
            return 0

        visited = lib.zset_foreach(None, callback, None)
        assert visited == 0

    def test_remove_null_store(self, lib):
        assert lib.zset_remove(None, b"test") == -1

    def test_rank_null_store(self, lib):
        rank = ctypes.c_size_t(999)
        assert lib.zset_rank(None, b"test", ctypes.byref(rank)) == 0


# ---------------------------------------------------------------------------
# Integration: full workflow
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_workflow(self, lib, zset):
        """Exercises the complete API in a realistic sequence."""
        # Add members
        lib.zset_add(zset, b"alice", 10.0)
        lib.zset_add(zset, b"bob", 20.0)
        lib.zset_add(zset, b"charlie", 15.0)
        lib.zset_add(zset, b"dave", 25.0)
        lib.zset_add(zset, b"eve", 5.0)
        assert lib.zset_card(zset) == 5

        # Update alice
        lib.zset_add(zset, b"alice", 12.0)
        assert lib.zset_card(zset) == 5

        # Check scores
        score = ctypes.c_double(0.0)
        lib.zset_score(zset, b"alice", ctypes.byref(score))
        assert score.value == 12.0

        lib.zset_score(zset, b"bob", ctypes.byref(score))
        assert score.value == 20.0

        # Check ranks (order: eve=5, alice=12, charlie=15, bob=20, dave=25)
        rank = ctypes.c_size_t(999)
        lib.zset_rank(zset, b"eve", ctypes.byref(rank))
        assert rank.value == 0

        lib.zset_rank(zset, b"dave", ctypes.byref(rank))
        assert rank.value == 4

        # Range by score [10, 20] -> alice(12), charlie(15), bob(20)
        result = lib.zset_range_by_score(zset, 10.0, 20.0)
        r = result.contents
        assert r.count == 3
        assert r.members[0] == b"alice"
        assert r.scores[0] == 12.0
        assert r.members[1] == b"charlie"
        assert r.scores[1] == 15.0
        assert r.members[2] == b"bob"
        assert r.scores[2] == 20.0
        lib.zset_range_free(result)

        # Range by rank [1, 3] -> alice(12), charlie(15), bob(20)
        result = lib.zset_range_by_rank(zset, 1, 3)
        r = result.contents
        assert r.count == 3
        assert r.members[0] == b"alice"
        assert r.members[1] == b"charlie"
        assert r.members[2] == b"bob"
        lib.zset_range_free(result)

        # Foreach — collect all in order
        collected = []

        @ITER_CALLBACK
        def cb(member, sc, _ud):
            collected.append(member)
            return 0

        lib.zset_foreach(zset, cb, None)
        assert collected == [b"eve", b"alice", b"charlie", b"bob", b"dave"]

        # Clone, mutate, verify independence
        clone = lib.zset_clone(zset)
        lib.zset_add(clone, b"frank", 99.0)
        assert lib.zset_card(clone) == 6
        assert lib.zset_card(zset) == 5
        lib.zset_free(clone)

        # Remove and verify
        lib.zset_remove(zset, b"charlie")
        assert lib.zset_card(zset) == 4

        result = lib.zset_range_by_rank(zset, 0, 3)
        r = result.contents
        assert r.count == 4
        members = [r.members[i] for i in range(r.count)]
        assert b"charlie" not in members
        lib.zset_range_free(result)
