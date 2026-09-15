"""
Peephole optimizer for the Sea-of-Nodes IR.

Implements:
  - Constant folding (evaluate ops on constant inputs)
  - Algebraic simplification (identity, annihilator, self-op rules)
  - Strength reduction (multiply/divide/mod by power-of-two)
  - Comparison simplification (reflexive comparisons)
  - Select simplification (constant condition, identical arms)
  - Cast simplification (redundant trunc/zext/sext chains)
  - Unary simplification (double negation, double complement)
  - Global Value Numbering (CSE via structural hashing)
  - Dead code elimination
"""


import sys
sys.path.insert(0, '/opt/son_ir')
sys.path.insert(0, '/app')

from ir import Graph, Node, Op, DataType, _c_sdiv, _c_smod
from typing import Optional, Dict, Tuple


def optimize(graph: Graph) -> None:
    """Optimize the graph in-place.  Iterates peephole + GVN + DCE to a
    fixed point."""
    opt = _Optimizer(graph)
    opt.run()


class _Optimizer:
    def __init__(self, graph: Graph):
        self.g = graph
        self._const_cache: Dict[Tuple[DataType, int], Node] = {}
        # Seed cache with existing constants
        for n in graph.nodes:
            if n.op == Op.ICONST:
                self._const_cache[(n.dt, n.extra)] = n

    # -- helpers ------------------------------------------------------------

    def _iconst(self, dt: DataType, value: int) -> Node:
        value = dt.truncate(value)
        key = (dt, value)
        if key in self._const_cache:
            return self._const_cache[key]
        node = self.g.iconst(dt, value)
        self._const_cache[key] = node
        return node

    @staticmethod
    def _is_pow2(v: int) -> bool:
        return v > 0 and (v & (v - 1)) == 0

    @staticmethod
    def _log2(v: int) -> int:
        assert v > 0 and (v & (v - 1)) == 0
        return v.bit_length() - 1

    # -- main loop ----------------------------------------------------------

    def run(self):
        MAX_ITERS = 50
        for _ in range(MAX_ITERS):
            changed = self._peephole_pass()
            changed |= self._gvn_pass()
            self.g.remove_dead()
            if not changed:
                break

    def _peephole_pass(self) -> bool:
        changed = False
        for node in list(self.g.nodes):
            if node not in self.g.nodes:
                continue
            result = self._process(node)
            if result is not None and result is not node:
                self.g.replace_node(node, result)
                changed = True
        return changed

    def _gvn_pass(self) -> bool:
        changed = False
        table: Dict[Tuple, Node] = {}
        for node in list(self.g.nodes):
            if node not in self.g.nodes:
                continue
            key = self._gvn_key(node)
            if key is None:
                continue
            if key in table:
                canonical = table[key]
                if canonical is not node:
                    self.g.replace_node(node, canonical)
                    changed = True
            else:
                table[key] = node
        return changed

    def _gvn_key(self, node: Node) -> Optional[Tuple]:
        if node.op == Op.PARAM:
            return None
        if node.op == Op.ICONST:
            return (Op.ICONST, node.dt, node.extra)
        input_ids = [inp.id for inp in node.inputs]
        if node.op.is_binary and node.op.is_commutative:
            input_ids = sorted(input_ids)
        return (node.op, node.dt, tuple(input_ids))

    # -- per-node processing ------------------------------------------------

    def _process(self, n: Node) -> Optional[Node]:
        # 1. Constant folding
        r = self._const_fold(n)
        if r is not None:
            return r
        # 2. Canonicalization (commutative: const to the right)
        r = self._canonicalize(n)
        if r is not None:
            return r
        # 3. Algebraic simplification
        r = self._idealize(n)
        if r is not None:
            return r
        return None

    # -- canonicalization ---------------------------------------------------

    def _canonicalize(self, n: Node) -> Optional[Node]:
        if n.op.is_binary and n.op.is_commutative:
            a, b = n.inputs
            if a.is_const and not b.is_const:
                # Swap so constant is on the right
                a.users = [(u, s) for u, s in a.users
                           if not (u is n and s == 0)]
                b.users = [(u, s) for u, s in b.users
                           if not (u is n and s == 1)]
                n.inputs[0], n.inputs[1] = b, a
                b.users.append((n, 0))
                a.users.append((n, 1))
                return n  # signal change for re-processing
        return None

    # -- constant folding ---------------------------------------------------

    def _const_fold(self, n: Node) -> Optional[Node]:
        op = n.op
        if op in (Op.ICONST, Op.PARAM):
            return None

        # Unary constant fold
        if op == Op.NEG and n.inputs[0].is_const:
            return self._iconst(n.dt, -n.inputs[0].const_val)
        if op == Op.NOT and n.inputs[0].is_const:
            return self._iconst(n.dt, n.inputs[0].const_val ^ n.dt.mask)

        # Cast constant fold
        if op == Op.TRUNC and n.inputs[0].is_const:
            return self._iconst(n.dt, n.inputs[0].const_val)
        if op == Op.ZEXT and n.inputs[0].is_const:
            return self._iconst(n.dt, n.inputs[0].const_val)
        if op == Op.SEXT and n.inputs[0].is_const:
            src_dt = n.inputs[0].dt
            signed = src_dt.sign_extend(n.inputs[0].const_val)
            return self._iconst(n.dt, signed)

        # Select with constant condition
        if op == Op.SELECT and n.inputs[0].is_const:
            return n.inputs[1] if n.inputs[0].const_val else n.inputs[2]

        # Binary constant fold
        if not op.is_binary:
            return None
        a, b = n.inputs
        if not (a.is_const and b.is_const):
            return None

        av, bv = a.const_val, b.const_val
        src_dt = a.dt
        dt = n.dt

        result = None
        if op == Op.ADD:
            result = (av + bv) & src_dt.mask
        elif op == Op.SUB:
            result = (av - bv) & src_dt.mask
        elif op == Op.MUL:
            result = (av * bv) & src_dt.mask
        elif op == Op.UDIV:
            result = 0 if bv == 0 else av // bv
        elif op == Op.SDIV:
            if bv == 0:
                return None  # leave as-is
            sa = src_dt.sign_extend(av)
            sb = src_dt.sign_extend(bv)
            result = dt.truncate(_c_sdiv(sa, sb))
        elif op == Op.UMOD:
            result = 0 if bv == 0 else av % bv
        elif op == Op.SMOD:
            if bv == 0:
                return None
            sa = src_dt.sign_extend(av)
            sb = src_dt.sign_extend(bv)
            result = dt.truncate(_c_smod(sa, sb))
        elif op == Op.AND:
            result = av & bv
        elif op == Op.OR:
            result = av | bv
        elif op == Op.XOR:
            result = av ^ bv
        elif op == Op.SHL:
            shift = bv & (src_dt.value - 1)
            result = (av << shift) & src_dt.mask
        elif op == Op.LSHR:
            shift = bv & (src_dt.value - 1)
            result = av >> shift
        elif op == Op.ASHR:
            shift = bv & (src_dt.value - 1)
            result = dt.truncate(src_dt.sign_extend(av) >> shift)
        elif op == Op.CMP_EQ:
            result = 1 if av == bv else 0
        elif op == Op.CMP_NE:
            result = 1 if av != bv else 0
        elif op == Op.CMP_SLT:
            result = (1 if src_dt.sign_extend(av) < src_dt.sign_extend(bv)
                      else 0)
        elif op == Op.CMP_SLE:
            result = (1 if src_dt.sign_extend(av) <= src_dt.sign_extend(bv)
                      else 0)
        elif op == Op.CMP_ULT:
            result = 1 if av < bv else 0
        elif op == Op.CMP_ULE:
            result = 1 if av <= bv else 0

        if result is not None:
            return self._iconst(dt, result)
        return None

    # -- algebraic simplification -------------------------------------------

    def _idealize(self, n: Node) -> Optional[Node]:
        op = n.op

        # -- unary ops ------------------------------------------------------
        if op == Op.NEG:
            x = n.inputs[0]
            # neg(neg(x)) -> x
            if x.op == Op.NEG:
                return x.inputs[0]
            return None

        if op == Op.NOT:
            x = n.inputs[0]
            # not(not(x)) -> x
            if x.op == Op.NOT:
                return x.inputs[0]
            return None

        # -- select ---------------------------------------------------------
        if op == Op.SELECT:
            cond, tv, fv = n.inputs
            # select(c, x, x) -> x
            if tv is fv:
                return tv
            return None

        # -- casts ----------------------------------------------------------
        if op == Op.TRUNC:
            x = n.inputs[0]
            # trunc(zext(y)) where result width == y width -> y
            if x.op == Op.ZEXT and n.dt == x.inputs[0].dt:
                return x.inputs[0]
            # trunc(sext(y)) where result width == y width -> y
            if x.op == Op.SEXT and n.dt == x.inputs[0].dt:
                return x.inputs[0]
            # trunc(trunc(y)) -> trunc(y) to narrowest
            if x.op == Op.TRUNC:
                return self.g.trunc(x.inputs[0], n.dt)
            return None

        if op == Op.ZEXT:
            x = n.inputs[0]
            # zext(zext(y)) -> zext(y) to widest
            if x.op == Op.ZEXT:
                return self.g.zext(x.inputs[0], n.dt)
            return None

        if op == Op.SEXT:
            x = n.inputs[0]
            # sext(sext(y)) -> sext(y) to widest
            if x.op == Op.SEXT:
                return self.g.sext(x.inputs[0], n.dt)
            return None

        # -- binary ops -----------------------------------------------------
        if not op.is_binary:
            return None

        a, b = n.inputs
        dt = n.dt
        mask = dt.mask

        # ---- ADD ----------------------------------------------------------
        if op == Op.ADD:
            # x + 0 -> x
            if b.is_const and b.const_val == 0:
                return a
            # 0 + x -> x (after canonicalization, but just in case)
            if a.is_const and a.const_val == 0:
                return b
            return None

        # ---- SUB ----------------------------------------------------------
        if op == Op.SUB:
            # x - 0 -> x
            if b.is_const and b.const_val == 0:
                return a
            # x - x -> 0
            if a is b:
                return self._iconst(dt, 0)
            return None

        # ---- MUL ----------------------------------------------------------
        if op == Op.MUL:
            # x * 0 -> 0
            if b.is_const and b.const_val == 0:
                return self._iconst(dt, 0)
            if a.is_const and a.const_val == 0:
                return self._iconst(dt, 0)
            # x * 1 -> x
            if b.is_const and b.const_val == 1:
                return a
            if a.is_const and a.const_val == 1:
                return b
            # x * 2^n -> x << n  (strength reduction)
            if b.is_const and self._is_pow2(b.const_val):
                shift = self._log2(b.const_val)
                return self.g.shl(a, self._iconst(dt, shift))
            if a.is_const and self._is_pow2(a.const_val):
                shift = self._log2(a.const_val)
                return self.g.shl(b, self._iconst(dt, shift))
            return None

        # ---- UDIV ---------------------------------------------------------
        if op == Op.UDIV:
            # x /u 1 -> x
            if b.is_const and b.const_val == 1:
                return a
            # x /u 2^n -> x >>u n  (strength reduction)
            if b.is_const and self._is_pow2(b.const_val):
                shift = self._log2(b.const_val)
                return self.g.lshr(a, self._iconst(dt, shift))
            return None

        # ---- SDIV ---------------------------------------------------------
        if op == Op.SDIV:
            # x /s 1 -> x
            if b.is_const and b.const_val == 1:
                return a
            return None

        # ---- UMOD ---------------------------------------------------------
        if op == Op.UMOD:
            # x %u 1 -> 0
            if b.is_const and b.const_val == 1:
                return self._iconst(dt, 0)
            # x %u 2^n -> x & (2^n - 1)  (strength reduction)
            if b.is_const and self._is_pow2(b.const_val):
                return self.g.and_(a, self._iconst(dt, b.const_val - 1))
            return None

        # ---- SMOD ---------------------------------------------------------
        if op == Op.SMOD:
            # x %s 1 -> 0
            if b.is_const and b.const_val == 1:
                return self._iconst(dt, 0)
            return None

        # ---- AND ----------------------------------------------------------
        if op == Op.AND:
            # x & 0 -> 0
            if b.is_const and b.const_val == 0:
                return self._iconst(dt, 0)
            if a.is_const and a.const_val == 0:
                return self._iconst(dt, 0)
            # x & all_ones -> x
            if b.is_const and b.const_val == mask:
                return a
            if a.is_const and a.const_val == mask:
                return b
            # x & x -> x
            if a is b:
                return a
            return None

        # ---- OR -----------------------------------------------------------
        if op == Op.OR:
            # x | 0 -> x
            if b.is_const and b.const_val == 0:
                return a
            if a.is_const and a.const_val == 0:
                return b
            # x | all_ones -> all_ones
            if b.is_const and b.const_val == mask:
                return self._iconst(dt, mask)
            if a.is_const and a.const_val == mask:
                return self._iconst(dt, mask)
            # x | x -> x
            if a is b:
                return a
            return None

        # ---- XOR ----------------------------------------------------------
        if op == Op.XOR:
            # x ^ 0 -> x
            if b.is_const and b.const_val == 0:
                return a
            if a.is_const and a.const_val == 0:
                return b
            # x ^ x -> 0
            if a is b:
                return self._iconst(dt, 0)
            return None

        # ---- SHL / LSHR / ASHR -------------------------------------------
        if op in (Op.SHL, Op.LSHR, Op.ASHR):
            # x << 0 -> x, x >> 0 -> x
            if b.is_const and b.const_val == 0:
                return a
            return None

        # ---- Comparisons -------------------------------------------------
        if op.is_comparison:
            # Reflexive: cmp(x, x)
            if a is b:
                if op in (Op.CMP_EQ, Op.CMP_SLE, Op.CMP_ULE):
                    return self._iconst(DataType.I1, 1)
                if op in (Op.CMP_NE, Op.CMP_SLT, Op.CMP_ULT):
                    return self._iconst(DataType.I1, 0)
            return None

        return None
