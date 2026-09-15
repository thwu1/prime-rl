#!/usr/bin/env python3
"""Diagnostic and benchmark suite for the persistent map store.

Usage:
    python3 benchmarks/run_bench.py                    # run correctness checks
    python3 benchmarks/run_bench.py --check identity   # run single check
    python3 benchmarks/run_bench.py --profile          # include tracemalloc
    python3 benchmarks/run_bench.py --profile-merge    # profile merge with cProfile
    python3 benchmarks/run_bench.py --all              # run all checks and profiles

Available checks:
    sharing, identity, canonical, diff-identity, compaction,
    collision-diff, asymmetric-diff
"""

import sys
import time
import argparse
import cProfile
import pstats
import io

sys.path.insert(0, '/app')
from store.persistent_map import PersistentMap


class _CK:
    """Key with controllable hash for collision testing."""
    def __init__(self, name, hash_val):
        self._name = name
        self._hash = hash_val
    def __hash__(self):
        return self._hash
    def __eq__(self, other):
        return isinstance(other, _CK) and self._name == other._name
    def __repr__(self):
        return f"CK({self._name!r})"


def check_sharing():
    """Updating one key should share all other root children."""
    m = PersistentMap()
    for i in range(1000):
        m = m.insert(i, i)
    m2 = m.insert(500, -1)
    r1, r2 = m._root_node(), m2._root_node()
    shared = sum(1 for a, b in zip(r1.array, r2.array) if a is b)
    total = len(r1.array)
    ratio = shared / total if total > 0 else 0
    return ratio >= 0.9, f"shared {shared}/{total} root children ({ratio:.0%})"


def check_identity():
    """Inserting same key-value must return the identical map object."""
    m = PersistentMap().insert('a', 1).insert('b', 2)
    m2 = m.insert('a', 1)
    return m is m2, f"identity {'preserved' if m is m2 else 'BROKEN — new object created'}"


def check_canonical():
    """Different insertion orders must yield identical tree structure."""
    import random
    keys = list(range(100))
    m1 = PersistentMap()
    for k in keys:
        m1 = m1.insert(k, k)
    random.seed(42)
    shuffled = keys.copy()
    random.shuffle(shuffled)
    m2 = PersistentMap()
    for k in shuffled:
        m2 = m2.insert(k, k)
    r1, r2 = m1._root_node(), m2._root_node()
    bitmaps_match = r1.data_map == r2.data_map and r1.node_map == r2.node_map
    diff = m1.diff(m2)
    return bitmaps_match and len(diff) == 0, \
        f"bitmaps {'match' if bitmaps_match else 'DIFFER'}, diff size={len(diff)}"


def check_diff_identity():
    """Self-diff should be near-instant via identity short-circuit."""
    m = PersistentMap()
    for i in range(5000):
        m = m.insert(i, i)
    t0 = time.monotonic()
    for _ in range(10):
        d = m.diff(m)
    elapsed = time.monotonic() - t0
    fast = elapsed < 0.1
    return len(d) == 0 and fast, \
        f"diff size={len(d)}, 10 iterations in {elapsed:.4f}s {'(OK)' if fast else '(TOO SLOW)'}"


def check_compaction():
    """Deleting from a sub-node that leaves one entry must compact it."""
    m = PersistentMap().insert(1, 'a').insert(33, 'b')
    m2 = m.delete(33)
    root = m2._root_node()
    bit = 1 << (hash(1) & 0xFFFFFFFF & 31)
    inline = bool(root.data_map & bit)
    not_sub = not bool(root.node_map & bit)
    return inline and not_sub, \
        f"key 1 is {'inline (compacted)' if inline else 'STILL in sub-node — not compacted'}"


def check_collision_diff():
    """Collision bucket diff must detect value changes, not just key presence."""
    k1 = _CK('a', 100)
    k2 = _CK('b', 100)
    m1 = PersistentMap().insert(k1, 1).insert(k2, 2)
    m2 = PersistentMap().insert(k1, 99).insert(k2, 2)
    diff = m1.diff(m2)
    correct = k1 in diff and k2 not in diff
    return correct, \
        f"collision value diff {'correct' if correct else 'BROKEN — value changes not detected'}"


def check_asymmetric_diff():
    """Diff must handle inline data vs sub-node at same trie position."""
    m1 = PersistentMap.from_dict({0: 'zero'})
    m2 = PersistentMap.from_dict({0: 'zero', 32: 'thirty-two'})
    diff = m1.diff(m2)
    correct = 0 not in diff and 32 in diff
    return correct, \
        f"asymmetric diff {'correct' if correct else 'BROKEN — shared keys reported as changed'}"


def check_merge_exists():
    """PersistentMap must expose a callable merge() method."""
    has_merge = hasattr(PersistentMap, 'merge') and callable(getattr(PersistentMap, 'merge'))
    return has_merge, f"merge() {'found' if has_merge else 'NOT FOUND — see issue 004'}"


