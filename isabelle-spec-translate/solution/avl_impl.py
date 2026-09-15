
"""
Faithful Python translation of the AVL tree formalization from the
Isabelle Archive of Formal Proofs (AVL.thy by Nipkow, Pusch, Klein et al.).

Tree representation:
  - None  represents  ET  (empty tree)
  - (value, left, right, height)  represents  MKT value left right height

Every function directly mirrors the Isabelle specification.
"""


# ------------------------------------------------------------------
# Auxiliary functions
# ------------------------------------------------------------------

def ht(t):
    """Cached height: ht ET = 0 | ht (MKT _ _ _ h) = h"""
    if t is None:
        return 0
    return t[3]


def height(t):
    """Recursively computed height (not cached)."""
    if t is None:
        return 0
    _, l, r, _ = t
    return max(height(l), height(r)) + 1


def mkt(x, l, r):
    """Construct a node with correct cached height."""
    return (x, l, r, max(ht(l), ht(r)) + 1)


# ------------------------------------------------------------------
# Rebalancing
# ------------------------------------------------------------------

def mkt_bal_l(n, l, r):
    """Rebalance after left subtree grew (or right subtree shrank).

    Isabelle definition:
      if ht l = ht r + 2 then
        case l of MKT ln ll lr _ =>
          if ht ll < ht lr then  (* double rotation *)
            case lr of MKT lrn lrl lrr _ =>
              mkt lrn (mkt ln ll lrl) (mkt n lrr r)
          else  (* single rotation *)
            mkt ln ll (mkt n lr r)
      else mkt n l r
    """
    if ht(l) == ht(r) + 2:
        ln, ll, lr, _ = l
        if ht(ll) < ht(lr):
            # Double rotation (left-right)
            lrn, lrl, lrr, _ = lr
            return mkt(lrn, mkt(ln, ll, lrl), mkt(n, lrr, r))
        else:
            # Single rotation (right)
            return mkt(ln, ll, mkt(n, lr, r))
    else:
        return mkt(n, l, r)


def mkt_bal_r(n, l, r):
    """Rebalance after right subtree grew (or left subtree shrank).

    Isabelle definition:
      if ht r = ht l + 2 then
        case r of MKT rn rl rr _ =>
          if ht rl > ht rr then  (* double rotation *)
            case rl of MKT rln rll rlr _ =>
              mkt rln (mkt n l rll) (mkt rn rlr rr)
          else  (* single rotation *)
            mkt rn (mkt n l rl) rr
      else mkt n l r
    """
    if ht(r) == ht(l) + 2:
        rn, rl, rr, _ = r
        if ht(rl) > ht(rr):
            # Double rotation (right-left)
            rln, rll, rlr, _ = rl
            return mkt(rln, mkt(n, l, rll), mkt(rn, rlr, rr))
        else:
            # Single rotation (left)
            return mkt(rn, mkt(n, l, rl), rr)
    else:
        return mkt(n, l, r)


# ------------------------------------------------------------------
# Insertion
# ------------------------------------------------------------------

def avl_insert(x, t):
    """Insert x into AVL tree t.

    Isabelle definition:
      insert x ET = MKT x ET ET 1
      insert x (MKT n l r h) =
        if x = n then MKT n l r h
        else if x < n then mkt_bal_l n (insert x l) r
        else mkt_bal_r n l (insert x r)
    """
    if t is None:
        return (x, None, None, 1)
    n, l, r, h = t
    if x == n:
        return (n, l, r, h)
    elif x < n:
        return mkt_bal_l(n, avl_insert(x, l), r)
    else:
        return mkt_bal_r(n, l, avl_insert(x, r))


# ------------------------------------------------------------------
# Deletion helpers
# ------------------------------------------------------------------

def delete_max(t):
    """Remove and return the maximum (rightmost) element.

    Isabelle definition:
      delete_max (MKT n l ET h) = (n, l)
      delete_max (MKT n l r h) =
        let (n', r') = delete_max r in (n', mkt_bal_l n l r')

    Returns (max_value, remaining_tree).
    """
    n, l, r, h = t
    if r is None:
        return (n, l)
    else:
        n_prime, r_prime = delete_max(r)
        return (n_prime, mkt_bal_l(n, l, r_prime))


def delete_root(t):
    """Delete the root node of t.

    Isabelle definition:
      delete_root (MKT n ET r h) = r
      delete_root (MKT n l ET h) = l
      delete_root (MKT n l r h) =
        let (new_n, l') = delete_max l in mkt_bal_r new_n l' r
    """
    n, l, r, h = t
    if l is None:
        return r
    elif r is None:
        return l
    else:
        new_n, l_prime = delete_max(l)
        return mkt_bal_r(new_n, l_prime, r)


def avl_delete(x, t):
    """Delete x from AVL tree t.

    Isabelle definition:
      delete _ ET = ET
      delete x (MKT n l r h) =
        if x = n then delete_root (MKT n l r h)
        else if x < n then mkt_bal_r n (delete x l) r
        else mkt_bal_l n l (delete x r)
    """
    if t is None:
        return None
    n, l, r, h = t
    if x == n:
        return delete_root(t)
    elif x < n:
        l_prime = avl_delete(x, l)
        return mkt_bal_r(n, l_prime, r)
    else:
        r_prime = avl_delete(x, r)
        return mkt_bal_l(n, l, r_prime)


# ------------------------------------------------------------------
# Lookup
# ------------------------------------------------------------------

def is_in(k, t):
    """Check membership.

    Isabelle definition:
      is_in k ET = False
      is_in k (MKT n l r h) =
        if k = n then True
        else if k < n then is_in k l
        else is_in k r
    """
    if t is None:
        return False
    n, l, r, h = t
    if k == n:
        return True
    elif k < n:
        return is_in(k, l)
    else:
        return is_in(k, r)


# ------------------------------------------------------------------
# Set abstraction
# ------------------------------------------------------------------

def set_of(t):
    """Return the set of all elements stored in t."""
    if t is None:
        return set()
    n, l, r, _ = t
    return {n} | set_of(l) | set_of(r)


# ------------------------------------------------------------------
# Invariant check
# ------------------------------------------------------------------

def is_avl(t):
    """Check the full AVL invariant (balance + correct cached height).

    Isabelle definition:
      avl ET = True
      avl (MKT x l r h) =
        (height l = height r | height l = height r + 1 | height r = height l + 1)
        & h = max (height l) (height r) + 1
        & avl l & avl r
    """
    if t is None:
        return True
    _, l, r, h = t
    hl = height(l)
    hr = height(r)
    balance_ok = (hl == hr) or (hl == hr + 1) or (hr == hl + 1)
    height_ok = (h == max(hl, hr) + 1)
    return balance_ok and height_ok and is_avl(l) and is_avl(r)
