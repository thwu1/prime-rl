"""
Optimizer for DAG computations — implements algebraic simplification,
constant folding, identity/annihilation elimination, cancellation,
involution, inverse cancellation, conditional collapse, forward abstract
interpretation for range-based comparison folding, algebraic factoring
(distributive law), power-of-two strength reduction, and verified
candidate rules (C1 bit partition, C4 sub inverse, C5 additive inverse)
using the pattern-matching graph rewrite framework.

"""
from dag_ir import DAG, Op, MASK32
from pattern import Pat, Var, CVar, graph_rewrite


def _compute_range(dag: DAG, nid: int, cache: dict) -> tuple[int, int]:
    """Forward abstract interpretation: compute [min, max] uint32 range."""
    if nid in cache:
        return cache[nid]
    node = dag.nodes[nid]

    if node.op == Op.CONST:
        v = node.arg & MASK32
        r = (v, v)
    elif node.op == Op.ARG:
        r = (0, MASK32)
    elif node.op == Op.AND:
        ar = _compute_range(dag, node.srcs[0], cache)
        br = _compute_range(dag, node.srcs[1], cache)
        # AND can only clear bits — result ≤ min(a_max, b_max)
        r = (0, min(ar[1], br[1]))
    elif node.op == Op.OR:
        ar = _compute_range(dag, node.srcs[0], cache)
        br = _compute_range(dag, node.srcs[1], cache)
        r = (max(ar[0], br[0]), min(ar[1] | br[1], MASK32))
    elif node.op == Op.ADD:
        ar = _compute_range(dag, node.srcs[0], cache)
        br = _compute_range(dag, node.srcs[1], cache)
        total_max = ar[1] + br[1]
        if total_max <= MASK32:
            r = (ar[0] + br[0], total_max)
        else:
            r = (0, MASK32)
    elif node.op == Op.SUB:
        ar = _compute_range(dag, node.srcs[0], cache)
        br = _compute_range(dag, node.srcs[1], cache)
        if ar[0] >= br[1]:
            r = (ar[0] - br[1], ar[1] - br[0])
        else:
            r = (0, MASK32)
    elif node.op == Op.MUL:
        ar = _compute_range(dag, node.srcs[0], cache)
        br = _compute_range(dag, node.srcs[1], cache)
        prod_max = ar[1] * br[1]
        if prod_max <= MASK32:
            r = (ar[0] * br[0], prod_max)
        else:
            r = (0, MASK32)
    elif node.op == Op.SHR:
        ar = _compute_range(dag, node.srcs[0], cache)
        br = _compute_range(dag, node.srcs[1], cache)
        if br[0] == br[1]:  # constant shift amount
            shift = br[0] & 0x1F
            r = (ar[0] >> shift, ar[1] >> shift)
        else:
            r = (0, MASK32)
    elif node.op == Op.SHL:
        ar = _compute_range(dag, node.srcs[0], cache)
        br = _compute_range(dag, node.srcs[1], cache)
        if br[0] == br[1]:
            shift = br[0] & 0x1F
            shl_max = ar[1] << shift
            if shl_max <= MASK32:
                r = (ar[0] << shift, shl_max)
            else:
                r = (0, MASK32)
        else:
            r = (0, MASK32)
    elif node.op == Op.CMPLT:
        r = (0, 1)
    elif node.op == Op.CMPEQ:
        r = (0, 1)
    elif node.op == Op.NEG:
        r = (0, MASK32)
    elif node.op == Op.NOT:
        r = (0, MASK32)
    elif node.op == Op.XOR:
        r = (0, MASK32)
    elif node.op == Op.WHERE:
        # result range is union of true/false branch ranges
        tr = _compute_range(dag, node.srcs[1], cache)
        fr = _compute_range(dag, node.srcs[2], cache)
        r = (min(tr[0], fr[0]), max(tr[1], fr[1]))
    else:
        r = (0, MASK32)

    cache[nid] = r
    return r


