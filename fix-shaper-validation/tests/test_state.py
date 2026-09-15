"""
Tests for the hierarchical network traffic shaper library.

Verifies that /app/libshaper.so conforms to the specification in /app/SPEC.md.

"""
import ctypes
import subprocess
import pytest

# ── Constants from shaper.h ──────────────────────────────────────────
SCOPE_NETDEV = 1
SCOPE_QUEUE  = 2
SCOPE_GROUP  = 3
HANDLE_ID_BITS = 30
HANDLE_ID_MAX  = (1 << HANDLE_ID_BITS) - 1


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def build_lib():
    """Compile the shared library once."""
    r = subprocess.run(["make", "-C", "/app", "clean", "all"],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"Build failed:\n{r.stderr}\n{r.stdout}"


@pytest.fixture(scope="session")
def lib(build_lib):
    """Load libshaper.so and set function signatures."""
    lib = ctypes.CDLL("/app/libshaper.so")
    lib.shaper_ctx_new.restype          = ctypes.c_void_p
    lib.shaper_ctx_free.restype         = None
    lib.shaper_node_create.restype      = ctypes.c_int
    lib.shaper_node_delete.restype      = ctypes.c_int
    lib.shaper_node_modify.restype      = ctypes.c_int
    lib.shaper_find_by_handle.restype   = ctypes.c_int
    lib.shaper_group.restype            = ctypes.c_int
    lib.shaper_rebalance.restype        = ctypes.c_int
    lib.shaper_compact.restype          = ctypes.c_int
    lib.shaper_get_handle.restype       = ctypes.c_uint32
    lib.shaper_get_used.restype         = ctypes.c_int
    lib.shaper_get_parent.restype       = ctypes.c_int
    lib.shaper_get_child_count.restype  = ctypes.c_int
    lib.shaper_get_rate.restype         = ctypes.c_uint64
    lib.shaper_validate_tree.restype    = ctypes.c_int
    return lib


@pytest.fixture
def ctx(lib):
    """Fresh shaper context per test."""
    c = lib.shaper_ctx_new()
    assert c not in (None, 0)
    yield c
    lib.shaper_ctx_free(ctypes.c_void_p(c))


# ── Helpers ──────────────────────────────────────────────────────────

def _vp(ctx):
    return ctypes.c_void_p(ctx)


def create(lib, ctx, scope, hid, rate=1000000, burst=1000, parent=-1):
    return lib.shaper_node_create(
        _vp(ctx), ctypes.c_int(scope), ctypes.c_uint32(hid),
        ctypes.c_uint64(rate), ctypes.c_uint64(burst),
        ctypes.c_int(parent))


def get_h(lib, ctx, idx):
    return lib.shaper_get_handle(_vp(ctx), ctypes.c_int(idx))


def get_rate(lib, ctx, idx):
    return lib.shaper_get_rate(_vp(ctx), ctypes.c_int(idx))


def do_group(lib, ctx, parent, handles, rate=500000, burst=500,
             results_size=None):
    n = len(handles)
    if results_size is None:
        results_size = n
    h_arr = (ctypes.c_uint32 * n)(*handles)
    # Always allocate a safe buffer (at least n entries)
    buf_n = max(n, results_size)
    r_arr = (ctypes.c_int * buf_n)()
    ret = lib.shaper_group(
        _vp(ctx), ctypes.c_int(parent),
        h_arr, ctypes.c_int(n),
        ctypes.c_uint64(rate), ctypes.c_uint64(burst),
        r_arr, ctypes.c_int(results_size))
    return ret, list(r_arr[:n])


def rebalance(lib, ctx, subtree_root):
    return lib.shaper_rebalance(_vp(ctx), ctypes.c_int(subtree_root))


def compact(lib, ctx):
    return lib.shaper_compact(_vp(ctx))


# ── QUEUE scope: id must be > 0 ─────────────────────────────────────

class TestQueueScopeId:
    def test_queue_id_zero_rejected(self, lib, ctx):
        root = create(lib, ctx, SCOPE_NETDEV, 0)
        assert root >= 0
        ret = create(lib, ctx, SCOPE_QUEUE, 0, parent=root)
        assert ret < 0, "QUEUE scope with id=0 must be rejected"

    def test_queue_id_positive_accepted(self, lib, ctx):
        root = create(lib, ctx, SCOPE_NETDEV, 0)
        assert root >= 0
        ret = create(lib, ctx, SCOPE_QUEUE, 1, parent=root)
        assert ret >= 0, "QUEUE with id=1 must succeed"


# ── NETDEV scope: singleton, id must be 0 ───────────────────────────

class TestNetdevSingleton:
    def test_second_netdev_rejected(self, lib, ctx):
        r1 = create(lib, ctx, SCOPE_NETDEV, 0)
        assert r1 >= 0
        ret = create(lib, ctx, SCOPE_NETDEV, 0)
        assert ret < 0, "Second NETDEV root must be rejected"

    def test_netdev_nonzero_id_rejected(self, lib, ctx):
        ret = create(lib, ctx, SCOPE_NETDEV, 1)
        assert ret < 0, "NETDEV with id != 0 must be rejected"

    def test_netdev_id_zero_accepted(self, lib, ctx):
        ret = create(lib, ctx, SCOPE_NETDEV, 0)
        assert ret >= 0, "NETDEV with id=0 must succeed"


# ── Handle ID: must not exceed 30-bit maximum ───────────────────────

class TestHandleIdRange:
    def test_max_valid_id_accepted(self, lib, ctx):
        root = create(lib, ctx, SCOPE_NETDEV, 0)
        assert root >= 0
        ret = create(lib, ctx, SCOPE_QUEUE, HANDLE_ID_MAX, parent=root)
        assert ret >= 0, f"Max ID ({HANDLE_ID_MAX}) must be accepted"

    def test_overflow_id_rejected(self, lib, ctx):
        root = create(lib, ctx, SCOPE_NETDEV, 0)
        assert root >= 0
        ret = create(lib, ctx, SCOPE_QUEUE, HANDLE_ID_MAX + 1, parent=root)
        assert ret < 0, "ID exceeding 30-bit max must be rejected"

    def test_large_overflow_id_rejected(self, lib, ctx):
        root = create(lib, ctx, SCOPE_NETDEV, 0)
        assert root >= 0
        ret = create(lib, ctx, SCOPE_QUEUE, 0xFFFFFFFF, parent=root)
        assert ret < 0, "ID 0xFFFFFFFF must be rejected"


# ── GROUP: results_size must be >= n_leaves ──────────────────────────

class TestGroupResultsSize:
    def test_undersized_results_rejected(self, lib, ctx):
        root = create(lib, ctx, SCOPE_NETDEV, 0)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, parent=root)
        q3 = create(lib, ctx, SCOPE_QUEUE, 3, parent=root)
        assert all(x >= 0 for x in [root, q1, q2, q3])

        handles = [get_h(lib, ctx, q1), get_h(lib, ctx, q2),
                   get_h(lib, ctx, q3)]
        ret, _ = do_group(lib, ctx, root, handles, results_size=2)
        assert ret < 0, "GROUP with results_size < n_leaves must fail"

    def test_exact_results_size_accepted(self, lib, ctx):
        root = create(lib, ctx, SCOPE_NETDEV, 0)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, parent=root)
        assert all(x >= 0 for x in [root, q1, q2])

        handles = [get_h(lib, ctx, q1), get_h(lib, ctx, q2)]
        ret, sts = do_group(lib, ctx, root, handles, results_size=2)
        assert ret >= 0, "GROUP with results_size == n_leaves must succeed"
        assert all(s == 0 for s in sts)


