"""
Tests for AVL tree ordered set implementation.
Verifies formal invariants from the Isabelle/AFP specification
across all layers: core rotations, insert/delete, join, split, set operations.

"""

import sys
sys.path.insert(0, '/app')

import random
from avl import (
    ET, MKT, empty, is_empty, height, ht, set_of,
    avl, is_ord, mkt, mkt_bal_l, mkt_bal_r,
    insert, delete_max, delete_root, delete, is_in,
    join, join_right, join_left, split,
    union, intersection, difference, join2
)


def build_tree(elements):
    """Build an AVL tree by inserting elements one by one."""
    t = empty()
    for x in elements:
        t = insert(x, t)
    return t


def check_invariants(t, label=""):
    """Assert all AVL invariants hold."""
    assert avl(t), f"AVL violated {label}"
    assert is_ord(t), f"Order violated {label}"


# ---------------------------------------------------------------------------
# Layer 1: Core rotation tests
# ---------------------------------------------------------------------------

class TestMktBalDirect:

    def test_mkt_bal_l_lr_case(self):
        """LR double rotation in mkt_bal_l with non-trivial subtrees."""
        l = MKT(10,
                MKT(5, ET(), ET(), 1),
                MKT(20, MKT(15, ET(), ET(), 1), MKT(25, ET(), ET(), 1), 2),
                3)
        r = MKT(35, ET(), ET(), 1)
        result = mkt_bal_l(30, l, r)
        check_invariants(result, "mkt_bal_l LR")
        assert set_of(result) == {5, 10, 15, 20, 25, 30, 35}

    def test_mkt_bal_l_ll_case(self):
        """LL single rotation in mkt_bal_l."""
        l = MKT(10, MKT(5, MKT(2, ET(), ET(), 1), ET(), 2), ET(), 3)
        r = MKT(25, ET(), ET(), 1)
        result = mkt_bal_l(20, l, r)
        check_invariants(result, "mkt_bal_l LL")
        assert set_of(result) == {2, 5, 10, 20, 25}

    def test_mkt_bal_r_rr_case(self):
        """RR single rotation in mkt_bal_r."""
        l = ET()
        r = MKT(15, MKT(10, ET(), ET(), 1), MKT(20, ET(), ET(), 1), 2)
        result = mkt_bal_r(5, l, r)
        check_invariants(result, "mkt_bal_r RR")
        assert set_of(result) == {5, 10, 15, 20}

    def test_mkt_bal_r_rr_nonempty_left(self):
        """RR rotation in mkt_bal_r where l is non-empty.
        Catches l/rl swap: if swapped, l's elements end up on wrong side.
        """
        l = MKT(3, ET(), ET(), 1)
        r = MKT(20, MKT(15, ET(), ET(), 1),
                MKT(30, MKT(25, ET(), ET(), 1), MKT(35, ET(), ET(), 1), 2), 3)
        result = mkt_bal_r(10, l, r)
        check_invariants(result, "mkt_bal_r RR nonempty-l")
        assert set_of(result) == {3, 10, 15, 20, 25, 30, 35}

    def test_mkt_bal_r_rl_case(self):
        """RL double rotation in mkt_bal_r."""
        l = MKT(3, ET(), ET(), 1)
        r = MKT(20,
                MKT(10, MKT(8, ET(), ET(), 1), MKT(12, ET(), ET(), 1), 2),
                MKT(25, ET(), ET(), 1), 3)
        result = mkt_bal_r(5, l, r)
        check_invariants(result, "mkt_bal_r RL")
        assert set_of(result) == {3, 5, 8, 10, 12, 20, 25}

    def test_mkt_bal_no_rotation(self):
        """When balance is within limits, no rotation occurs."""
        l = MKT(5, ET(), ET(), 1)
        r = MKT(15, ET(), ET(), 1)
        result = mkt_bal_l(10, l, r)
        assert result.val == 10
        check_invariants(result)