def profile_merge():
    """Profile merge operation with cProfile and compare to from_dict baseline."""
    print()
    print("=" * 56)
    print("  Merge Performance — cProfile Report")
    print("=" * 56)
    print()

    base = PersistentMap()
    for i in range(5000):
        base = base.insert(i, i)

    v1 = base.insert(100, -1).insert(200, -2).insert(5001, 5001).delete(400)
    v2 = base.insert(100, -10).insert(300, -3).insert(5002, 5002).delete(401)

    pr = cProfile.Profile()
    pr.enable()
    for _ in range(20):
        merged = v1.merge(v2)
    pr.disable()

    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
    ps.print_stats(15)
    print("  --- merge() profile (20 iterations) ---")
    print(s.getvalue())

    expected = {}
    for k, val in v1.items():
        expected[k] = val
    for k, val in v2.items():
        expected[k] = val

    pr2 = cProfile.Profile()
    pr2.enable()
    for _ in range(20):
        rebuilt = PersistentMap.from_dict(expected)
    pr2.disable()

    s2 = io.StringIO()
    ps2 = pstats.Stats(pr2, stream=s2).sort_stats('cumulative')
    ps2.print_stats(5)
    print("  --- from_dict() baseline (20 iterations) ---")
    print(s2.getvalue())

    assert merged.to_dict() == expected, "Merge produced incorrect result!"
    print("  Merge correctness: VERIFIED")

    t_merge = sum(e[3] for e in pr.getstats())
    t_rebuild = sum(e[3] for e in pr2.getstats())
    if t_merge < t_rebuild:
        print(f"  merge ({t_merge:.4f}s) faster than from_dict ({t_rebuild:.4f}s) — GOOD")
    else:
        print(f"  WARNING: merge ({t_merge:.4f}s) not faster than from_dict ({t_rebuild:.4f}s)")
    print()


CHECKS = [
    ("sharing", check_sharing),
    ("identity", check_identity),
    ("canonical", check_canonical),
    ("diff-identity", check_diff_identity),
    ("compaction", check_compaction),
    ("collision-diff", check_collision_diff),
    ("asymmetric-diff", check_asymmetric_diff),
]

CHECK_MAP = {name: fn for name, fn in CHECKS}


def run_single_check(name):
    """Run a single named check, return exit code."""
    if name not in CHECK_MAP:
        print(f"Unknown check: {name}")
        print(f"Available: {', '.join(CHECK_MAP.keys())}")
        return 2
    fn = CHECK_MAP[name]
    try:
        passed, detail = fn()
    except Exception as e:
        passed, detail = False, f"EXCEPTION: {e}"
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}")
    print(f"         {detail}")
    return 0 if passed else 1


def run_all(profile=False, profile_merge_flag=False, run_all_flag=False):
    if profile or run_all_flag:
        import tracemalloc
        tracemalloc.start()

    print("=" * 56)
    print("  Persistent Map Diagnostic Suite")
    print("=" * 56)
    print()
    all_pass = True
    for name, fn in CHECKS:
        try:
            passed, detail = fn()
        except Exception as e:
            passed, detail = False, f"EXCEPTION: {e}"
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {name}")
        print(f"         {detail}")
        print()

    if profile or run_all_flag:
        print("=" * 56)
        print("  Memory Profile — tracemalloc (top 15)")
        print("=" * 56)
        print()
        snapshot = tracemalloc.take_snapshot()
        for stat in snapshot.statistics('lineno')[:15]:
            print(f"  {stat}")
        print()

    if profile_merge_flag or run_all_flag:
        if hasattr(PersistentMap, 'merge') and callable(getattr(PersistentMap, 'merge')):
            try:
                profile_merge()
            except Exception as e:
                print(f"  Merge profiling FAILED: {e}")
                all_pass = False
        else:
            print("  [SKIP] Merge profiling — merge() not yet implemented")
            print()

    summary = "All checks passed." if all_pass else "SOME CHECKS FAILED — see above."
    print(f"  Result: {summary}")
    print()
    return all_pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Persistent map diagnostics')
    parser.add_argument('--check', type=str, default=None,
                        help='Run a specific check by name')
    parser.add_argument('--profile', action='store_true',
                        help='Include tracemalloc memory profile')
    parser.add_argument('--profile-merge', action='store_true',
                        help='Profile merge operation with cProfile/pstats')
    parser.add_argument('--all', action='store_true',
                        help='Run all checks and profiles')
    args = parser.parse_args()

    if args.check:
        sys.exit(run_single_check(args.check))

    success = run_all(profile=args.profile,
                      profile_merge_flag=args.profile_merge,
                      run_all_flag=args.all)
    sys.exit(0 if success else 1)