# ── GROUP: duplicate leaf handles must be rejected ───────────────────

class TestGroupDuplicateLeaves:
    def test_duplicate_leaves_rejected(self, lib, ctx):
        root = create(lib, ctx, SCOPE_NETDEV, 0)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, parent=root)
        assert root >= 0 and q1 >= 0

        h1 = get_h(lib, ctx, q1)
        ret, _ = do_group(lib, ctx, root, [h1, h1])
        assert ret < 0, "GROUP with duplicate leaves must be rejected"

    def test_unique_leaves_accepted(self, lib, ctx):
        root = create(lib, ctx, SCOPE_NETDEV, 0)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, parent=root)
        assert all(x >= 0 for x in [root, q1, q2])

        handles = [get_h(lib, ctx, q1), get_h(lib, ctx, q2)]
        ret, _ = do_group(lib, ctx, root, handles)
        assert ret >= 0, "GROUP with unique leaves must succeed"


# ── Duplicate handle detection (handle_exists polarity) ──────────────

class TestDuplicateHandleDetection:
    def test_same_handle_rejected(self, lib, ctx):
        root = create(lib, ctx, SCOPE_NETDEV, 0)
        assert root >= 0
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, parent=root)
        assert q1 >= 0
        ret = create(lib, ctx, SCOPE_QUEUE, 1, parent=root)
        assert ret < 0, "Creating node with duplicate handle must fail"

    def test_different_handles_accepted(self, lib, ctx):
        root = create(lib, ctx, SCOPE_NETDEV, 0)
        assert root >= 0
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, parent=root)
        assert q1 >= 0 and q2 >= 0

    def test_reuse_handle_after_delete(self, lib, ctx):
        root = create(lib, ctx, SCOPE_NETDEV, 0)
        assert root >= 0
        q = create(lib, ctx, SCOPE_QUEUE, 10, parent=root)
        assert q >= 0

        ret = lib.shaper_node_delete(_vp(ctx), ctypes.c_int(q))
        assert ret == 0

        q2 = create(lib, ctx, SCOPE_QUEUE, 10, parent=root)
        assert q2 >= 0, "Handle must be reusable after deletion"


