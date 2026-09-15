
import sys
sys.path.insert(0, '/app')

import os
import json
import subprocess
import pytest
import random
import time

from store.persistent_map import PersistentMap


# ---------------------------------------------------------------------------
# Helper: key with controllable hash for collision testing
# ---------------------------------------------------------------------------
class CollidingKey:
    def __init__(self, name, hash_val):
        self._name = name
        self._hash = hash_val

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        return isinstance(other, CollidingKey) and self._name == other._name

    def __repr__(self):
        return f"CK({self._name!r})"

    def __lt__(self, other):
        return self._name < other._name


# ===================================================================
# Regression Report Verification
# ===================================================================
class TestRegressionReport:
    @pytest.fixture
    def report(self):
        path = '/app/regression_report.json'
        assert os.path.exists(path), \
            "Missing /app/regression_report.json — run git bisect analysis"
        with open(path) as f:
            return json.load(f)

    @pytest.fixture
    def git_shas(self):
        result = subprocess.run(
            ['git', '-C', '/app', 'log', '--format=%H'],
            capture_output=True, text=True
        )
        return result.stdout.strip().split('\n')

    def test_report_structure(self, report):
        """Report must be a JSON array with issue_id, commit, description."""
        assert isinstance(report, list)
        assert len(report) >= 3, f"Expected >= 3 entries, got {len(report)}"
        for entry in report:
            assert 'issue_id' in entry, f"Missing 'issue_id': {entry}"
            assert 'commit' in entry, f"Missing 'commit': {entry}"
            assert 'description' in entry, f"Missing 'description': {entry}"
            assert len(entry['commit']) >= 7, \
                f"Commit SHA too short: {entry['commit']}"

    def test_report_commits_in_history(self, report, git_shas):
        """Each reported commit SHA must exist in the git history."""
        for entry in report:
            sha = entry['commit']
            found = any(full.startswith(sha) for full in git_shas)
            assert found, \
                f"Commit {sha} for issue {entry['issue_id']} not in git history"

    def test_report_distinct_commits(self, report, git_shas):
        """Regressions should trace to at least 2 different commits."""
        full_shas = set()
        for entry in report:
            for full in git_shas:
                if full.startswith(entry['commit']):
                    full_shas.add(full)
                    break
        assert len(full_shas) >= 2, \
            f"Expected >= 2 distinct commits, found {len(full_shas)}"

    def test_report_not_initial_commit(self, report):
        """The initial clean commit should not be identified as a regression."""
        result = subprocess.run(
            ['git', '-C', '/app', 'log', '--reverse', '--format=%H', '-1'],
            capture_output=True, text=True
        )
        first_sha = result.stdout.strip()
        for entry in report:
            assert not first_sha.startswith(entry['commit']), \
                f"Initial commit identified as regression for issue {entry['issue_id']}"


# ===================================================================
# Basic operations
# ===================================================================
class TestBasicOperations:
    def test_empty_map(self):
        m = PersistentMap()
        assert len(m) == 0
        assert 'x' not in m
        with pytest.raises(KeyError):
            m['x']
        assert m.get('x') is None
        assert m.get('x', 42) == 42
        assert list(m) == []
        assert list(m.items()) == []
        assert m.to_dict() == {}

    def test_single_insert_get(self):
        m = PersistentMap().insert('hello', 1)
        assert len(m) == 1
        assert m['hello'] == 1
        assert 'hello' in m
        assert 'world' not in m

    def test_multiple_inserts(self):
        m = PersistentMap()
        for i in range(100):
            m = m.insert(i, i * 10)
        assert len(m) == 100
        for i in range(100):
            assert m[i] == i * 10

    def test_update_existing_key(self):
        m = PersistentMap().insert('a', 1).insert('b', 2).insert('a', 99)
        assert len(m) == 2
        assert m['a'] == 99
        assert m['b'] == 2

    def test_delete(self):
        m = PersistentMap().insert('a', 1).insert('b', 2).insert('c', 3)
        m2 = m.delete('b')
        assert len(m2) == 2
        assert 'a' in m2
        assert 'b' not in m2
        assert 'c' in m2

    def test_delete_nonexistent_raises(self):
        m = PersistentMap().insert('a', 1)
        with pytest.raises(KeyError):
            m.delete('z')

    def test_delete_from_empty_raises(self):
        with pytest.raises(KeyError):
            PersistentMap().delete('x')

    def test_delete_to_empty(self):
        m = PersistentMap().insert('a', 1).delete('a')
        assert len(m) == 0
        assert 'a' not in m
        assert list(m) == []

    def test_iterators(self):
        d = {str(i): i for i in range(50)}
        m = PersistentMap.from_dict(d)
        assert set(m.keys()) == set(d.keys())
        assert sorted(m.values()) == sorted(d.values())
        assert set(m.items()) == set(d.items())

    def test_from_dict_to_dict_roundtrip(self):
        d = {i: i ** 2 for i in range(200)}
        m = PersistentMap.from_dict(d)
        assert m.to_dict() == d
        assert len(m) == 200

    def test_get_default(self):
        m = PersistentMap().insert(1, 'one')
        assert m.get(1) == 'one'
        assert m.get(2) is None
        assert m.get(2, 'fallback') == 'fallback'


