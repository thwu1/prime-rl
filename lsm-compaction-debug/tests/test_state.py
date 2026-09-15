
"""
Tests for the B+ tree sorted set (bptree_zset.py).

Verifies: split correctness, deletion integrity, leaf-chain consistency,
zrank via augmented subtree sizes, zrangebyscore boundary handling,
structural invariants, and mixed-workload data integrity.
"""

import sys
import random

sys.path.insert(0, "/app")
from bptree_zset import BPTreeZSet, BPNode


# ------------------------------------------------------------------ #
#  Helpers                                                            #
# ------------------------------------------------------------------ #


def _collect_leaf_chain(zset: BPTreeZSet):
    """Walk the leaf doubly-linked list and return all (score, member) entries."""
    node = zset._leftmost_leaf()
    entries = []
    visited = set()
    while node is not None:
        nid = id(node)
        if nid in visited:
            raise AssertionError("Cycle detected in leaf chain")
        visited.add(nid)
        entries.extend(node.keys)
        node = node.next_leaf
    return entries


def _verify_invariants(zset: BPTreeZSet):
    """Check structural B+ tree invariants.  Raises AssertionError on violation."""
    root = zset.root
    order = zset.order
    min_keys = (order - 1) // 2

    stack = [(root, None, None)]  # (node, lower_bound, upper_bound)
    leaf_count = 0
    internal_count = 0

    while stack:
        node, lo, hi = stack.pop()

        # Keys must be sorted
        for i in range(len(node.keys) - 1):
            assert node.keys[i] <= node.keys[i + 1], (
                f"Keys not sorted: {node.keys[i]} > {node.keys[i + 1]}"
            )

        # Bound checks
        if lo is not None:
            for k in node.keys:
                assert k >= lo, f"Key {k} < lower bound {lo}"
        if hi is not None:
            for k in node.keys:
                assert k < hi, f"Key {k} >= upper bound {hi}"

        if node.is_leaf:
            leaf_count += 1
            if node is not root:
                assert len(node.keys) >= min_keys, (
                    f"Leaf has {len(node.keys)} keys, min is {min_keys}"
                )
        else:
            internal_count += 1
            assert len(node.children) == len(node.keys) + 1, (
                f"Internal node: {len(node.keys)} keys but "
                f"{len(node.children)} children"
            )
            if node is not root:
                assert len(node.keys) >= min_keys, (
                    f"Internal node has {len(node.keys)} keys, min is {min_keys}"
                )
            for i, child in enumerate(node.children):
                assert child.parent is node, "Child→parent pointer mismatch"
                child_lo = node.keys[i - 1] if i > 0 else lo
                child_hi = node.keys[i] if i < len(node.keys) else hi
                stack.append((child, child_lo, child_hi))

    # Leaf chain must cover every entry exactly once
    leaf_entries = _collect_leaf_chain(zset)
    assert len(leaf_entries) == zset.zcard(), (
        f"Leaf chain has {len(leaf_entries)} entries but zcard()={zset.zcard()}"
    )
    assert len(leaf_entries) == len(set(leaf_entries)), (
        "Duplicate entries in leaf chain"
    )


# ------------------------------------------------------------------ #
#  Tests                                                              #
# ------------------------------------------------------------------ #


def test_basic_operations_no_split():
    """Basic zadd / zscore / zrem with fewer entries than the node order."""
    zset = BPTreeZSet(order=8)
    assert zset.zadd("alice", 10.0) is True
    assert zset.zadd("bob", 5.0) is True
    assert zset.zadd("carol", 15.0) is True
    assert zset.zadd("dave", 5.0) is True  # same score as bob

    assert zset.zscore("alice") == 10.0
    assert zset.zscore("bob") == 5.0
    assert zset.zcard() == 4

    assert zset.zrem("carol") is True
    assert zset.zscore("carol") is None
    assert zset.zcard() == 3

    # zrange should return the 3 remaining in score order
    results = zset.zrange(0, 10)
    members = [m for m, _ in results]
    assert members == ["bob", "dave", "alice"], f"Got {members}"


def test_delete_not_in_range_after_removal():
    """After many inserts (triggering splits) and deletions, deleted entries
    must not appear in range scans."""
    zset = BPTreeZSet(order=8)
    n = 60
    for i in range(n):
        zset.zadd(f"m{i:03d}", float(i))

    to_delete = list(range(0, n, 3))  # delete every 3rd entry
    for i in to_delete:
        zset.zrem(f"m{i:03d}")

    results = zset.zrange(0, n)
    result_members = {m for m, _ in results}
    for i in to_delete:
        assert f"m{i:03d}" not in result_members, (
            f"m{i:03d} should have been deleted but appears in zrange"
        )

    expected_remaining = n - len(to_delete)
    assert len(results) == expected_remaining, (
        f"Expected {expected_remaining} entries, got {len(results)}"
    )


def test_zadd_update_score_consistency():
    """Updating a member's score must remove the old tree entry and insert a
    new one — no orphaned entries at the old score."""
    zset = BPTreeZSet(order=8)
    for i in range(40):
        zset.zadd(f"m{i:03d}", float(i))

    # Move several members to new scores
    moved = [3, 7, 11, 15, 19, 23, 27, 31, 35, 39]
    for i in moved:
        zset.zadd(f"m{i:03d}", float(i) + 1000.0)

    # Old scores must not appear
    for i in moved:
        old_score = float(i)
        hits = zset.zrangebyscore(old_score - 0.1, old_score + 0.1)
        members_at_old = [m for m, _ in hits]
        assert f"m{i:03d}" not in members_at_old, (
            f"m{i:03d} still appears at old score {old_score}"
        )

    # New scores must appear
    for i in moved:
        new_score = float(i) + 1000.0
        hits = zset.zrangebyscore(new_score - 0.1, new_score + 0.1)
        members_at_new = [m for m, _ in hits]
        assert f"m{i:03d}" in members_at_new, (
            f"m{i:03d} missing at new score {new_score}"
        )


