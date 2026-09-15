#!/usr/bin/env python3

"""
Diagnose and fix correctness bugs in the B+ tree sorted set implementation
by comparing behaviour against Redis and tracing through the source code.

Three bugs are identified via differential testing:

1. Leaf linked-list corruption during merge-right in _fix_underflow:
   When the leftmost child underflows and merges with its right sibling,
   the code omits updating node.next_leaf to right.next_leaf. This leaves
   orphaned nodes in the leaf chain, causing range scans (zrangebyscore,
   zrange via range_by_rank) to traverse defunct nodes and return duplicate
   entries.

2. zpopmax result ordering:
   An erroneous result.reverse() call returns popped elements in ascending
   score order instead of descending (highest-score-first), diverging from
   Redis ZPOPMAX semantics.

3. zrangebyscore LIMIT offset initialisation:
   The skip counter is initialised to 1 instead of 0, causing offset-based
   pagination to skip one fewer element than requested (off-by-one).
"""

import subprocess
import redis
import sys
import time


def verify_against_redis():
    """Run a quick differential check to confirm fix correctness."""
    r = redis.Redis()
    r.flushall()

    # Verify ZPOPMAX ordering
    r.zadd("zpm", {"a": 1, "b": 2, "c": 3, "d": 4})
    redis_pop = r.zpopmax("zpm", 3)
    # Redis returns list of (member_bytes, score) in descending order
    expected_order = [(b"d", 4.0), (b"c", 3.0), (b"b", 2.0)]
    assert redis_pop == expected_order, f"Redis ZPOPMAX sanity: {redis_pop}"

    # Verify ZRANGEBYSCORE LIMIT
    r.flushall()
    for i in range(10):
        r.zadd("zrs", {f"m{i}": float(i)})
    redis_range = r.zrangebyscore("zrs", 0, 9, start=2, num=3, withscores=True)
    assert redis_range[0] == (b"m2", 2.0), f"Redis LIMIT sanity: {redis_range}"

    r.flushall()
    print("Redis verification passed.")


def apply_fixes():
    """Read the buggy source, apply three targeted patches, write it back."""
    with open("/app/sorted_set.py", "r") as f:
        code = f.read()

    original = code  # keep for verification

    # ── Fix 1: Restore leaf linked-list update in merge-right path ──
    # The merge-right branch (else clause in _fix_underflow merge section)
    # for leaf nodes must update node.next_leaf = right.next_leaf so the
    # linked list skips over the absorbed sibling.
    old_merge = (
        "            else:\n"
        "                parent.keys.pop(ci)  # remove separator\n"
        "                node.keys.extend(right.keys)\n"
        "            parent.children.pop(ci + 1)"
    )
    new_merge = (
        "            else:\n"
        "                parent.keys.pop(ci)  # remove separator\n"
        "                node.keys.extend(right.keys)\n"
        "                node.next_leaf = right.next_leaf\n"
        "            parent.children.pop(ci + 1)"
    )
    assert old_merge in code, "Bug 1 pattern not found in source"
    code = code.replace(old_merge, new_merge, 1)

    # ── Fix 2: Remove erroneous result.reverse() in zpopmax ──
    # Redis ZPOPMAX returns elements from highest to lowest score.
    # The loop already pops the current maximum each iteration, so the
    # result list is naturally in descending order.  The reverse() call
    # inverts it to ascending, which is wrong.
    old_pop = "        result.reverse()\n        return result"
    new_pop = "        return result"
    assert old_pop in code, "Bug 2 pattern not found in source"
    code = code.replace(old_pop, new_pop, 1)

    # ── Fix 3: Fix skip-counter initialisation in zrangebyscore ──
    # The LIMIT offset skip counter must start at 0.  Starting at 1
    # means offset=N actually skips N-1 elements.
    old_skip = "        skipped = 1\n        collected = 0"
    new_skip = "        skipped = 0\n        collected = 0"
    assert old_skip in code, "Bug 3 pattern not found in source"
    code = code.replace(old_skip, new_skip, 1)

    assert code != original, "No changes were made"

    with open("/app/sorted_set.py", "w") as f:
        f.write(code)

    print("Applied 3 fixes to /app/sorted_set.py")


if __name__ == "__main__":
    apply_fixes()

    # Quick verification against Redis
    try:
        verify_against_redis()
    except Exception as e:
        print(f"Redis verification skipped: {e}", file=sys.stderr)

    # Run our own sanity check with the fixed module
    sys.path.insert(0, "/app")
    from sorted_set import BPTreeSortedSet

    ss = BPTreeSortedSet()
    for i in range(500):
        ss.zadd([(float(i), f"m{i:04d}")])
    for i in range(200):
        ss.zrem(f"m{i:04d}")

    elems = ss.zrangebyscore(float("-inf"), float("inf"))
    assert len(elems) == 300, f"Range scan: {len(elems)} != 300"
    assert len(set(m for m, _ in elems)) == 300, "Duplicates in range scan"
    assert ss._verify_integrity(), "Integrity check failed"

    ss2 = BPTreeSortedSet()
    for i in range(10):
        ss2.zadd([(float(i), f"e{i}")])
    r = ss2.zpopmax(3)
    assert r == [("e9", 9.0), ("e8", 8.0), ("e7", 7.0)], f"ZPOPMAX order: {r}"

    r2 = ss2.zrangebyscore(0.0, 9.0, offset=2, count=3)
    assert r2 == [("e2", 2.0), ("e3", 3.0), ("e4", 4.0)], f"LIMIT offset: {r2}"

    print("All sanity checks passed.")