# ===================================================================
# Persistence
# ===================================================================
class TestPersistence:
    def test_insert_preserves_old(self):
        m1 = PersistentMap().insert('a', 1)
        m2 = m1.insert('b', 2)
        assert len(m1) == 1
        assert 'b' not in m1
        assert len(m2) == 2
        assert m2['a'] == 1
        assert m2['b'] == 2

    def test_delete_preserves_old(self):
        m1 = PersistentMap().insert('a', 1).insert('b', 2)
        m2 = m1.delete('a')
        assert len(m1) == 2
        assert 'a' in m1
        assert m1['a'] == 1
        assert len(m2) == 1
        assert 'a' not in m2

    def test_update_preserves_old_value(self):
        m1 = PersistentMap().insert('a', 1)
        m2 = m1.insert('a', 99)
        assert m1['a'] == 1
        assert m2['a'] == 99

    def test_many_versions(self):
        versions = [PersistentMap()]
        for i in range(50):
            versions.append(versions[-1].insert(i, i))
        for idx, v in enumerate(versions):
            assert len(v) == idx
            for j in range(idx):
                assert v[j] == j


# ===================================================================
# Structural sharing
# ===================================================================
class TestStructuralSharing:
    def test_root_children_shared_after_single_update(self):
        m1 = PersistentMap()
        for i in range(1000):
            m1 = m1.insert(i, i)
        m2 = m1.insert(500, -1)
        r1 = m1._root_node()
        r2 = m2._root_node()
        assert r1 is not r2
        assert r1.data_map == r2.data_map
        assert r1.node_map == r2.node_map
        shared = sum(1 for a, b in zip(r1.array, r2.array) if a is b)
        assert shared >= len(r1.array) - 1

    def test_self_identity_on_noop_insert(self):
        m1 = PersistentMap().insert('a', 1)
        m2 = m1.insert('a', 1)
        assert m1 is m2

    def test_diff_empty_for_same_object(self):
        m = PersistentMap()
        for i in range(500):
            m = m.insert(i, i)
        assert m.diff(m) == set()


# ===================================================================
# Canonical form
# ===================================================================
class TestCanonicalForm:
    def test_different_insertion_order_same_bitmaps(self):
        keys = list(range(200))
        m1 = PersistentMap()
        for k in keys:
            m1 = m1.insert(k, k * 10)

        shuffled = keys.copy()
        random.seed(42)
        random.shuffle(shuffled)
        m2 = PersistentMap()
        for k in shuffled:
            m2 = m2.insert(k, k * 10)

        assert m1.to_dict() == m2.to_dict()
        r1, r2 = m1._root_node(), m2._root_node()
        assert r1.data_map == r2.data_map
        assert r1.node_map == r2.node_map
        assert m1.diff(m2) == set()