# ---------------------------------------------------------------------------
# Layer 2: Insert tests
# ---------------------------------------------------------------------------

class TestInsert:

    def test_insert_single(self):
        t = insert(5, empty())
        check_invariants(t)
        assert set_of(t) == {5}

    def test_insert_ascending(self):
        t = empty()
        for x in range(1, 25):
            t = insert(x, t)
            check_invariants(t, f"after inserting {x} ascending")
        assert set_of(t) == set(range(1, 25))

    def test_insert_descending(self):
        t = empty()
        for x in range(25, 0, -1):
            t = insert(x, t)
            check_invariants(t, f"after inserting {x} descending")
        assert set_of(t) == set(range(1, 26))

    def test_insert_lr_rotation(self):
        t = insert(10, empty())
        t = insert(5, t)
        t = insert(7, t)
        check_invariants(t, "after LR rotation")
        assert set_of(t) == {5, 7, 10}

    def test_insert_rl_rotation(self):
        t = insert(5, empty())
        t = insert(10, t)
        t = insert(7, t)
        check_invariants(t, "after RL rotation")
        assert set_of(t) == {5, 7, 10}

    def test_insert_set_correctness(self):
        random.seed(42)
        t = empty()
        expected = set()
        for _ in range(150):
            x = random.randint(1, 500)
            expected.add(x)
            t = insert(x, t)
            assert set_of(t) == expected

    def test_insert_random_large(self):
        random.seed(123)
        t = empty()
        for _ in range(500):
            x = random.randint(1, 10000)
            t = insert(x, t)
            check_invariants(t, "random insertion")

    def test_insert_duplicate(self):
        t = build_tree([3, 1, 5])
        s_before = set_of(t)
        t2 = insert(3, t)
        assert set_of(t2) == s_before
        check_invariants(t2)


# ---------------------------------------------------------------------------
# Layer 3: Delete tests
# ---------------------------------------------------------------------------

class TestDelete:

    def test_delete_leaf(self):
        t = build_tree([5, 3, 7])
        t = delete(3, t)
        check_invariants(t)
        assert set_of(t) == {5, 7}

    def test_delete_root_two_children(self):
        t = build_tree([10, 5, 15, 3, 7, 12, 20])
        t = delete(10, t)
        check_invariants(t, "after deleting root")
        assert 10 not in set_of(t)

    def test_delete_from_left_rebalance(self):
        """Delete from left subtree requiring right rebalance (mkt_bal_r)."""
        t = MKT(10,
                MKT(5, MKT(3, ET(), ET(), 1), ET(), 2),
                MKT(20, MKT(15, ET(), ET(), 1),
                    MKT(25, ET(), MKT(30, ET(), ET(), 1), 2), 3),
                4)
        assert avl(t) and is_ord(t), "precondition"
        result = delete(3, t)
        check_invariants(result, "after deleting from left subtree")
        assert 3 not in set_of(result)

    def test_delete_root_needs_rebalance(self):
        """Delete root where delete_max + mkt_bal_r is needed."""
        t = MKT(20,
                MKT(10, ET(), MKT(15, ET(), ET(), 1), 2),
                MKT(30,
                    MKT(25, MKT(23, ET(), ET(), 1), MKT(27, ET(), ET(), 1), 2),
                    MKT(35, ET(), ET(), 1), 3),
                4)
        assert avl(t) and is_ord(t), "precondition"
        result = delete(20, t)
        check_invariants(result, "after deleting root")
        assert 20 not in set_of(result)
        assert set_of(result) == {10, 15, 23, 25, 27, 30, 35}

    def test_delete_set_correctness(self):
        random.seed(77)
        elements = list(range(1, 51))
        t = build_tree(elements)
        remaining = set(elements)
        random.shuffle(elements)
        for x in elements:
            remaining.discard(x)
            t = delete(x, t)
            assert set_of(t) == remaining, f"set mismatch after deleting {x}"
            check_invariants(t, f"after deleting {x}")

    def test_delete_all_elements(self):
        random.seed(88)
        elements = random.sample(range(1, 300), 150)
        t = build_tree(elements)
        random.shuffle(elements)
        for x in elements:
            t = delete(x, t)
            check_invariants(t, f"after deleting {x}")
        assert is_empty(t)

    def test_delete_nonexistent(self):
        t = build_tree([5, 3, 7])
        s_before = set_of(t)
        t2 = delete(100, t)
        assert set_of(t2) == s_before
        check_invariants(t2)


