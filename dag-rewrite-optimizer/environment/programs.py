"""
Test programs — eight computation DAGs with known redundancies.

Each function returns a (DAG, target_comp_nodes) tuple.
target_comp_nodes is the maximum acceptable computational node count
after optimization (nodes whose op is not CONST or ARG).

"""
from dag_ir import DAG, Op


# ---------------------------------------------------------------------------
# Program 1 — identity_cleanup
# A hash computation wrapped in many identity operations that should be
# stripped away: x^0, x*1, x+0, x<<0, x&0xFFFFFFFF, NEG(NEG(x)),
# NOT(NOT(x)), 0|x.
# ---------------------------------------------------------------------------
def make_identity_cleanup() -> tuple[DAG, int]:
    d = DAG()
    x = d.arg(0)
    c0 = d.const(0)
    c1 = d.const(1)
    cff = d.const(0xFFFFFFFF)

    # ----- redundant identity chain (10 ops, all should collapse to x) -----
    t1 = d.xor(x, c0)         # x ^ 0 = x
    t2 = d.mul(t1, c1)        # x * 1 = x
    t3 = d.add(t2, c0)        # x + 0 = x
    t4 = d.shl(t3, c0)        # x << 0 = x
    t5 = d.and_(t4, cff)      # x & 0xFFFFFFFF = x
    t6 = d.neg(t5)
    t7 = d.neg(t6)            # NEG(NEG(x)) = x
    t8 = d.not_(t7)
    t9 = d.not_(t8)           # NOT(NOT(x)) = x
    t10 = d.or_(c0, t9)       # 0 | x = x  (commutative identity)

    # ----- essential hash computation (11 ops) -----
    ch1 = d.const(0x7ED55D16)
    c12 = d.const(12)
    a = d.add(t10, ch1)
    b = d.shl(t10, c12)
    c = d.add(a, b)

    ch2 = d.const(0xC761C23C)
    c19 = d.const(19)
    e = d.xor(c, ch2)
    f = d.shr(c, c19)
    g = d.xor(e, f)

    ch3 = d.const(0x165667B1)
    c5 = d.const(5)
    h = d.add(g, ch3)
    i = d.shl(g, c5)
    j = d.add(h, i)

    c16 = d.const(16)
    k = d.shr(j, c16)
    result = d.xor(j, k)

    # ----- trailing redundant identity (3 ops) -----
    r1 = d.add(result, c0)    # + 0
    r2 = d.mul(r1, c1)        # * 1
    r3 = d.xor(r2, c0)        # ^ 0

    d.set_outputs([r3])
    return d, 11


# ---------------------------------------------------------------------------
# Program 2 — const_propagation
# A long chain of operations on constants that should all fold away,
# leaving only four operations that mix folded constants with the input.
# ---------------------------------------------------------------------------
def make_const_propagation() -> tuple[DAG, int]:
    d = DAG()
    x = d.arg(0)
    c2 = d.const(2)
    c3 = d.const(3)
    c5 = d.const(5)
    c7 = d.const(7)
    cff = d.const(0xFF)
    c4 = d.const(4)

    # ----- constant chain (10 ops, all foldable) -----
    a = d.add(c2, c3)          # 5
    b = d.mul(c5, c7)          # 35
    cc = d.xor(a, b)           # 5 ^ 35 = 38
    dd = d.shl(cc, c4)         # 38 << 4 = 608
    ee = d.and_(dd, cff)       # 608 & 0xFF = 96
    ff = d.sub(b, a)           # 35 - 5 = 30
    gg = d.add(ee, ff)         # 96 + 30 = 126
    hh = d.mul(gg, c3)         # 126 * 3 = 378
    ii = d.not_(c7)            # ~7 = 0xFFFFFFF8
    jj = d.and_(hh, ii)       # 378 & 0xFFFFFFF8 = 376

    # ----- essential computation (4 ops) -----
    k = d.add(x, jj)           # x + 376
    l = d.xor(x, gg)           # x ^ 126
    m = d.mul(k, l)            # (x + 376) * (x ^ 126)
    n = d.sub(m, jj)           # result - 376

    d.set_outputs([n])
    return d, 4