def test_merge_no_duplicates_in_range():
    """Heavy deletion that triggers node merges must not introduce duplicates
    in range scans."""
    zset = BPTreeZSet(order=6)
    n = 48
    for i in range(n):
        zset.zadd(f"m{i:03d}", float(i))

    # Delete most entries to force many merges
    for i in range(36):
        zset.zrem(f"m{i:03d}")

    results = zset.zrange(0, n)
    members = [m for m, _ in results]
    assert len(members) == len(set(members)), (
        f"Duplicate entries in range scan: "
        f"{[m for m in members if members.count(m) > 1]}"
    )
    assert len(members) == zset.zcard(), (
        f"Leaf-chain walk returned {len(members)} entries, "
        f"but zcard()={zset.zcard()}"
    )


def test_zrangebyscore_includes_boundary():
    """zrangebyscore must include the entry whose score exactly equals
    min_score (no off-by-one)."""
    zset = BPTreeZSet(order=8)
    for i in range(25):
        zset.zadd(f"m{i:03d}", float(i))

    results = zset.zrangebyscore(5.0, 10.0)
    members = {m for m, _ in results}

    assert "m005" in members, (
        "Entry at exact min_score boundary missing from zrangebyscore"
    )
    assert "m010" in members, (
        "Entry at exact max_score boundary missing from zrangebyscore"
    )
    assert "m004" not in members, "Entry below min_score should be excluded"
    assert "m011" not in members, "Entry above max_score should be excluded"
    assert len(results) == 6, f"Expected 6 results, got {len(results)}"


def test_zrank_basic():
    """zrank must return the correct 0-based position for each member."""
    zset = BPTreeZSet(order=8)
    entries = [(f"m{i:03d}", float(i)) for i in range(35)]
    for member, score in entries:
        zset.zadd(member, score)

    for expected_rank, (member, _) in enumerate(entries):
        actual = zset.zrank(member)
        assert actual == expected_rank, (
            f"zrank({member}): expected {expected_rank}, got {actual}"
        )

    assert zset.zrank("nonexistent") == -1


def test_zrank_with_updates_and_deletes():
    """zrank must remain correct after score updates and deletions."""
    zset = BPTreeZSet(order=8)
    for i in range(50):
        zset.zadd(f"m{i:03d}", float(i))

    # Move m010 from score 10.0 → 45.5 (between m045 and m046)
    zset.zadd("m010", 45.5)

    # Delete m020
    zset.zrem("m020")

    # Build the expected order manually
    expected = []
    for i in range(50):
        if i == 10:
            continue  # moved
        if i == 20:
            continue  # deleted
        expected.append((f"m{i:03d}", float(i)))
    # Insert m010 at new score
    expected.append(("m010", 45.5))
    expected.sort(key=lambda x: (x[1], x[0]))

    for rank, (member, _) in enumerate(expected):
        actual = zset.zrank(member)
        assert actual == rank, (
            f"zrank({member}): expected {rank}, got {actual}"
        )


def test_structural_invariants():
    """B+ tree structural invariants must hold after a batch of mixed
    insertions, updates, and deletions."""
    zset = BPTreeZSet(order=8)
    rng = random.Random(12345)

    members = [f"m{i:04d}" for i in range(200)]
    for m in members:
        zset.zadd(m, rng.uniform(0, 1000))

    # Updates
    for m in rng.sample(members, 40):
        zset.zadd(m, rng.uniform(0, 1000))

    # Deletions
    for m in rng.sample(members, 60):
        zset.zrem(m)

    _verify_invariants(zset)


def test_large_mixed_workload():
    """Data integrity under a heavy mixed workload with seeded RNG."""
    zset = BPTreeZSet(order=8)
    rng = random.Random(98765)
    ground_truth: Dict[str, float] = {}

    for _ in range(3000):
        op = rng.random()
        member = f"m{rng.randint(0, 199):04d}"

        if op < 0.5:
            # zadd
            score = rng.uniform(-500, 500)
            zset.zadd(member, score)
            ground_truth[member] = score
        elif op < 0.7 and member in ground_truth:
            # zrem
            zset.zrem(member)
            del ground_truth[member]
        elif op < 0.85:
            # zscore
            expected = ground_truth.get(member)
            actual = zset.zscore(member)
            assert actual == expected, (
                f"zscore({member}): expected {expected}, got {actual}"
            )
        else:
            # zrangebyscore spot check
            lo = rng.uniform(-500, 500)
            hi = lo + rng.uniform(0, 100)
            results = zset.zrangebyscore(lo, hi)
            for m, s in results:
                assert lo <= s <= hi, f"Score {s} outside [{lo}, {hi}]"

    # Final consistency: every ground-truth member present & ranked
    assert zset.zcard() == len(ground_truth)

    all_entries = zset.zrange(0, zset.zcard())
    all_members = {m for m, _ in all_entries}
    for member, score in ground_truth.items():
        assert member in all_members, f"{member} missing from zrange"
        assert zset.zscore(member) == score

    # No duplicates
    leaf_entries = _collect_leaf_chain(zset)
    assert len(leaf_entries) == len(set(leaf_entries)), (
        "Duplicate entries in leaf chain after workload"
    )


# required for the Dict type hint used in test_large_mixed_workload
from typing import Dict
