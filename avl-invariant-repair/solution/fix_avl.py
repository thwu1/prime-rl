#!/usr/bin/env python3
"""
Fix all bugs in /app/avl.py and implement the missing join_left function.
Corrections derived from comparing with the Isabelle specification (reference_spec.thy).

Bugs identified through specification comparison:

1. mkt_bal_l LR case: lrl and lrr are swapped
   Spec: mkt lrn (mkt ln ll lrl) (mkt n lrr r)
   Bug:  mkt(lrn, mkt(ln, ll, lrr), mkt(n, lrl, r))

2. mkt_bal_r RR case: l and rl are swapped
   Spec: mkt rn (mkt n l rl) rr
   Bug:  mkt(rn, mkt(n, rl, l), rr)

3. delete x < n: uses mkt_bal_l instead of mkt_bal_r
   Spec: mkt_bal_r n l' r (left shrank, right may be too tall)
   Bug:  mkt_bal_l(t.val, l_prime, t.right)

4. delete_root both-children: uses mkt instead of mkt_bal_r
   Spec: mkt_bal_r new_n l' r (left shrank via delete_max)
   Bug:  mkt(new_n, l_prime, t.right)

5. split x > n: uses r1 instead of l1 in join call
   Spec: (join l n l1, p, r1) where (l1, p, r1) = split x r
   Bug:  (join(t.left, n, r1), present, r1)

6. join_right: uses mkt_bal_l instead of mkt_bal_r
   Spec: mkt_bal_r ln ll new_r (right child may be too tall after join)
   Bug:  mkt_bal_l(ln, ll, new_r)

7. join_left: not implemented (just returns mkt(n, l, r) without rebalancing)
   Must walk down r's left spine using mkt_bal_l for rebalancing.

8. intersection: inverted present check
   Spec: if p then join l_i n2 r_i else join2 l_i r_i
   Bug:  if not present: join(l_int, n2, r_int) else: join2(l_int, r_int)
"""