# ---------------------------------------------------------------------------
# Program 3 — cancel_annihilate
# Additive/XOR cancellation, self-cancellation, annihilation, involution,
# commutative identity, and self-AND.  After optimizing, only two
# essential operations remain.
# ---------------------------------------------------------------------------
def make_cancel_annihilate() -> tuple[DAG, int]:
    d = DAG()
    x = d.arg(0)
    y = d.arg(1)
    c0 = d.const(0)
    c1 = d.const(1)

    # additive cancel: (x + y) - y  →  x
    a = d.add(x, y)
    b = d.sub(a, y)

    # XOR cancel: (x ^ y) ^ y  →  x
    c = d.xor(x, y)
    dd = d.xor(c, y)

    # self-cancel
    e = d.xor(y, y)            # y ^ y → 0
    f = d.sub(x, x)            # x - x → 0

    # annihilation (requires b→x and f→0 first)
    g = d.mul(b, f)            # x * 0 → 0

    # involution (requires dd→x first)
    h = d.neg(dd)
    i = d.neg(h)               # NEG(NEG(x)) → x

    # commutative identity: ADD(0, x) → x (g→0, i→x)
    j = d.add(g, i)

    # self: AND(x, x) → x
    k = d.and_(j, j)

    # identity: ADD(x, 0) → x  (e→0)
    l = d.add(k, e)

    # ----- essential computation (2 ops) -----
    m = d.add(l, y)            # x + y
    n = d.shl(m, c1)           # (x + y) << 1

    d.set_outputs([n])
    return d, 2


# ---------------------------------------------------------------------------
# Program 4 — cond_collapse
# WHERE nodes with constant conditions, identical branches, and
# tautological/contradictory comparisons.
# ---------------------------------------------------------------------------
def make_cond_collapse() -> tuple[DAG, int]:
    d = DAG()
    x = d.arg(0)
    y = d.arg(1)
    c0 = d.const(0)
    c1 = d.const(1)

    # constant-condition WHERE
    a = d.where(c1, x, y)          # WHERE(1, x, y) → x
    b = d.where(c0, x, y)          # WHERE(0, x, y) → y

    # identical-branches WHERE
    c = d.where(x, y, y)           # WHERE(_, y, y) → y

    # tautological comparison
    dd = d.cmpeq(x, x)            # CMPEQ(x, x) → 1
    ee = d.where(dd, x, y)        # WHERE(1, x, y) → x

    # contradictory comparison
    ff = d.cmplt(x, x)            # CMPLT(x, x) → 0
    gg = d.where(ff, x, y)        # WHERE(0, x, y) → y

    # nested: WHERE(1, WHERE(0, x, y), x) → WHERE(0, x, y) → y → y
    hh_inner = d.where(c0, x, y)   # → y
    hh = d.where(c1, hh_inner, x)  # → hh_inner → y

    # ----- combine simplified results (5 essential ops) -----
    i = d.add(a, b)                # x + y
    j = d.add(ee, gg)             # x + y
    k = d.add(c, hh)              # y + y
    l = d.add(i, k)               # (x + y) + (y + y)
    m = d.add(l, j)               # + (x + y)

    d.set_outputs([m])
    return d, 5


# ---------------------------------------------------------------------------
# Program 5 — range_fold
# Comparisons whose truth depends on value ranges propagating through
# arithmetic operations.  Pattern matching alone cannot simplify these;
# the optimizer must reason about uint32 interval bounds.
#
# AND(x, 0xFF) ∈ [0, 255], AND(y, 0xFF) ∈ [0, 255]
# ADD of masked values ∈ [0, 510], which is < 512
# → CMPLT folds to 1, WHERE selects true-branch, MUL is dead code
# ---------------------------------------------------------------------------
def make_range_fold() -> tuple[DAG, int]:
    d = DAG()
    x = d.arg(0)
    y = d.arg(1)

    # Mask to low 8 bits — provable range [0, 255]
    c_mask = d.const(0xFF)
    x_lo = d.and_(x, c_mask)
    y_lo = d.and_(y, c_mask)

    # Sum of masked values — provable range [0, 510]
    s = d.add(x_lo, y_lo)

    # This comparison is NOT a constant-condition WHERE —
    # both operands are non-constant.  Range analysis proves
    # max(s) = 510 < 512 = min(bound), so the result is always 1.
    c_bound = d.const(0x200)        # 512
    cond = d.cmplt(s, c_bound)

    # Dead branch: the MUL is only reachable if cond=0, which never happens
    fallback = d.mul(x, y)
    result = d.where(cond, s, fallback)

    d.set_outputs([result])
    return d, 3   # AND, AND, ADD