# ── validate_tree: must accept single-child GROUP ────────────────────

class TestValidateTree:
    def test_single_child_group_valid(self, lib, ctx):
        """validate_tree must NOT reject a GROUP with exactly 1 child."""
        root = create(lib, ctx, SCOPE_NETDEV, 0)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, parent=root)
        assert root >= 0 and q1 >= 0

        handles = [get_h(lib, ctx, q1)]
        grp, sts = do_group(lib, ctx, root, handles, rate=500000)
        assert grp >= 0, "GROUP creation with 1 leaf should succeed"

        ret = lib.shaper_validate_tree(_vp(ctx))
        assert ret == 0, (
            f"validate_tree returned {ret} for a valid tree with a "
            f"single-child GROUP — the spec allows GROUP nodes with 1 child"
        )

    def test_valid_tree_after_child_deletion(self, lib, ctx):
        """Deleting one child from a 2-child GROUP leaves 1 child; still valid."""
        root = create(lib, ctx, SCOPE_NETDEV, 0)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, parent=root)
        assert all(x >= 0 for x in [root, q1, q2])

        handles = [get_h(lib, ctx, q1), get_h(lib, ctx, q2)]
        grp, _ = do_group(lib, ctx, root, handles, rate=500000)
        assert grp >= 0

        # Delete q2 — group now has 1 child
        ret = lib.shaper_node_delete(_vp(ctx), ctypes.c_int(q2))
        assert ret == 0

        ret = lib.shaper_validate_tree(_vp(ctx))
        assert ret == 0, (
            f"validate_tree returned {ret} after removing a child from "
            f"a GROUP — single-child GROUPs are valid per spec"
        )


# ── shaper_rebalance: hierarchical rate enforcement ──────────────────