CORRECT_AVL = r'''"""
AVL Tree-based Ordered Set implementation.
Based on the Isabelle/AFP (Archive of Formal Proofs) formalization.
See reference_spec.thy for the formal specification.

Provides:
- AVL tree data structure with cached heights
- Insert/delete operations with automatic rebalancing
- Split and join primitives for efficient tree operations
- Set operations: union, intersection, difference
- Invariant checking: avl (balance), is_ord (BST ordering)
- Set semantics: set_of, is_in
"""



class ET:
    """Empty tree, corresponding to Isabelle's ET constructor."""
    def __repr__(self):
        return "ET"


class MKT:
    """Non-empty tree node: MKT(value, left, right, cached_height).
    Corresponds to Isabelle's MKT constructor.
    """
    def __init__(self, val, left, right, h):
        self.val = val
        self.left = left
        self.right = right
        self.h = h

    def __repr__(self):
        return f"MKT({self.val}, {self.left}, {self.right}, {self.h})"


def empty():
    """Create an empty tree."""
    return ET()


def is_empty(t):
    """Check if tree is empty."""
    return isinstance(t, ET)


def height(t):
    """Compute actual height (recursive, not cached)."""
    if is_empty(t):
        return 0
    return max(height(t.left), height(t.right)) + 1


def ht(t):
    """Get cached height from node."""
    if is_empty(t):
        return 0
    return t.h


def set_of(t):
    """Get the set of all elements in the tree."""
    if is_empty(t):
        return set()
    return {t.val} | set_of(t.left) | set_of(t.right)


def avl(t):
    """Check AVL balance invariant: |height(l) - height(r)| <= 1,
    cached height is correct, and recursively holds."""
    if is_empty(t):
        return True
    hl = height(t.left)
    hr = height(t.right)
    return (abs(hl - hr) <= 1 and
            t.h == max(hl, hr) + 1 and
            avl(t.left) and avl(t.right))


def is_ord(t):
    """Check BST ordering invariant: all left < root < all right."""
    if is_empty(t):
        return True
    return (all(x < t.val for x in set_of(t.left)) and
            all(t.val < x for x in set_of(t.right)) and
            is_ord(t.left) and is_ord(t.right))


# ---- Core tree construction ----

def mkt(x, l, r):
    """Create node with correct cached height (no rebalancing).
    Corresponds to Isabelle's mkt definition.
    """
    return MKT(x, l, r, max(ht(l), ht(r)) + 1)


def mkt_bal_l(n, l, r):
    """Rebalance when left subtree may be too tall (by at most 1).
    Handles LL and LR rotation cases.
    See reference_spec.thy: mkt_bal_l definition.
    """
    if ht(l) == ht(r) + 2:
        ln = l.val
        ll = l.left
        lr = l.right
        if ht(ll) < ht(lr):
            # LR case: double rotation
            lrn = lr.val
            lrl = lr.left
            lrr = lr.right
            return mkt(lrn, mkt(ln, ll, lrl), mkt(n, lrr, r))
        else:
            # LL case: single rotation
            return mkt(ln, ll, mkt(n, lr, r))
    else:
        return mkt(n, l, r)


def mkt_bal_r(n, l, r):
    """Rebalance when right subtree may be too tall (by at most 1).
    Handles RR and RL rotation cases.
    See reference_spec.thy: mkt_bal_r definition.
    """
    if ht(r) == ht(l) + 2:
        rn = r.val
        rl = r.left
        rr = r.right
        if ht(rl) > ht(rr):
            # RL case: double rotation
            rln = rl.val
            rll = rl.left
            rlr = rl.right
            return mkt(rln, mkt(n, l, rll), mkt(rn, rlr, rr))
        else:
            # RR case: single rotation
            return mkt(rn, mkt(n, l, rl), rr)
    else:
        return mkt(n, l, r)


# ---- Insert/delete operations ----

def insert(x, t):
    """Insert element x into the AVL tree.
    Corresponds to Isabelle's insert function.
    """
    if is_empty(t):
        return MKT(x, ET(), ET(), 1)
    if x == t.val:
        return MKT(t.val, t.left, t.right, t.h)
    elif x < t.val:
        return mkt_bal_l(t.val, insert(x, t.left), t.right)
    else:
        return mkt_bal_r(t.val, t.left, insert(x, t.right))


def delete_max(t):
    """Remove and return the maximum element from a non-empty tree.
    Returns (max_value, remaining_tree).
    Corresponds to Isabelle's delete_max function.
    """
    if is_empty(t.right):
        return (t.val, t.left)
    else:
        n_prime, r_prime = delete_max(t.right)
        return (n_prime, mkt_bal_l(t.val, t.left, r_prime))


def delete_root(t):
    """Delete root element of a non-empty tree.
    When both children exist, uses delete_max on left subtree
    to find the in-order predecessor.
    Corresponds to Isabelle's delete_root function.
    """
    if is_empty(t.left):
        return t.right
    elif is_empty(t.right):
        return t.left
    else:
        new_n, l_prime = delete_max(t.left)
        return mkt_bal_r(new_n, l_prime, t.right)


def delete(x, t):
    """Delete element x from the AVL tree.
    Corresponds to Isabelle's delete function.
    """
    if is_empty(t):
        return ET()
    if x == t.val:
        return delete_root(t)
    elif x < t.val:
        l_prime = delete(x, t.left)
        return mkt_bal_r(t.val, l_prime, t.right)
    else:
        r_prime = delete(x, t.right)
        return mkt_bal_l(t.val, t.left, r_prime)


def is_in(k, t):
    """Check if element k is in the tree.
    Corresponds to Isabelle's is_in function.
    """
    if is_empty(t):
        return False
    if k == t.val:
        return True
    elif k < t.val:
        return is_in(k, t.left)
    else:
        return is_in(k, t.right)


# ---- Join operations ----

def join(l, n, r):
    """Create balanced AVL tree from (l, n, r) where set_of(l) < {n} < set_of(r).
    Dispatches to join_right or join_left depending on relative heights.
    See reference_spec.thy: join definition.
    """
    if ht(l) > ht(r) + 1:
        return join_right(l, n, r)
    elif ht(r) > ht(l) + 1:
        return join_left(l, n, r)
    else:
        return mkt(n, l, r)


def join_right(l, n, r):
    """Join when l is significantly taller. Walk down l's right spine
    until finding a subtree with height compatible with r, then rebuild
    upward with rebalancing.
    See reference_spec.thy: join_right definition.
    """
    if ht(l) <= ht(r) + 1:
        return mkt(n, l, r)
    ln, ll, lr = l.val, l.left, l.right
    new_r = join_right(lr, n, r)
    return mkt_bal_r(ln, ll, new_r)


def join_left(l, n, r):
    """Join when r is significantly taller. Walk down r's left spine
    until finding a subtree with height compatible with l.
    See join_right for the symmetric case and reference_spec.thy for specification.
    """
    if ht(r) <= ht(l) + 1:
        return mkt(n, l, r)
    rn, rl, rr = r.val, r.left, r.right
    new_l = join_left(l, n, rl)
    return mkt_bal_l(rn, new_l, rr)


# ---- Split operation ----

def split(x, t):
    """Split tree t at key x.
    Returns (l, present, r) where:
    - set_of(l) = {y in set_of(t) | y < x}
    - present = (x in set_of(t))
    - set_of(r) = {y in set_of(t) | y > x}
    See reference_spec.thy: split definition.
    """
    if is_empty(t):
        return (ET(), False, ET())
    n = t.val
    if x == n:
        return (t.left, True, t.right)
    elif x < n:
        l1, present, r1 = split(x, t.left)
        return (l1, present, join(r1, n, t.right))
    else:
        l1, present, r1 = split(x, t.right)
        return (join(t.left, n, l1), present, r1)


# ---- Set operations ----

def join2(l, r):
    """Join two AVL trees without a separator key.
    Precondition: all elements of l are less than all elements of r.
    Uses delete_max to extract a separator from l.
    """
    if is_empty(l):
        return r
    if is_empty(r):
        return l
    new_n, l_prime = delete_max(l)
    return join(l_prime, new_n, r)


def union(t1, t2):
    """Set union of two AVL trees.
    Uses divide-and-conquer via split.
    See reference_spec.thy: t_union definition.
    """
    if is_empty(t1):
        return t2
    if is_empty(t2):
        return t1
    n2 = t2.val
    l1, _, r1 = split(n2, t1)
    return join(union(l1, t2.left), n2, union(r1, t2.right))


def intersection(t1, t2):
    """Set intersection of two AVL trees.
    See reference_spec.thy: t_inter definition.
    """
    if is_empty(t1) or is_empty(t2):
        return ET()
    n2 = t2.val
    l1, present, r1 = split(n2, t1)
    l_int = intersection(l1, t2.left)
    r_int = intersection(r1, t2.right)
    if present:
        return join(l_int, n2, r_int)
    else:
        return join2(l_int, r_int)


def difference(t1, t2):
    """Set difference: elements in t1 but not in t2.
    See reference_spec.thy: t_diff definition.
    """
    if is_empty(t1):
        return ET()
    if is_empty(t2):
        return t1
    n2 = t2.val
    l1, _, r1 = split(n2, t1)
    return join2(difference(l1, t2.left), difference(r1, t2.right))
'''

with open('/app/avl.py', 'w') as f:
    f.write(CORRECT_AVL)

print("All 8 bugs fixed in /app/avl.py:")
print("  - Bug 1: mkt_bal_l LR case lrl/lrr swap corrected")
print("  - Bug 2: mkt_bal_r RR case l/rl swap corrected")
print("  - Bug 3: delete x<n rebalance direction fixed (mkt_bal_l -> mkt_bal_r)")
print("  - Bug 4: delete_root rebalance added (mkt -> mkt_bal_r)")
print("  - Bug 5: split x>n join argument fixed (r1 -> l1)")
print("  - Bug 6: join_right rebalance direction fixed (mkt_bal_l -> mkt_bal_r)")
print("  - Bug 7: join_left fully implemented (was stub)")
print("  - Bug 8: intersection present check inverted (not present -> present)")