# ===================================================================
# Collision handling
# ===================================================================
class TestCollisionHandling:
    def test_full_hash_collision_insert_get(self):
        k1 = CollidingKey('alpha', 0)
        k2 = CollidingKey('beta', 0)
        k3 = CollidingKey('gamma', 0)
        m = PersistentMap().insert(k1, 1).insert(k2, 2).insert(k3, 3)
        assert len(m) == 3
        assert m[k1] == 1
        assert m[k2] == 2
        assert m[k3] == 3

    def test_collision_update(self):
        k1 = CollidingKey('a', 77)
        k2 = CollidingKey('b', 77)
        m = PersistentMap().insert(k1, 1).insert(k2, 2)
        m2 = m.insert(k1, 99)
        assert m[k1] == 1
        assert m2[k1] == 99
        assert m2[k2] == 2
        assert len(m2) == 2

    def test_collision_delete(self):
        k1 = CollidingKey('a', 55)
        k2 = CollidingKey('b', 55)
        k3 = CollidingKey('c', 55)
        m = PersistentMap().insert(k1, 1).insert(k2, 2).insert(k3, 3)
        m2 = m.delete(k2)
        assert len(m2) == 2
        assert m2[k1] == 1
        assert k2 not in m2
        assert m2[k3] == 3

    def test_collision_delete_nonexistent(self):
        k1 = CollidingKey('a', 55)
        k2 = CollidingKey('b', 55)
        k3 = CollidingKey('missing', 55)
        m = PersistentMap().insert(k1, 1).insert(k2, 2)
        with pytest.raises(KeyError):
            m.delete(k3)

    def test_collision_delete_to_compact(self):
        k1 = CollidingKey('a', 42)
        k2 = CollidingKey('b', 42)
        m = PersistentMap().insert(k1, 1).insert(k2, 2)
        m2 = m.delete(k2)
        assert len(m2) == 1
        assert m2[k1] == 1
        root = m2._root_node()
        h = hash(k1) & 0xFFFFFFFF
        bit = 1 << (h & 31)
        assert root.data_map & bit
        assert not (root.node_map & bit)

    def test_partial_collision(self):
        k1 = CollidingKey('x', 0b00000_00001)
        k2 = CollidingKey('y', 0b00001_00001)
        m = PersistentMap().insert(k1, 10).insert(k2, 20)
        assert m[k1] == 10
        assert m[k2] == 20
        assert len(m) == 2

    def test_collision_contains(self):
        k1 = CollidingKey('a', 100)
        k2 = CollidingKey('b', 100)
        k3 = CollidingKey('c', 100)
        m = PersistentMap().insert(k1, 1).insert(k2, 2)
        assert k1 in m
        assert k2 in m
        assert k3 not in m


# ===================================================================
# Diff
# ===================================================================
class TestDiff:
    def test_diff_identical_content_separate_builds(self):
        d = {i: i for i in range(100)}
        m1 = PersistentMap.from_dict(d)
        m2 = PersistentMap.from_dict(d)
        assert m1.diff(m2) == set()

    def test_diff_one_added(self):
        m1 = PersistentMap.from_dict({1: 'a', 2: 'b'})
        m2 = m1.insert(3, 'c')
        assert m1.diff(m2) == {3}

    def test_diff_one_removed(self):
        m1 = PersistentMap.from_dict({1: 'a', 2: 'b', 3: 'c'})
        m2 = m1.delete(2)
        assert m1.diff(m2) == {2}

    def test_diff_one_value_changed(self):
        m1 = PersistentMap.from_dict({1: 'a', 2: 'b'})
        m2 = m1.insert(2, 'z')
        assert m1.diff(m2) == {2}

    def test_diff_multiple_changes(self):
        m1 = PersistentMap()
        for i in range(100):
            m1 = m1.insert(i, i)
        m2 = m1.insert(50, -1).insert(200, 200).delete(99)
        expected = {50, 200, 99}
        assert m1.diff(m2) == expected

    def test_diff_symmetry(self):
        m1 = PersistentMap.from_dict({1: 'a', 2: 'b', 3: 'c'})
        m2 = PersistentMap.from_dict({2: 'x', 3: 'c', 4: 'd'})
        assert m1.diff(m2) == m2.diff(m1)
        expected = {1, 2, 4}
        assert m1.diff(m2) == expected

    def test_diff_completely_disjoint(self):
        m1 = PersistentMap.from_dict({i: i for i in range(50)})
        m2 = PersistentMap.from_dict({i: i for i in range(50, 100)})
        assert m1.diff(m2) == set(range(100))

    def test_diff_empty_maps(self):
        assert PersistentMap().diff(PersistentMap()) == set()

    def test_diff_vs_empty(self):
        m = PersistentMap.from_dict({1: 1, 2: 2})
        assert m.diff(PersistentMap()) == {1, 2}
        assert PersistentMap().diff(m) == {1, 2}

    def test_diff_with_collisions(self):
        k1 = CollidingKey('a', 100)
        k2 = CollidingKey('b', 100)
        k3 = CollidingKey('c', 100)
        m1 = PersistentMap().insert(k1, 1).insert(k2, 2)
        m2 = PersistentMap().insert(k1, 1).insert(k3, 3)
        diff = m1.diff(m2)
        assert k2 in diff
        assert k3 in diff
        assert k1 not in diff

    def test_diff_collision_value_change(self):
        """Value changes within collision buckets must be detected."""
        k1 = CollidingKey('x', 200)
        k2 = CollidingKey('y', 200)
        m1 = PersistentMap().insert(k1, 1).insert(k2, 2)
        m2 = PersistentMap().insert(k1, 99).insert(k2, 2)
        diff = m1.diff(m2)
        assert k1 in diff
        assert k2 not in diff

    def test_diff_inline_vs_subnode(self):
        """Diff must correctly handle one side having inline data where
        the other has a sub-node at the same trie position."""
        m1 = PersistentMap.from_dict({0: 'zero'})
        m2 = PersistentMap.from_dict({0: 'zero', 32: 'thirty-two'})
        diff = m1.diff(m2)
        assert 32 in diff
        assert 0 not in diff

    def test_diff_shared_structure_finds_single_change(self):
        m1 = PersistentMap()
        for i in range(500):
            m1 = m1.insert(i, i)
        m2 = m1.insert(250, -999)
        assert m1.diff(m2) == {250}