class TestRebalance:
    def test_no_scaling_needed(self, lib, ctx):
        """Children sum <= parent rate: no changes."""
        root = create(lib, ctx, SCOPE_NETDEV, 0, rate=1000000)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, rate=300000, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, rate=400000, parent=root)
        assert all(x >= 0 for x in [root, q1, q2])

        ret = rebalance(lib, ctx, root)
        assert ret == 0
        assert get_rate(lib, ctx, q1) == 300000, "Rate should be unchanged"
        assert get_rate(lib, ctx, q2) == 400000, "Rate should be unchanged"

    def test_proportional_scaling(self, lib, ctx):
        """Proportional reduction when children exceed parent rate."""
        root = create(lib, ctx, SCOPE_NETDEV, 0, rate=1000000)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, rate=600000, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, rate=300000, parent=root)
        q3 = create(lib, ctx, SCOPE_QUEUE, 3, rate=300000, parent=root)
        assert all(x >= 0 for x in [root, q1, q2, q3])
        # sum=1,200,000 > 1,000,000
        # q1: floor(600000 * 1000000 / 1200000) = 500000
        # q2: floor(300000 * 1000000 / 1200000) = 250000
        # q3: floor(300000 * 1000000 / 1200000) = 250000
        # sum=1000000, remainder=0

        ret = rebalance(lib, ctx, root)
        assert ret == 0
        assert get_rate(lib, ctx, q1) == 500000
        assert get_rate(lib, ctx, q2) == 250000
        assert get_rate(lib, ctx, q3) == 250000

    def test_remainder_distribution(self, lib, ctx):
        """Remainder from floor division goes to first children."""
        root = create(lib, ctx, SCOPE_NETDEV, 0, rate=1000000)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, rate=400000, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, rate=400000, parent=root)
        q3 = create(lib, ctx, SCOPE_QUEUE, 3, rate=400000, parent=root)
        assert all(x >= 0 for x in [root, q1, q2, q3])
        # sum=1,200,000 > 1,000,000
        # each: floor(400000 * 1000000 / 1200000) = 333333
        # sum=999999, remainder=1 → q1 gets +1

        ret = rebalance(lib, ctx, root)
        assert ret == 0
        assert get_rate(lib, ctx, q1) == 333334, "First child gets remainder"
        assert get_rate(lib, ctx, q2) == 333333
        assert get_rate(lib, ctx, q3) == 333333

    def test_zero_rate_child_stays_zero(self, lib, ctx):
        """A child with rate=0 stays at 0 and does not receive remainder."""
        root = create(lib, ctx, SCOPE_NETDEV, 0, rate=1000000)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, rate=0, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, rate=800000, parent=root)
        q3 = create(lib, ctx, SCOPE_QUEUE, 3, rate=600000, parent=root)
        assert all(x >= 0 for x in [root, q1, q2, q3])
        # sum=1,400,000 > 1,000,000
        # q1: floor(0 * 1000000 / 1400000) = 0
        # q2: floor(800000 * 1000000 / 1400000) = 571428
        # q3: floor(600000 * 1000000 / 1400000) = 428571
        # sum=999999, remainder=1
        # Skip q1 (rate 0), q2 gets +1 → 571429

        ret = rebalance(lib, ctx, root)
        assert ret == 0
        assert get_rate(lib, ctx, q1) == 0, "Zero-rate child must stay zero"
        assert get_rate(lib, ctx, q2) == 571429, "Non-zero child gets remainder"
        assert get_rate(lib, ctx, q3) == 428571

    def test_all_zero_children_no_crash(self, lib, ctx):
        """All children at rate=0: total is 0, no scaling, no crash."""
        root = create(lib, ctx, SCOPE_NETDEV, 0, rate=1000000)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, rate=0, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, rate=0, parent=root)
        assert all(x >= 0 for x in [root, q1, q2])

        ret = rebalance(lib, ctx, root)
        assert ret == 0
        assert get_rate(lib, ctx, q1) == 0
        assert get_rate(lib, ctx, q2) == 0

    def test_deep_tree_post_order(self, lib, ctx):
        """Post-order DFS: rebalance inner group first, then root."""
        root = create(lib, ctx, SCOPE_NETDEV, 0, rate=1000000)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, rate=500000, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, rate=400000, parent=root)
        q3 = create(lib, ctx, SCOPE_QUEUE, 3, rate=500000, parent=root)
        assert all(x >= 0 for x in [root, q1, q2, q3])

        # Group q1 and q2 under a GROUP with rate=700000
        handles = [get_h(lib, ctx, q1), get_h(lib, ctx, q2)]
        grp, sts = do_group(lib, ctx, root, handles, rate=700000)
        assert grp >= 0
        assert all(s == 0 for s in sts)

        # Tree:
        # Root (1,000,000)
        # ├── Group (700,000)
        # │   ├── Q1 (500,000)
        # │   └── Q2 (400,000)  → sum=900,000 > 700,000
        # └── Q3 (500,000)      → root sum=1,200,000 > 1,000,000

        ret = rebalance(lib, ctx, root)
        assert ret == 0

        # Step 1 (Group rebalance — group children are [q1, q2]):
        #   Q1: floor(500000*700000/900000) = 388888, +1 remainder → 388889
        #   Q2: floor(400000*700000/900000) = 311111
        # Step 2 (Root rebalance — root children are [q3, grp] after reparenting):
        #   Q3: floor(500000*1000000/1200000) = 416666, +1 remainder → 416667
        #   Group: floor(700000*1000000/1200000) = 583333
        assert get_rate(lib, ctx, q1) == 388889
        assert get_rate(lib, ctx, q2) == 311111
        assert get_rate(lib, ctx, grp) == 583333
        assert get_rate(lib, ctx, q3) == 416667

    def test_invalid_node_rejected(self, lib, ctx):
        """Rebalancing an invalid or inactive node returns -EINVAL."""
        ret = rebalance(lib, ctx, 999)
        assert ret < 0, "Out-of-range index must return error"

        ret = rebalance(lib, ctx, -1)
        assert ret < 0, "Negative index must return error"

        # Create and delete a node, then rebalance the deleted index
        root = create(lib, ctx, SCOPE_NETDEV, 0, rate=1000000)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, rate=500000, parent=root)
        assert root >= 0 and q1 >= 0
        lib.shaper_node_delete(_vp(ctx), ctypes.c_int(q1))
        ret = rebalance(lib, ctx, q1)
        assert ret < 0, "Inactive node must return error"


