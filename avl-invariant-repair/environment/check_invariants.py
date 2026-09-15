#!/usr/bin/env python3
"""
Quick invariant checker for AVL tree implementation.
Tests core operations and split/join/set-operations layer by layer.
Usage: python3 /app/check_invariants.py
"""


import sys
import random
sys.path.insert(0, '/app')

from avl import (
    ET, MKT, empty, is_empty, height, ht, set_of,
    avl, is_ord, mkt, mkt_bal_l, mkt_bal_r,
    insert, delete_max, delete_root, delete, is_in,
    join, join_right, join_left, split,
    union, intersection, difference, join2
)


def build_tree(elements):
    t = empty()
    for x in elements:
        t = insert(x, t)
    return t


def run_checks():
    errors = []

    # --- Layer 1: Core rotations ---

    print("Check 1: Ascending insertion (right-heavy rebalancing)...", end=" ")
    try:
        t = empty()
        for i in range(1, 30):
            t = insert(i, t)
            if not avl(t):
                errors.append(f"AVL violated inserting {i} ascending"); break
            if not is_ord(t):
                errors.append(f"Ordering violated inserting {i} ascending"); break
        else:
            print("OK")
    except Exception as e:
        errors.append(f"Exception: {e}")

    print("Check 2: Descending insertion (left-heavy rebalancing)...", end=" ")
    try:
        t = empty()
        for i in range(30, 0, -1):
            t = insert(i, t)
            if not avl(t):
                errors.append(f"AVL violated inserting {i} descending"); break
            if not is_ord(t):
                errors.append(f"Ordering violated inserting {i} descending"); break
        else:
            print("OK")
    except Exception as e:
        errors.append(f"Exception: {e}")

    print("Check 3: mkt_bal_l LR double rotation...", end=" ")
    try:
        l = MKT(10, MKT(5, ET(), ET(), 1),
                MKT(20, MKT(15, ET(), ET(), 1), MKT(25, ET(), ET(), 1), 2), 3)
        r = MKT(35, ET(), ET(), 1)
        result = mkt_bal_l(30, l, r)
        if not avl(result):
            errors.append("AVL violated in mkt_bal_l LR")
        elif not is_ord(result):
            errors.append("Ordering violated in mkt_bal_l LR")
        else:
            print("OK")
    except Exception as e:
        errors.append(f"Exception: {e}")

    print("Check 4: mkt_bal_r RR single rotation...", end=" ")
    try:
        l = MKT(3, ET(), ET(), 1)
        r = MKT(20, MKT(15, ET(), ET(), 1),
                MKT(30, MKT(25, ET(), ET(), 1), MKT(35, ET(), ET(), 1), 2), 3)
        result = mkt_bal_r(10, l, r)
        if not avl(result):
            errors.append("AVL violated in mkt_bal_r RR")
        elif not is_ord(result):
            errors.append("Ordering violated in mkt_bal_r RR")
        else:
            print("OK")
    except Exception as e:
        errors.append(f"Exception: {e}")

    # --- Layer 2: Delete operations ---

    print("Check 5: Delete from left subtree (rebalance direction)...", end=" ")
    try:
        t = MKT(10,
            MKT(5, MKT(3, ET(), ET(), 1), ET(), 2),
            MKT(20, MKT(15, ET(), ET(), 1),
                MKT(25, ET(), MKT(30, ET(), ET(), 1), 2), 3), 4)
        result = delete(3, t)
        if not avl(result):
            errors.append("AVL violated after delete-from-left")
        elif not is_ord(result):
            errors.append("Ordering violated after delete-from-left")
        else:
            print("OK")
    except Exception as e:
        errors.append(f"Exception: {e}")

    print("Check 6: Delete root with both children (rebalance)...", end=" ")
    try:
        t = MKT(20,
            MKT(10, ET(), MKT(15, ET(), ET(), 1), 2),
            MKT(30,
                MKT(25, MKT(23, ET(), ET(), 1), MKT(27, ET(), ET(), 1), 2),
                MKT(35, ET(), ET(), 1), 3), 4)
        result = delete(20, t)
        if not avl(result):
            errors.append("AVL violated after delete-root")
        elif not is_ord(result):
            errors.append("Ordering violated after delete-root")
        else:
            print("OK")
    except Exception as e:
        errors.append(f"Exception: {e}")

    # --- Layer 3: Join operations ---

    print("Check 7: join_right (asymmetric left tree)...", end=" ")
    try:
        # Asymmetric: ll.height=1, lr.height=2 — triggers rebalancing in join_right
        l = MKT(10,
                MKT(5, ET(), ET(), 1),
                MKT(20, MKT(15, ET(), ET(), 1), MKT(25, ET(), ET(), 1), 2),
                3)
        r = MKT(35, ET(), ET(), 1)
        result = join_right(l, 30, r)
        if not avl(result):
            errors.append("AVL violated in join_right")
        elif not is_ord(result):
            errors.append("Ordering violated in join_right")
        elif set_of(result) != {5, 10, 15, 20, 25, 30, 35}:
            errors.append(f"Set mismatch in join_right: {set_of(result)}")
        else:
            print("OK")
    except Exception as e:
        errors.append(f"Exception: {e}")

    print("Check 8: join_left (right tree much taller)...", end=" ")
    try:
        l = MKT(2, ET(), ET(), 1)
        r = MKT(12, MKT(8, MKT(6, MKT(5, ET(), ET(), 1), MKT(7, ET(), ET(), 1), 2),
                MKT(10, MKT(9, ET(), ET(), 1), MKT(11, ET(), ET(), 1), 2), 3),
                MKT(16, MKT(14, MKT(13, ET(), ET(), 1), MKT(15, ET(), ET(), 1), 2),
                MKT(18, MKT(17, ET(), ET(), 1), MKT(19, ET(), ET(), 1), 2), 3), 4)
        result = join_left(l, 4, r)
        if not avl(result):
            errors.append("AVL violated in join_left")
        elif not is_ord(result):
            errors.append("Ordering violated in join_left")
        else:
            print("OK")
    except Exception as e:
        errors.append(f"Exception: {e}")

    # --- Layer 4: Split ---

    print("Check 9: split set semantics...", end=" ")
    try:
        # Use manually constructed valid tree to avoid depending on insert correctness
        t = MKT(15, MKT(10, MKT(5, ET(), ET(), 1), MKT(12, ET(), ET(), 1), 2),
                MKT(25, MKT(20, ET(), ET(), 1), MKT(30, ET(), ET(), 1), 2), 3)
        left, present, right = split(17, t)
        expected_left = {5, 10, 12, 15}
        expected_right = {20, 25, 30}
        if set_of(left) != expected_left:
            errors.append(f"Split left mismatch: {set_of(left)} != {expected_left}")
        elif set_of(right) != expected_right:
            errors.append(f"Split right mismatch: {set_of(right)} != {expected_right}")
        elif present:
            errors.append("Split present should be False for 17")
        elif not avl(left) or not avl(right):
            errors.append("AVL violated in split results")
        else:
            print("OK")
    except Exception as e:
        errors.append(f"Exception: {e}")

    # --- Layer 5: Set operations ---

    print("Check 10: union...", end=" ")
    try:
        t1 = MKT(3, MKT(1, ET(), ET(), 1), MKT(5, ET(), ET(), 1), 2)
        t2 = MKT(4, MKT(2, ET(), ET(), 1), MKT(6, ET(), ET(), 1), 2)
        result = union(t1, t2)
        if not avl(result):
            errors.append("AVL violated in union")
        elif set_of(result) != {1, 2, 3, 4, 5, 6}:
            errors.append(f"Union set mismatch: {set_of(result)}")
        else:
            print("OK")
    except Exception as e:
        errors.append(f"Exception: {e}")

    print("Check 11: intersection...", end=" ")
    try:
        t1 = MKT(3, MKT(1, ET(), ET(), 1), MKT(5, MKT(4, ET(), ET(), 1), ET(), 2), 3)
        t2 = MKT(4, MKT(3, ET(), ET(), 1), MKT(6, ET(), ET(), 1), 2)
        result = intersection(t1, t2)
        if set_of(result) != {3, 4}:
            errors.append(f"Intersection set mismatch: {set_of(result)}, expected {{3, 4}}")
        elif not avl(result):
            errors.append("AVL violated in intersection")
        else:
            print("OK")
    except Exception as e:
        errors.append(f"Exception: {e}")

    print("Check 12: difference...", end=" ")
    try:
        t1 = MKT(3, MKT(1, ET(), ET(), 1), MKT(5, MKT(4, ET(), ET(), 1), ET(), 2), 3)
        t2 = MKT(4, MKT(3, ET(), ET(), 1), MKT(6, ET(), ET(), 1), 2)
        result = difference(t1, t2)
        if set_of(result) != {1, 5}:
            errors.append(f"Difference set mismatch: {set_of(result)}, expected {{1, 5}}")
        elif not avl(result):
            errors.append("AVL violated in difference")
        else:
            print("OK")
    except Exception as e:
        errors.append(f"Exception: {e}")

    print()
    if errors:
        print(f"FAILED: {len(errors)} check(s) failed:")
        for e in errors:
            print(f"  - {e}")
        return False
    else:
        print("ALL CHECKS PASSED")
        return True


if __name__ == '__main__':
    success = run_checks()
    sys.exit(0 if success else 1)