# ===================================================================
# Large-scale fuzz vs Python dict
# ===================================================================
class TestLargeScale:
    def test_random_operations_vs_dict(self):
        random.seed(12345)
        m = PersistentMap()
        d = {}
        keys_present = []

        for _ in range(2000):
            op = random.choice(['insert', 'insert', 'insert', 'delete'])
            if op == 'insert' or not keys_present:
                k = random.randint(0, 10000)
                v = random.randint(0, 100000)
                m = m.insert(k, v)
                d[k] = v
                if k not in keys_present:
                    keys_present.append(k)
            else:
                k = random.choice(keys_present)
                if k in d:
                    m = m.delete(k)
                    del d[k]
                    keys_present.remove(k)

        assert len(m) == len(d)
        assert m.to_dict() == d
        for k, v in d.items():
            assert m[k] == v

    def test_large_diff_correctness(self):
        random.seed(9999)
        d1 = {i: random.randint(0, 1000) for i in range(500)}
        d2 = dict(d1)
        changed = set()
        for _ in range(50):
            k = random.randint(0, 499)
            d2[k] = d2[k] + 1
            changed.add(k)
        for i in range(500, 550):
            d2[i] = i
        removed = set()
        for _ in range(25):
            k = random.randint(0, 499)
            if k in d2:
                del d2[k]
                removed.add(k)

        m1 = PersistentMap.from_dict(d1)
        m2 = PersistentMap.from_dict(d2)
        diff = m1.diff(m2)

        expected = set()
        all_keys = set(d1.keys()) | set(d2.keys())
        for k in all_keys:
            if k not in d1 or k not in d2 or d1[k] != d2[k]:
                expected.add(k)

        assert diff == expected


# ===================================================================
# Internal structure verification
# ===================================================================
class TestInternalStructure:
    def test_32_keys_all_inline_at_root(self):
        """In CPython, hash(n)==n for small ints; keys 0-31 each get unique
        5-bit slots at depth 0, so all should be inline data entries."""
        m = PersistentMap()
        for i in range(32):
            m = m.insert(i, i * 10)
        root = m._root_node()
        assert root.data_map == 0xFFFFFFFF
        assert root.node_map == 0
        assert len(root.array) == 32

    def test_33rd_key_creates_subnode(self):
        """Key 32 has hash(32)&31 == 0, colliding with key 0 at depth 0."""
        m = PersistentMap()
        for i in range(33):
            m = m.insert(i, i * 10)
        root = m._root_node()
        assert not (root.data_map & 1)
        assert root.node_map & 1

    def test_delete_compacts_subnode_to_data(self):
        """After inserting keys 1 and 33 (same depth-0 slot), deleting 33
        should compact the sub-node back to an inline entry for key 1."""
        m = PersistentMap().insert(1, 'a').insert(33, 'b')
        root = m._root_node()
        bit = 1 << (hash(1) & 0xFFFFFFFF & 31)
        assert root.node_map & bit

        m2 = m.delete(33)
        root2 = m2._root_node()
        assert root2.data_map & bit
        assert not (root2.node_map & bit)
        assert m2[1] == 'a'