# ---------------------------------------------------------------------------
# Program 6 — algebraic_factor
# Multiplicative redundancies requiring the distributive law and
# power-of-two strength reduction.
#
# ADD(MUL(x, 3), MUL(x, 5))  →  MUL(x, 8)  →  SHL(x, 3)
# ADD(MUL(y, 12), MUL(y, 4)) →  MUL(y, 16) →  SHL(y, 4)
# ---------------------------------------------------------------------------
def make_algebraic_factor() -> tuple[DAG, int]:
    d = DAG()
    x = d.arg(0)
    y = d.arg(1)

    # Pair 1: x*3 + x*5 = x*8 = x << 3
    c3 = d.const(3)
    c5 = d.const(5)
    t1 = d.mul(x, c3)
    t2 = d.mul(x, c5)
    s = d.add(t1, t2)

    # Pair 2: y*12 + y*4 = y*16 = y << 4
    c12 = d.const(12)
    c4 = d.const(4)
    t3 = d.mul(y, c12)
    t4 = d.mul(y, c4)
    u = d.add(t3, t4)

    result = d.add(s, u)
    d.set_outputs([result])
    return d, 3   # SHL, SHL, ADD


# ---------------------------------------------------------------------------
# Program 7 — multi_pass_compose
# Combines constant folding, conditional collapse, additive/XOR
# cancellation, involution, annihilation, and identity elimination.
# Requires many cascading passes (14+) to fully simplify.
# ---------------------------------------------------------------------------
def make_multi_pass() -> tuple[DAG, int]:
    d = DAG()
    x = d.arg(0)
    y = d.arg(1)
    c0 = d.const(0)
    c1 = d.const(1)
    c2 = d.const(2)
    c3 = d.const(3)
    c7 = d.const(7)

    # Layer 1: constant chain
    a = d.add(c2, c3)           # → 5
    b = d.mul(a, c7)            # → 35
    cc = d.sub(b, a)            # → 30
    dd = d.xor(cc, b)           # → 30 ^ 35 = 61

    # Layer 2: comparison on folded constants
    g = d.cmplt(a, b)           # CMPLT(5, 35) → 1

    # Layer 3: conditional collapse
    h = d.where(g, x, y)       # WHERE(1, x, y) → x

    # Layer 4: additive cancel
    i = d.add(h, y)             # x + y
    j = d.sub(i, y)             # (x + y) - y → x

    # Layer 5: XOR cancel
    k = d.xor(j, y)             # x ^ y
    l = d.xor(k, y)             # (x ^ y) ^ y → x

    # Layer 6: involution
    m = d.neg(l)
    n = d.neg(m)                # NEG(NEG(x)) → x

    # Layer 7: self-cancel
    p = d.sub(y, y)             # → 0

    # Layer 8: identity (n→x, p→0)
    q = d.add(n, p)             # x + 0 → x

    # Layer 9: commutative identity (g→1, q→x)
    o = d.mul(g, q)             # 1 * x → x

    # Layer 10: identity
    r = d.add(o, c0)            # x + 0 → x

    # Layer 11: essential computation
    s = d.add(r, y)             # x + y
    t = d.mul(s, dd)            # (x + y) * 61

    d.set_outputs([t])
    return d, 2


# ---------------------------------------------------------------------------
# Program 8 — verified_rewrites
# Requires applying formally verified candidate rewrite rules:
# C1 (bit partition), C4 (sub inverse), C5 (additive inverse).
# Combined with identity elimination, cascading 4+ passes deep.
# ---------------------------------------------------------------------------
def make_verified_rewrites() -> tuple[DAG, int]:
    d = DAG()
    x = d.arg(0)
    y = d.arg(1)

    # --- Bit partition: OR(AND(x, mask), AND(x, ~mask)) → x (rule C1) ---
    c_hi = d.const(0xFF00FF00)
    c_lo = d.const(0x00FF00FF)
    bp1 = d.and_(x, c_hi)
    bp2 = d.and_(x, c_lo)
    bp = d.or_(bp1, bp2)

    # --- Additive inverse: ADD(y, NEG(y)) → 0 (rule C5) ---
    ny = d.neg(y)
    zero = d.add(y, ny)

    # --- Identity: ADD(bp, 0) → bp, then bp → x via C1 ---
    e1 = d.add(bp, zero)

    # --- Sub inverse: SUB(e1, SUB(e1, y)) → y (rule C4) ---
    s1 = d.sub(e1, y)
    s2 = d.sub(e1, s1)

    # --- Essential computation: ADD(x, y) ---
    result = d.add(e1, s2)

    d.set_outputs([result])
    return d, 2


# ---------------------------------------------------------------------------
# Registry — map from name to builder function
# ---------------------------------------------------------------------------
PROGRAMS: dict[str, callable] = {
    "identity_cleanup":   make_identity_cleanup,
    "const_propagation":  make_const_propagation,
    "cancel_annihilate":  make_cancel_annihilate,
    "cond_collapse":      make_cond_collapse,
    "range_fold":         make_range_fold,
    "algebraic_factor":   make_algebraic_factor,
    "multi_pass_compose": make_multi_pass,
    "verified_rewrites":  make_verified_rewrites,
}