class TestDeleteMax:

    def test_delete_max_returns_maximum(self):
        t = build_tree([10, 5, 15, 3, 7, 12, 20])
        max_val, remaining = delete_max(t)
        assert max_val == max(set_of(t))
        assert set_of(remaining) == set_of(t) - {max_val}
        check_invariants(remaining)

    def test_delete_max_single(self):
        t = MKT(5, ET(), ET(), 1)
        max_val, remaining = delete_max(t)
        assert max_val == 5
        assert is_empty(remaining)

    def test_delete_max_chain(self):
        t = build_tree([10, 5, 15, 3, 7, 12, 20, 1, 4, 6, 8])
        prev_max = float('inf')
        while not is_empty(t):
            max_val, t = delete_max(t)
            assert max_val < prev_max
            check_invariants(t, f"after deleting max {max_val}")
            prev_max = max_val


# ---------------------------------------------------------------------------
# Layer 4: Join tests
# ---------------------------------------------------------------------------

class TestJoin:

    def test_join_equal_heights(self):
        l = MKT(3, MKT(1, ET(), ET(), 1), MKT(5, ET(), ET(), 1), 2)
        r = MKT(15, MKT(12, ET(), ET(), 1), MKT(20, ET(), ET(), 1), 2)
        result = join(l, 10, r)
        check_invariants(result, "join equal heights")
        assert set_of(result) == {1, 3, 5, 10, 12, 15, 20}

    def test_join_left_much_taller(self):
        """Left tree height 4, right tree height 1. Exercises join_right."""
        l = MKT(8,
                MKT(4, MKT(2, MKT(1, ET(), ET(), 1), MKT(3, ET(), ET(), 1), 2),
                    MKT(6, MKT(5, ET(), ET(), 1), MKT(7, ET(), ET(), 1), 2), 3),
                MKT(12, MKT(10, MKT(9, ET(), ET(), 1), MKT(11, ET(), ET(), 1), 2),
                    MKT(14, MKT(13, ET(), ET(), 1), MKT(15, ET(), ET(), 1), 2), 3),
                4)
        r = MKT(20, ET(), ET(), 1)
        assert avl(l) and is_ord(l), "precondition on l"
        result = join(l, 17, r)
        check_invariants(result, "join left much taller")
        assert set_of(result) == set(range(1, 16)) | {17, 20}

    def test_join_right_much_taller(self):
        """Right tree height 4, left tree height 1. Exercises join_left."""
        l = MKT(2, ET(), ET(), 1)
        r = MKT(12,
                MKT(8, MKT(6, MKT(5, ET(), ET(), 1), MKT(7, ET(), ET(), 1), 2),
                    MKT(10, MKT(9, ET(), ET(), 1), MKT(11, ET(), ET(), 1), 2), 3),
                MKT(16, MKT(14, MKT(13, ET(), ET(), 1), MKT(15, ET(), ET(), 1), 2),
                    MKT(18, MKT(17, ET(), ET(), 1), MKT(19, ET(), ET(), 1), 2), 3),
                4)
        assert avl(r) and is_ord(r), "precondition on r"
        result = join(l, 4, r)
        check_invariants(result, "join right much taller")
        assert set_of(result) == {2, 4} | set(range(5, 20))

    def test_join_empty_trees(self):
        result = join(ET(), 5, ET())
        check_invariants(result)
        assert set_of(result) == {5}

    def test_join_left_empty(self):
        r = MKT(10, MKT(8, ET(), ET(), 1), MKT(12, ET(), ET(), 1), 2)
        result = join(ET(), 5, r)
        check_invariants(result, "join left empty")
        assert set_of(result) == {5, 8, 10, 12}

    def test_join_right_empty(self):
        l = MKT(3, MKT(1, ET(), ET(), 1), MKT(5, ET(), ET(), 1), 2)
        result = join(l, 10, ET())
        check_invariants(result, "join right empty")
        assert set_of(result) == {1, 3, 5, 10}

    def test_join_height_diff_2(self):
        """Height difference exactly 2 — border case for join dispatch."""
        l = MKT(3, MKT(1, ET(), ET(), 1), MKT(5, ET(), ET(), 1), 2)
        r = MKT(20,
                MKT(15, MKT(12, ET(), ET(), 1), MKT(17, ET(), ET(), 1), 2),
                MKT(25, MKT(22, ET(), ET(), 1), MKT(30, ET(), ET(), 1), 2),
                3)
        # ht(l) = 2, ht(r) = 3, diff = 1 → no dispatch, but let's try with diff=2
        r2 = MKT(20,
                 MKT(15, MKT(12, MKT(11, ET(), ET(), 1), MKT(13, ET(), ET(), 1), 2),
                     MKT(17, ET(), ET(), 1), 3),
                 MKT(25, MKT(22, ET(), ET(), 1), MKT(30, ET(), ET(), 1), 2),
                 4)
        assert avl(r2) and is_ord(r2)
        result = join(l, 10, r2)
        check_invariants(result, "join height diff 2")
        assert 10 in set_of(result)