# ── shaper_compact: node array defragmentation ───────────────────────

class TestCompact:
    def test_compact_closes_gap(self, lib, ctx):
        """Delete a node, compact, verify tree integrity via validate_tree."""
        root = create(lib, ctx, SCOPE_NETDEV, 0, rate=1000000)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, rate=300000, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, rate=400000, parent=root)
        q3 = create(lib, ctx, SCOPE_QUEUE, 3, rate=500000, parent=root)
        assert all(x >= 0 for x in [root, q1, q2, q3])

        lib.shaper_node_delete(_vp(ctx), ctypes.c_int(q1))

        ret = compact(lib, ctx)
        assert ret == 3, f"compact must return 3 (active nodes), got {ret}"

        ret = lib.shaper_validate_tree(_vp(ctx))
        assert ret == 0, (
            f"validate_tree returned {ret} after compact — "
            f"all parent/child cross-references must be remapped"
        )

    def test_compact_preserves_handles(self, lib, ctx):
        """Handles survive compaction — find_by_handle works."""
        root = create(lib, ctx, SCOPE_NETDEV, 0, rate=1000000)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, rate=300000, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, rate=400000, parent=root)
        assert all(x >= 0 for x in [root, q1, q2])

        h_root = get_h(lib, ctx, root)
        h_q2 = get_h(lib, ctx, q2)

        lib.shaper_node_delete(_vp(ctx), ctypes.c_int(q1))
        ret = compact(lib, ctx)
        assert ret == 2

        r = lib.shaper_find_by_handle(_vp(ctx), ctypes.c_uint32(h_root))
        assert r >= 0, "Root handle must be findable after compact"
        r = lib.shaper_find_by_handle(_vp(ctx), ctypes.c_uint32(h_q2))
        assert r >= 0, "Q2 handle must be findable after compact"

    def test_compact_grouped_tree(self, lib, ctx):
        """Compact a tree with GROUP nodes — cross-references must be correct."""
        root = create(lib, ctx, SCOPE_NETDEV, 0, rate=2000000)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, rate=500000, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, rate=600000, parent=root)
        q3 = create(lib, ctx, SCOPE_QUEUE, 3, rate=700000, parent=root)
        q4 = create(lib, ctx, SCOPE_QUEUE, 4, rate=800000, parent=root)
        assert all(x >= 0 for x in [root, q1, q2, q3, q4])

        handles = [get_h(lib, ctx, q1), get_h(lib, ctx, q2)]
        grp, _ = do_group(lib, ctx, root, handles, rate=1000000)
        assert grp >= 0

        lib.shaper_node_delete(_vp(ctx), ctypes.c_int(q3))

        ret = compact(lib, ctx)
        assert ret == 5, f"Expected 5 active nodes, got {ret}"

        ret = lib.shaper_validate_tree(_vp(ctx))
        assert ret == 0, f"validate_tree failed after compact with groups: {ret}"

    def test_compact_no_gaps(self, lib, ctx):
        """No gaps — compact is a no-op, returns count unchanged."""
        root = create(lib, ctx, SCOPE_NETDEV, 0, rate=1000000)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, rate=300000, parent=root)
        assert root >= 0 and q1 >= 0

        ret = compact(lib, ctx)
        assert ret == 2

        assert lib.shaper_get_used(_vp(ctx), ctypes.c_int(0)) == 1
        assert lib.shaper_get_used(_vp(ctx), ctypes.c_int(1)) == 1

        ret = lib.shaper_validate_tree(_vp(ctx))
        assert ret == 0

    def test_compact_then_create(self, lib, ctx):
        """After compact, new node creation still works correctly."""
        root = create(lib, ctx, SCOPE_NETDEV, 0, rate=1000000)
        q1 = create(lib, ctx, SCOPE_QUEUE, 1, rate=300000, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, rate=400000, parent=root)
        assert all(x >= 0 for x in [root, q1, q2])

        h_root = get_h(lib, ctx, root)
        lib.shaper_node_delete(_vp(ctx), ctypes.c_int(q1))
        compact(lib, ctx)

        root_new = lib.shaper_find_by_handle(
            _vp(ctx), ctypes.c_uint32(h_root))
        assert root_new >= 0

        q3 = create(lib, ctx, SCOPE_QUEUE, 3, rate=500000, parent=root_new)
        assert q3 >= 0, "Must be able to create nodes after compact"

        ret = lib.shaper_validate_tree(_vp(ctx))
        assert ret == 0