def optimize(dag: DAG) -> DAG:
    """Optimize *dag* by applying rewrite rules to fixed-point."""

    rules: list[tuple] = []

    # ==================================================================
    # CONSTANT FOLDING — evaluate ops on two (or one) CONST operands
    # ==================================================================
    _binop_eval = {
        Op.ADD: lambda a, b: (a + b) & MASK32,
        Op.SUB: lambda a, b: (a - b) & MASK32,
        Op.MUL: lambda a, b: (a * b) & MASK32,
        Op.AND: lambda a, b: a & b,
        Op.OR:  lambda a, b: a | b,
        Op.XOR: lambda a, b: a ^ b,
        Op.SHL: lambda a, b: (a << (b & 0x1F)) & MASK32,
        Op.SHR: lambda a, b: (a >> (b & 0x1F)) & MASK32,
        Op.CMPLT: lambda a, b: 1 if (a & MASK32) < (b & MASK32) else 0,
        Op.CMPEQ: lambda a, b: 1 if (a & MASK32) == (b & MASK32) else 0,
    }
    for op, fn in _binop_eval.items():
        def _make_fold(f):
            return lambda dag, caps: dag.const(f(caps["a"], caps["b"]))
        rules.append((Pat(op, CVar("a"), CVar("b")), _make_fold(fn)))

    # unary constant fold
    rules.append((Pat(Op.NEG, CVar("a")),
                  lambda dag, caps: dag.const((-caps["a"]) & MASK32)))
    rules.append((Pat(Op.NOT, CVar("a")),
                  lambda dag, caps: dag.const((~caps["a"]) & MASK32)))

    # ==================================================================
    # IDENTITY ELIMINATION — x OP identity_element = x
    # ==================================================================
    # ADD(x, 0) → x  and  ADD(0, x) → x
    rules.append((Pat(Op.ADD, Var("x"), CVar("c")),
                  lambda dag, caps: caps["x"] if caps["c"] == 0 else None))
    rules.append((Pat(Op.ADD, CVar("c"), Var("x")),
                  lambda dag, caps: caps["x"] if caps["c"] == 0 else None))

    # SUB(x, 0) → x
    rules.append((Pat(Op.SUB, Var("x"), CVar("c")),
                  lambda dag, caps: caps["x"] if caps["c"] == 0 else None))

    # MUL(x, 1) → x  and  MUL(1, x) → x
    rules.append((Pat(Op.MUL, Var("x"), CVar("c")),
                  lambda dag, caps: caps["x"] if caps["c"] == 1 else None))
    rules.append((Pat(Op.MUL, CVar("c"), Var("x")),
                  lambda dag, caps: caps["x"] if caps["c"] == 1 else None))

    # XOR(x, 0) → x  and  XOR(0, x) → x
    rules.append((Pat(Op.XOR, Var("x"), CVar("c")),
                  lambda dag, caps: caps["x"] if caps["c"] == 0 else None))
    rules.append((Pat(Op.XOR, CVar("c"), Var("x")),
                  lambda dag, caps: caps["x"] if caps["c"] == 0 else None))

    # OR(x, 0) → x  and  OR(0, x) → x
    rules.append((Pat(Op.OR, Var("x"), CVar("c")),
                  lambda dag, caps: caps["x"] if caps["c"] == 0 else None))
    rules.append((Pat(Op.OR, CVar("c"), Var("x")),
                  lambda dag, caps: caps["x"] if caps["c"] == 0 else None))

    # AND(x, 0xFFFFFFFF) → x  and  AND(0xFFFFFFFF, x) → x
    rules.append((Pat(Op.AND, Var("x"), CVar("c")),
                  lambda dag, caps: caps["x"] if caps["c"] == MASK32 else None))
    rules.append((Pat(Op.AND, CVar("c"), Var("x")),
                  lambda dag, caps: caps["x"] if caps["c"] == MASK32 else None))

    # SHL(x, 0) → x  and  SHR(x, 0) → x
    rules.append((Pat(Op.SHL, Var("x"), CVar("c")),
                  lambda dag, caps: caps["x"] if caps["c"] == 0 else None))
    rules.append((Pat(Op.SHR, Var("x"), CVar("c")),
                  lambda dag, caps: caps["x"] if caps["c"] == 0 else None))

    # ==================================================================
    # ANNIHILATION — x OP annihilator = annihilator
    # ==================================================================
    # MUL(x, 0) → 0  and  MUL(0, x) → 0
    rules.append((Pat(Op.MUL, Var("x"), CVar("c")),
                  lambda dag, caps: dag.const(0) if caps["c"] == 0 else None))
    rules.append((Pat(Op.MUL, CVar("c"), Var("x")),
                  lambda dag, caps: dag.const(0) if caps["c"] == 0 else None))

    # AND(x, 0) → 0  and  AND(0, x) → 0
    rules.append((Pat(Op.AND, Var("x"), CVar("c")),
                  lambda dag, caps: dag.const(0) if caps["c"] == 0 else None))
    rules.append((Pat(Op.AND, CVar("c"), Var("x")),
                  lambda dag, caps: dag.const(0) if caps["c"] == 0 else None))

    # ==================================================================
    # SELF-RULES — x OP x
    # ==================================================================
    # XOR(x, x) → 0
    rules.append((Pat(Op.XOR, Var("x"), Var("x")),
                  lambda dag, caps: dag.const(0)))
    # SUB(x, x) → 0
    rules.append((Pat(Op.SUB, Var("x"), Var("x")),
                  lambda dag, caps: dag.const(0)))
    # AND(x, x) → x
    rules.append((Pat(Op.AND, Var("x"), Var("x")),
                  lambda dag, caps: caps["x"]))
    # OR(x, x) → x
    rules.append((Pat(Op.OR, Var("x"), Var("x")),
                  lambda dag, caps: caps["x"]))

    # ==================================================================
    # INVOLUTION — double application cancels
    # ==================================================================
    # NEG(NEG(x)) → x
    rules.append((Pat(Op.NEG, Pat(Op.NEG, Var("x"))),
                  lambda dag, caps: caps["x"]))
    # NOT(NOT(x)) → x
    rules.append((Pat(Op.NOT, Pat(Op.NOT, Var("x"))),
                  lambda dag, caps: caps["x"]))

    # ==================================================================
    # INVERSE CANCELLATION — two-level patterns
    # ==================================================================
    # SUB(ADD(x, y), y) → x  and  SUB(ADD(y, x), y) → x
    rules.append((Pat(Op.SUB, Pat(Op.ADD, Var("x"), Var("y")), Var("y")),
                  lambda dag, caps: caps["x"]))
    rules.append((Pat(Op.SUB, Pat(Op.ADD, Var("y"), Var("x")), Var("y")),
                  lambda dag, caps: caps["x"]))

    # XOR(XOR(x, y), y) → x  and  XOR(XOR(y, x), y) → x
    rules.append((Pat(Op.XOR, Pat(Op.XOR, Var("x"), Var("y")), Var("y")),
                  lambda dag, caps: caps["x"]))
    rules.append((Pat(Op.XOR, Pat(Op.XOR, Var("y"), Var("x")), Var("y")),
                  lambda dag, caps: caps["x"]))

    # XOR(y, XOR(x, y)) → x  and  XOR(y, XOR(y, x)) → x
    rules.append((Pat(Op.XOR, Var("y"), Pat(Op.XOR, Var("x"), Var("y"))),
                  lambda dag, caps: caps["x"]))
    rules.append((Pat(Op.XOR, Var("y"), Pat(Op.XOR, Var("y"), Var("x"))),
                  lambda dag, caps: caps["x"]))

    # ==================================================================
    # VERIFIED CANDIDATE RULES (C1, C4, C5 — proved sound via Z3)
    # ==================================================================

    # C1: Bit partition — OR(AND(x, c1), AND(x, c2)) → x
    #     when c1 and c2 are complementary masks (c1|c2=0xFFFFFFFF, c1&c2=0)
    def _bit_partition(dag, caps):
        c1_val, c2_val = caps["c1"], caps["c2"]
        if (c1_val | c2_val) == MASK32 and (c1_val & c2_val) == 0:
            return caps["x"]
        return None
    rules.append((
        Pat(Op.OR, Pat(Op.AND, Var("x"), CVar("c1")),
                   Pat(Op.AND, Var("x"), CVar("c2"))),
        _bit_partition))
    rules.append((
        Pat(Op.OR, Pat(Op.AND, CVar("c1"), Var("x")),
                   Pat(Op.AND, CVar("c2"), Var("x"))),
        _bit_partition))

    # C4: Sub inverse — SUB(x, SUB(x, y)) → y
    rules.append((Pat(Op.SUB, Var("x"), Pat(Op.SUB, Var("x"), Var("y"))),
                  lambda dag, caps: caps["y"]))

    # C5: Additive inverse — ADD(x, NEG(x)) → 0  and  ADD(NEG(x), x) → 0
    rules.append((Pat(Op.ADD, Var("x"), Pat(Op.NEG, Var("x"))),
                  lambda dag, caps: dag.const(0)))
    rules.append((Pat(Op.ADD, Pat(Op.NEG, Var("x")), Var("x")),
                  lambda dag, caps: dag.const(0)))

    # ==================================================================
    # CONDITIONAL SIMPLIFICATION
    # ==================================================================
    # WHERE(CONST(c), a, b) → a if c != 0 else b
    def _where_const(dag, caps):
        return caps["a"] if caps["c"] != 0 else caps["b"]
    rules.append((Pat(Op.WHERE, CVar("c"), Var("a"), Var("b")), _where_const))

    # WHERE(cond, a, a) → a   (identical branches)
    rules.append((Pat(Op.WHERE, Var("_c"), Var("a"), Var("a")),
                  lambda dag, caps: caps["a"]))

    # CMPEQ(x, x) → 1  (tautology)
    rules.append((Pat(Op.CMPEQ, Var("x"), Var("x")),
                  lambda dag, caps: dag.const(1)))

    # CMPLT(x, x) → 0  (contradiction)
    rules.append((Pat(Op.CMPLT, Var("x"), Var("x")),
                  lambda dag, caps: dag.const(0)))

    # ==================================================================
    # ALGEBRAIC FACTORING — distributive law
    # ADD(MUL(x, c1), MUL(x, c2)) → MUL(x, (c1+c2) & MASK32)
    # ==================================================================
    def _factor_add_mul(dag, caps):
        c_sum = (caps["c1"] + caps["c2"]) & MASK32
        return dag.mul(caps["x"], dag.const(c_sum))
    # All four commutative orderings of MUL operands
    rules.append((
        Pat(Op.ADD, Pat(Op.MUL, Var("x"), CVar("c1")),
                    Pat(Op.MUL, Var("x"), CVar("c2"))),
        _factor_add_mul))
    rules.append((
        Pat(Op.ADD, Pat(Op.MUL, CVar("c1"), Var("x")),
                    Pat(Op.MUL, CVar("c2"), Var("x"))),
        _factor_add_mul))
    rules.append((
        Pat(Op.ADD, Pat(Op.MUL, Var("x"), CVar("c1")),
                    Pat(Op.MUL, CVar("c2"), Var("x"))),
        _factor_add_mul))
    rules.append((
        Pat(Op.ADD, Pat(Op.MUL, CVar("c1"), Var("x")),
                    Pat(Op.MUL, Var("x"), CVar("c2"))),
        _factor_add_mul))

    # ==================================================================
    # POWER-OF-TWO STRENGTH REDUCTION
    # MUL(x, 2^k) → SHL(x, k)   and   MUL(2^k, x) → SHL(x, k)
    # ==================================================================
    def _is_pow2(c):
        return c > 0 and (c & (c - 1)) == 0

    def _pow2_shift(dag, caps):
        c = caps["c"]
        if _is_pow2(c):
            k = c.bit_length() - 1
            return dag.shl(caps["x"], dag.const(k))
        return None
    rules.append((Pat(Op.MUL, Var("x"), CVar("c")), _pow2_shift))
    rules.append((Pat(Op.MUL, CVar("c"), Var("x")), _pow2_shift))

    # ==================================================================
    # RANGE-BASED COMPARISON FOLDING — abstract interpretation
    # ==================================================================
    def _range_fold_cmplt(dag, caps):
        cache = {}
        a_r = _compute_range(dag, caps["a"], cache)
        b_r = _compute_range(dag, caps["b"], cache)
        if a_r[1] < b_r[0]:      # max(a) < min(b) → always true
            return dag.const(1)
        if a_r[0] >= b_r[1]:     # min(a) >= max(b) → always false
            return dag.const(0)
        return None
    rules.append((Pat(Op.CMPLT, Var("a"), Var("b")), _range_fold_cmplt))

    def _range_fold_cmpeq(dag, caps):
        cache = {}
        a_r = _compute_range(dag, caps["a"], cache)
        b_r = _compute_range(dag, caps["b"], cache)
        if a_r[1] < b_r[0] or b_r[1] < a_r[0]:   # ranges don't overlap
            return dag.const(0)
        if a_r[0] == a_r[1] == b_r[0] == b_r[1]:  # both same constant
            return dag.const(1)
        return None
    rules.append((Pat(Op.CMPEQ, Var("a"), Var("b")), _range_fold_cmpeq))

    return graph_rewrite(dag, rules)