class TestJoinRight:

    def test_join_right_basic(self):
        """Direct test of join_right."""
        l = MKT(5,
                MKT(3, MKT(1, ET(), ET(), 1), MKT(4, ET(), ET(), 1), 2),
                MKT(7, MKT(6, ET(), ET(), 1), MKT(8, ET(), ET(), 1), 2),
                3)
        r = MKT(15, ET(), ET(), 1)
        result = join_right(l, 10, r)
        check_invariants(result, "join_right basic")
        assert set_of(result) == {1, 3, 4, 5, 6, 7, 8, 10, 15}

    def test_join_right_asymmetric(self):
        """join_right with asymmetric tree where ll.height < lr.height.
        This triggers the rebalancing path where mkt_bal_r is needed.
        """
        l = MKT(10,
                MKT(5, ET(), ET(), 1),
                MKT(20, MKT(15, ET(), ET(), 1), MKT(25, ET(), ET(), 1), 2),
                3)
        r = MKT(35, ET(), ET(), 1)
        result = join_right(l, 30, r)
        check_invariants(result, "join_right asymmetric")
        assert set_of(result) == {5, 10, 15, 20, 25, 30, 35}

    def test_join_right_preserves_set(self):
        """join_right must preserve all elements."""
        l = build_tree(range(1, 20))
        r = MKT(25, ET(), ET(), 1)
        if avl(l):
            result = join_right(l, 22, r)
            check_invariants(result, "join_right preserves set")
            assert set_of(result) == set(range(1, 20)) | {22, 25}