# ── Integration ──────────────────────────────────────────────────────

class TestIntegration:
    def test_full_tree_lifecycle(self, lib, ctx):
        """Build a tree, group nodes, rebalance, modify, verify integrity."""
        root = create(lib, ctx, SCOPE_NETDEV, 0, rate=2000000)
        assert root >= 0

        q1 = create(lib, ctx, SCOPE_QUEUE, 1, rate=800000, parent=root)
        q2 = create(lib, ctx, SCOPE_QUEUE, 2, rate=700000, parent=root)
        q3 = create(lib, ctx, SCOPE_QUEUE, 3, rate=900000, parent=root)
        assert all(x >= 0 for x in [q1, q2, q3])

        # Group q1 and q2
        handles = [get_h(lib, ctx, q1), get_h(lib, ctx, q2)]
        grp, sts = do_group(lib, ctx, root, handles, rate=1200000)
        assert grp >= 0
        assert all(s == 0 for s in sts)

        # Verify structure
        assert lib.shaper_get_parent(_vp(ctx), ctypes.c_int(q1)) == grp
        assert lib.shaper_get_parent(_vp(ctx), ctypes.c_int(q2)) == grp
        assert lib.shaper_get_parent(_vp(ctx), ctypes.c_int(q3)) == root
        assert lib.shaper_get_child_count(_vp(ctx), ctypes.c_int(grp)) == 2

        # Tree integrity
        ret = lib.shaper_validate_tree(_vp(ctx))
        assert ret == 0, f"validate_tree returned {ret}"

        # Rebalance should adjust overcommitted levels
        ret = rebalance(lib, ctx, root)
        assert ret == 0

        # Modify
        ret = lib.shaper_node_modify(
            _vp(ctx), ctypes.c_int(q1),
            ctypes.c_uint64(2000000), ctypes.c_uint64(2000))
        assert ret == 0
        assert get_rate(lib, ctx, q1) == 2000000