# ===================================================================
# Merge
# ===================================================================
class TestMerge:
    def test_merge_empty_maps(self):
        assert PersistentMap().merge(PersistentMap()).to_dict() == {}

    def test_merge_nonempty_with_empty(self):
        m = PersistentMap.from_dict({1: 'a', 2: 'b'})
        result = m.merge(PersistentMap())
        assert result.to_dict() == {1: 'a', 2: 'b'}

    def test_merge_empty_with_nonempty(self):
        m = PersistentMap.from_dict({1: 'a', 2: 'b'})
        result = PersistentMap().merge(m)
        assert result.to_dict() == {1: 'a', 2: 'b'}
        assert result is m

    def test_merge_disjoint(self):
        m1 = PersistentMap.from_dict({1: 'a', 2: 'b'})
        m2 = PersistentMap.from_dict({3: 'c', 4: 'd'})
        assert m1.merge(m2).to_dict() == {1: 'a', 2: 'b', 3: 'c', 4: 'd'}

    def test_merge_overlap_other_wins(self):
        m1 = PersistentMap.from_dict({1: 'a', 2: 'b', 3: 'c'})
        m2 = PersistentMap.from_dict({2: 'x', 3: 'c', 4: 'd'})
        assert m1.merge(m2).to_dict() == {1: 'a', 2: 'x', 3: 'c', 4: 'd'}

    def test_merge_with_conflict_fn_sum(self):
        m1 = PersistentMap.from_dict({1: 10, 2: 20})
        m2 = PersistentMap.from_dict({1: 100, 3: 30})
        merged = m1.merge(m2, conflict_fn=lambda k, sv, ov: sv + ov)
        assert merged[1] == 110
        assert merged[2] == 20
        assert merged[3] == 30

    def test_merge_conflict_fn_self_wins(self):
        m1 = PersistentMap.from_dict({1: 'self', 2: 'both'})
        m2 = PersistentMap.from_dict({1: 'other', 3: 'only_other'})
        merged = m1.merge(m2, conflict_fn=lambda k, sv, ov: sv)
        assert merged[1] == 'self'
        assert merged[2] == 'both'
        assert merged[3] == 'only_other'

    def test_merge_self_identity(self):
        """Merging a map with itself must return self via identity check."""
        m = PersistentMap.from_dict({i: i for i in range(100)})
        assert m.merge(m) is m

    def test_merge_preserves_persistence(self):
        m1 = PersistentMap.from_dict({1: 'a', 2: 'b'})
        m2 = PersistentMap.from_dict({2: 'x', 3: 'c'})
        merged = m1.merge(m2)
        assert m1.to_dict() == {1: 'a', 2: 'b'}
        assert m2.to_dict() == {2: 'x', 3: 'c'}
        assert merged.to_dict() == {1: 'a', 2: 'x', 3: 'c'}

    def test_merge_shared_ancestry(self):
        """Merge of maps derived from common ancestor produces correct result."""
        base = PersistentMap()
        for i in range(1000):
            base = base.insert(i, i)
        v1 = base.insert(1001, 'v1')
        v2 = base.insert(1002, 'v2')
        merged = v1.merge(v2)
        expected = {i: i for i in range(1000)}
        expected[1001] = 'v1'
        expected[1002] = 'v2'
        assert merged.to_dict() == expected
        assert len(merged) == 1002

    def test_merge_with_collisions(self):
        k1 = CollidingKey('a', 77)
        k2 = CollidingKey('b', 77)
        k3 = CollidingKey('c', 77)
        m1 = PersistentMap().insert(k1, 1).insert(k2, 2)
        m2 = PersistentMap().insert(k2, 20).insert(k3, 3)
        merged = m1.merge(m2)
        assert merged[k1] == 1
        assert merged[k2] == 20  # other wins
        assert merged[k3] == 3
        assert len(merged) == 3

    def test_merge_collision_conflict_fn(self):
        k1 = CollidingKey('x', 200)
        k2 = CollidingKey('y', 200)
        m1 = PersistentMap().insert(k1, 10).insert(k2, 20)
        m2 = PersistentMap().insert(k1, 100).insert(k2, 200)
        merged = m1.merge(m2, conflict_fn=lambda k, sv, ov: sv * ov)
        assert merged[k1] == 1000
        assert merged[k2] == 4000

    def test_merge_data_vs_subnode(self):
        """One side inline data, other side sub-node at same trie position."""
        m1 = PersistentMap.from_dict({0: 'zero'})
        m2 = PersistentMap.from_dict({0: 'zero', 32: 'thirty-two'})
        merged = m1.merge(m2)
        assert merged[0] == 'zero'
        assert merged[32] == 'thirty-two'
        assert len(merged) == 2

    def test_merge_subnode_vs_data(self):
        """Reverse: self has sub-node, other has inline data."""
        m1 = PersistentMap.from_dict({0: 'zero', 32: 'thirty-two'})
        m2 = PersistentMap.from_dict({0: 'zero'})
        merged = m1.merge(m2)
        assert merged[0] == 'zero'
        assert merged[32] == 'thirty-two'
        assert len(merged) == 2

    def test_merge_symmetry_max(self):
        """Symmetric conflict_fn gives same result regardless of merge order."""
        m1 = PersistentMap.from_dict({i: i for i in range(50)})
        m2 = PersistentMap.from_dict({i: i * 10 for i in range(25, 75)})
        fn = lambda k, sv, ov: max(sv, ov)
        merged1 = m1.merge(m2, fn)
        merged2 = m2.merge(m1, fn)
        assert merged1.to_dict() == merged2.to_dict()

    def test_merge_large_scale_vs_dict(self):
        random.seed(54321)
        d1 = {random.randint(0, 1000): random.randint(0, 100) for _ in range(300)}
        d2 = {random.randint(0, 1000): random.randint(0, 100) for _ in range(300)}
        m1 = PersistentMap.from_dict(d1)
        m2 = PersistentMap.from_dict(d2)
        merged = m1.merge(m2)
        expected = dict(d1)
        expected.update(d2)
        assert merged.to_dict() == expected
        assert len(merged) == len(expected)

    def test_merge_identity_fast(self):
        """Self-merge must complete in O(1) via identity check."""
        m = PersistentMap()
        for i in range(5000):
            m = m.insert(i, i)
        t0 = time.monotonic()
        for _ in range(100):
            result = m.merge(m)
        elapsed = time.monotonic() - t0
        assert result.to_dict() == m.to_dict()
        assert elapsed < 0.1, f"Self-merge too slow: {elapsed:.4f}s"

    def test_merge_performance_vs_rebuild(self):
        """Merge with shared ancestry should outperform from_dict rebuild."""
        base = PersistentMap()
        for i in range(3000):
            base = base.insert(i, i)
        v1 = base.insert(3001, 'a').insert(3002, 'b')
        v2 = base.insert(3003, 'c').insert(3004, 'd')

        t0 = time.monotonic()
        for _ in range(20):
            merged = v1.merge(v2)
        merge_time = time.monotonic() - t0

        expected = dict(v1.to_dict())
        expected.update(v2.to_dict())
        t0 = time.monotonic()
        for _ in range(20):
            rebuilt = PersistentMap.from_dict(expected)
        rebuild_time = time.monotonic() - t0

        assert merged.to_dict() == expected
        assert merge_time < rebuild_time, \
            f"Merge ({merge_time:.4f}s) not faster than rebuild ({rebuild_time:.4f}s)"

    def test_merge_len_correct(self):
        """Merged map must report correct len()."""
        m1 = PersistentMap.from_dict({1: 'a', 2: 'b', 3: 'c'})
        m2 = PersistentMap.from_dict({3: 'x', 4: 'd', 5: 'e'})
        merged = m1.merge(m2)
        assert len(merged) == 5