class TestJoinLeft:

    def test_join_left_basic(self):
        """Direct test of join_left."""
        l = MKT(2, ET(), ET(), 1)
        r = MKT(10,
                MKT(7, MKT(6, ET(), ET(), 1), MKT(8, ET(), ET(), 1), 2),
                MKT(14, MKT(12, ET(), ET(), 1), MKT(16, ET(), ET(), 1), 2),
                3)
        result = join_left(l, 4, r)
        check_invariants(result, "join_left basic")
        assert set_of(result) == {2, 4, 6, 7, 8, 10, 12, 14, 16}

    def test_join_left_deep(self):
        """join_left with height difference of 3."""
        l = MKT(2, ET(), ET(), 1)
        r = MKT(12,
                MKT(8, MKT(6, MKT(5, ET(), ET(), 1), MKT(7, ET(), ET(), 1), 2),
                    MKT(10, MKT(9, ET(), ET(), 1), MKT(11, ET(), ET(), 1), 2), 3),
                MKT(16, MKT(14, MKT(13, ET(), ET(), 1), MKT(15, ET(), ET(), 1), 2),
                    MKT(18, MKT(17, ET(), ET(), 1), MKT(19, ET(), ET(), 1), 2), 3),
                4)
        assert avl(r) and is_ord(r)
        result = join_left(l, 4, r)
        check_invariants(result, "join_left deep")
        assert set_of(result) == {2, 4} | set(range(5, 20))


# ---------------------------------------------------------------------------
# Layer 5: Split tests
# ---------------------------------------------------------------------------

class TestSplit:

    def test_split_at_existing(self):
        """Split at an element that exists in the tree."""
        t = MKT(15, MKT(10, MKT(5, ET(), ET(), 1), MKT(12, ET(), ET(), 1), 2),
                MKT(25, MKT(20, ET(), ET(), 1), MKT(30, ET(), ET(), 1), 2), 3)
        left, present, right = split(15, t)
        assert present is True
        assert set_of(left) == {5, 10, 12}
        assert set_of(right) == {20, 25, 30}
        check_invariants(left, "split-left at existing")
        check_invariants(right, "split-right at existing")

    def test_split_at_nonexisting(self):
        """Split at an element not in the tree."""
        t = MKT(15, MKT(10, MKT(5, ET(), ET(), 1), MKT(12, ET(), ET(), 1), 2),
                MKT(25, MKT(20, ET(), ET(), 1), MKT(30, ET(), ET(), 1), 2), 3)
        left, present, right = split(17, t)
        assert present is False
        assert set_of(left) == {5, 10, 12, 15}
        assert set_of(right) == {20, 25, 30}
        check_invariants(left, "split-left at nonexisting")
        check_invariants(right, "split-right at nonexisting")

    def test_split_at_min(self):
        """Split at minimum element."""
        t = MKT(10, MKT(5, MKT(3, ET(), ET(), 1), ET(), 2),
                MKT(15, ET(), ET(), 1), 3)
        left, present, right = split(3, t)
        assert present is True
        assert set_of(left) == set()
        assert set_of(right) == {5, 10, 15}

    def test_split_at_max(self):
        """Split at maximum element."""
        t = MKT(10, MKT(5, ET(), ET(), 1),
                MKT(15, ET(), MKT(20, ET(), ET(), 1), 2), 3)
        left, present, right = split(20, t)
        assert present is True
        assert set_of(left) == {5, 10, 15}
        assert set_of(right) == set()

    def test_split_empty(self):
        left, present, right = split(5, ET())
        assert present is False
        assert is_empty(left)
        assert is_empty(right)

    def test_split_set_semantics_comprehensive(self):
        """Verify split set semantics on a larger tree."""
        t = build_tree([20, 10, 30, 5, 15, 25, 35, 3, 7, 12, 18, 22, 28, 32, 40])
        all_elems = set_of(t)

        for x in [1, 5, 14, 15, 20, 25, 35, 41]:
            left, present, right = split(x, t)
            expected_left = {e for e in all_elems if e < x}
            expected_right = {e for e in all_elems if e > x}
            assert set_of(left) == expected_left, \
                f"split({x}) left: {set_of(left)} != {expected_left}"
            assert set_of(right) == expected_right, \
                f"split({x}) right: {set_of(right)} != {expected_right}"
            assert present == (x in all_elems), \
                f"split({x}) present: {present} != {x in all_elems}"
            check_invariants(left, f"split({x}) left")
            check_invariants(right, f"split({x}) right")


# ---------------------------------------------------------------------------
# Layer 6: Set operations tests
# ---------------------------------------------------------------------------

class TestUnion:

    def test_union_disjoint(self):
        t1 = build_tree([1, 3, 5, 7])
        t2 = build_tree([2, 4, 6, 8])
        result = union(t1, t2)
        check_invariants(result, "union disjoint")
        assert set_of(result) == {1, 2, 3, 4, 5, 6, 7, 8}

    def test_union_overlapping(self):
        t1 = build_tree([1, 2, 3, 4, 5])
        t2 = build_tree([3, 4, 5, 6, 7])
        result = union(t1, t2)
        check_invariants(result, "union overlapping")
        assert set_of(result) == {1, 2, 3, 4, 5, 6, 7}

    def test_union_identical(self):
        t1 = build_tree([1, 2, 3])
        t2 = build_tree([1, 2, 3])
        result = union(t1, t2)
        check_invariants(result, "union identical")
        assert set_of(result) == {1, 2, 3}

    def test_union_with_empty(self):
        t1 = build_tree([1, 2, 3])
        result1 = union(t1, ET())
        assert set_of(result1) == {1, 2, 3}
        result2 = union(ET(), t1)
        assert set_of(result2) == {1, 2, 3}

    def test_union_set_semantics(self):
        random.seed(200)
        for _ in range(10):
            s1 = set(random.sample(range(1, 100), 20))
            s2 = set(random.sample(range(1, 100), 20))
            t1 = build_tree(s1)
            t2 = build_tree(s2)
            result = union(t1, t2)
            check_invariants(result, "union random")
            assert set_of(result) == s1 | s2


class TestIntersection:

    def test_intersection_overlapping(self):
        t1 = build_tree([1, 2, 3, 4, 5])
        t2 = build_tree([3, 4, 5, 6, 7])
        result = intersection(t1, t2)
        check_invariants(result, "intersection overlapping")
        assert set_of(result) == {3, 4, 5}

    def test_intersection_disjoint(self):
        t1 = build_tree([1, 2, 3])
        t2 = build_tree([4, 5, 6])
        result = intersection(t1, t2)
        assert set_of(result) == set()

    def test_intersection_subset(self):
        t1 = build_tree([1, 2, 3, 4, 5])
        t2 = build_tree([2, 4])
        result = intersection(t1, t2)
        check_invariants(result, "intersection subset")
        assert set_of(result) == {2, 4}

    def test_intersection_identical(self):
        t1 = build_tree([1, 2, 3, 4, 5])
        t2 = build_tree([1, 2, 3, 4, 5])
        result = intersection(t1, t2)
        check_invariants(result, "intersection identical")
        assert set_of(result) == {1, 2, 3, 4, 5}

    def test_intersection_set_semantics(self):
        random.seed(300)
        for _ in range(10):
            s1 = set(random.sample(range(1, 100), 25))
            s2 = set(random.sample(range(1, 100), 25))
            t1 = build_tree(s1)
            t2 = build_tree(s2)
            result = intersection(t1, t2)
            check_invariants(result, "intersection random")
            assert set_of(result) == s1 & s2, \
                f"Expected {s1 & s2}, got {set_of(result)}"


class TestDifference:

    def test_difference_overlapping(self):
        t1 = build_tree([1, 2, 3, 4, 5])
        t2 = build_tree([3, 4, 5, 6, 7])
        result = difference(t1, t2)
        check_invariants(result, "difference overlapping")
        assert set_of(result) == {1, 2}

    def test_difference_disjoint(self):
        t1 = build_tree([1, 2, 3])
        t2 = build_tree([4, 5, 6])
        result = difference(t1, t2)
        check_invariants(result, "difference disjoint")
        assert set_of(result) == {1, 2, 3}

    def test_difference_identical(self):
        t1 = build_tree([1, 2, 3])
        t2 = build_tree([1, 2, 3])
        result = difference(t1, t2)
        assert set_of(result) == set()

    def test_difference_with_empty(self):
        t1 = build_tree([1, 2, 3])
        result1 = difference(t1, ET())
        assert set_of(result1) == {1, 2, 3}
        result2 = difference(ET(), t1)
        assert set_of(result2) == set()

    def test_difference_set_semantics(self):
        random.seed(400)
        for _ in range(10):
            s1 = set(random.sample(range(1, 100), 25))
            s2 = set(random.sample(range(1, 100), 25))
            t1 = build_tree(s1)
            t2 = build_tree(s2)
            result = difference(t1, t2)
            check_invariants(result, "difference random")
            assert set_of(result) == s1 - s2


# ---------------------------------------------------------------------------
# Stress tests combining all layers
# ---------------------------------------------------------------------------

class TestStress:

    def test_interleaved_insert_delete(self):
        """Interleave insertions and deletions, checking invariants."""
        random.seed(2024)
        t = empty()
        elements = set()
        for _ in range(500):
            if random.random() < 0.6 or not elements:
                x = random.randint(1, 300)
                elements.add(x)
                t = insert(x, t)
            else:
                x = random.choice(list(elements))
                elements.discard(x)
                t = delete(x, t)
            check_invariants(t, "interleaved ops")
            assert set_of(t) == elements

    def test_split_join_roundtrip(self):
        """split then join should reconstitute the original set."""
        random.seed(500)
        elements = random.sample(range(1, 200), 50)
        t = build_tree(elements)
        all_elems = set(elements)

        for x in random.sample(range(1, 200), 30):
            left, present, right = split(x, t)
            if present:
                reconstituted = join(left, x, right)
            else:
                reconstituted = join2(left, right)
            check_invariants(reconstituted, f"roundtrip split({x})")
            assert set_of(reconstituted) == all_elems, \
                f"Roundtrip failed for split({x})"

    def test_set_ops_algebraic_identities(self):
        """Verify algebraic identities: union commutativity, De Morgan's laws."""
        random.seed(600)
        s1 = set(random.sample(range(1, 80), 30))
        s2 = set(random.sample(range(1, 80), 30))
        t1 = build_tree(s1)
        t2 = build_tree(s2)

        # union commutativity
        u12 = union(t1, t2)
        u21 = union(t2, t1)
        assert set_of(u12) == set_of(u21), "Union not commutative"

        # intersection subset of both operands
        inter = intersection(t1, t2)
        assert set_of(inter) <= s1 and set_of(inter) <= s2

        # difference + intersection = original
        diff = difference(t1, t2)
        assert set_of(diff) | set_of(inter) == s1

        # union = t1 + (t2 - t1)
        diff2 = difference(t2, t1)
        assert set_of(u12) == s1 | set_of(diff2)

    def test_height_caching_through_all_ops(self):
        """Verify cached heights match actual heights through operations."""
        random.seed(700)
        t = build_tree(range(1, 50))
        if not is_empty(t):
            assert ht(t) == height(t)

        for x in random.sample(range(1, 50), 20):
            t = delete(x, t)
            if not is_empty(t):
                assert ht(t) == height(t), f"Height mismatch after deleting {x}"

    def test_large_union_intersection(self):
        """Large-scale union and intersection stress test."""
        random.seed(800)
        s1 = set(random.sample(range(1, 500), 100))
        s2 = set(random.sample(range(1, 500), 100))
        t1 = build_tree(s1)
        t2 = build_tree(s2)

        u = union(t1, t2)
        check_invariants(u, "large union")
        assert set_of(u) == s1 | s2

        i = intersection(t1, t2)
        check_invariants(i, "large intersection")
        assert set_of(i) == s1 & s2

        d = difference(t1, t2)
        check_invariants(d, "large difference")
        assert set_of(d) == s1 - s2
