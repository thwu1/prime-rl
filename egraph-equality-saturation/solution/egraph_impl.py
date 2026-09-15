
"""
E-graph equality saturation engine.

Implements the core e-graph data structure (union-find, congruence closure),
pattern matching over equivalence classes, equality saturation with constant
folding, and cost-based extraction.
"""

import sys

sys.path.insert(0, "/app")

from expr import Expr, Var, Num, BinOp, parse, expr_cost  # noqa: E402
from rules import PatVar, PatNum, PatOp  # noqa: E402

_NODE_LIMIT = 5000
_MATCH_LIMIT = 5000


class EGraph:
    """E-graph with union-find, hashconsing, and congruence closure."""

    def __init__(self):
        self._parent = {}
        self._rank = {}
        self._classes = {}  # canonical_id -> set of canonical enodes
        self._memo = {}  # canonical enode -> canonical eclass id
        self._next = 0

    # ---- union-find --------------------------------------------------

    def find(self, eid):
        root = eid
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[eid] != root:
            self._parent[eid], eid = root, self._parent[eid]
        return root

    def _make(self):
        eid = self._next
        self._next += 1
        self._parent[eid] = eid
        self._rank[eid] = 0
        self._classes[eid] = set()
        return eid

    # ---- enode helpers -----------------------------------------------

    def _canon(self, enode):
        if enode[0] in ("num", "var"):
            return enode
        return ("op", enode[1], self.find(enode[2]), self.find(enode[3]))

    def _add_enode(self, enode):
        enode = self._canon(enode)
        if enode in self._memo:
            return self.find(self._memo[enode])
        if self._next >= _NODE_LIMIT:
            return None
        eid = self._make()
        self._classes[eid].add(enode)
        self._memo[enode] = eid
        return eid

    # ---- public mutators ---------------------------------------------

    def add_expr(self, expr):
        """Insert an Expr tree and return its e-class id."""
        if isinstance(expr, Num):
            return self._add_enode(("num", expr.value))
        if isinstance(expr, Var):
            return self._add_enode(("var", expr.name))
        if isinstance(expr, BinOp):
            l = self.add_expr(expr.left)
            r = self.add_expr(expr.right)
            return self._add_enode(("op", expr.op, l, r))
        raise TypeError(type(expr))

    def merge(self, a, b):
        """Union two e-classes. Returns new canonical id."""
        a, b = self.find(a), self.find(b)
        if a == b:
            return a
        if self._rank[a] < self._rank[b]:
            a, b = b, a
        self._parent[b] = a
        if self._rank[a] == self._rank[b]:
            self._rank[a] += 1
        self._classes[a] |= self._classes.pop(b, set())
        return a

    def rebuild(self):
        """Restore congruence closure invariant after merges."""
        changed = True
        while changed:
            changed = False
            pairs = []
            for eid in list(self._classes):
                ceid = self.find(eid)
                for en in self._classes[eid]:
                    pairs.append((en, ceid))

            self._classes.clear()
            self._memo.clear()

            for enode, owner in pairs:
                owner = self.find(owner)
                cenode = self._canon(enode)

                if cenode in self._memo:
                    existing = self.find(self._memo[cenode])
                    current = self.find(owner)
                    if existing != current:
                        w, l = existing, current
                        if self._rank.get(w, 0) < self._rank.get(l, 0):
                            w, l = l, w
                        self._parent[l] = w
                        if self._rank.get(w, 0) == self._rank.get(l, 0):
                            self._rank[w] = self._rank.get(w, 0) + 1
                        self._classes.setdefault(w, set())
                        self._classes[w] |= self._classes.pop(l, set())
                        owner = w
                        changed = True
                    else:
                        owner = existing
                else:
                    owner = self.find(owner)
                    self._memo[cenode] = owner

                owner = self.find(owner)
                self._classes.setdefault(owner, set()).add(cenode)

    # ---- read-only accessors -----------------------------------------

    def eclass_enodes(self, eid):
        return self._classes.get(self.find(eid), set())

    def all_eclasses(self):
        return list(self._classes.keys())


# ======================================================================
# Pattern matching
# ======================================================================

def _ematch(egraph, pattern, eid, subst, out):
    eid = egraph.find(eid)

    if isinstance(pattern, PatVar):
        if pattern.name in subst:
            if egraph.find(subst[pattern.name]) == eid:
                out.append(dict(subst))
        else:
            s = dict(subst)
            s[pattern.name] = eid
            out.append(s)
        return

    if isinstance(pattern, PatNum):
        for en in egraph.eclass_enodes(eid):
            if en[0] == "num" and en[1] == pattern.value:
                out.append(dict(subst))
                return
        return

    if isinstance(pattern, PatOp):
        for en in egraph.eclass_enodes(eid):
            if en[0] == "op" and en[1] == pattern.op:
                lid = egraph.find(en[2])
                rid = egraph.find(en[3])
                left_hits = []
                _ematch(egraph, pattern.left, lid, subst, left_hits)
                for lh in left_hits:
                    _ematch(egraph, pattern.right, rid, lh, out)


def _instantiate(egraph, pattern, subst):
    if isinstance(pattern, PatVar):
        return subst[pattern.name]
    if isinstance(pattern, PatNum):
        return egraph._add_enode(("num", pattern.value))
    if isinstance(pattern, PatOp):
        l = _instantiate(egraph, pattern.left, subst)
        if l is None:
            return None
        r = _instantiate(egraph, pattern.right, subst)
        if r is None:
            return None
        return egraph._add_enode(("op", pattern.op, l, r))
    raise TypeError(type(pattern))


# ======================================================================
# Rule application & constant folding
# ======================================================================

def _apply_rules(egraph, rules):
    if egraph._next >= _NODE_LIMIT:
        return False

    matches = []
    for eid in egraph.all_eclasses():
        for rule in rules:
            hits = []
            _ematch(egraph, rule.lhs, eid, {}, hits)
            for h in hits:
                matches.append((rule, eid, h))
                if len(matches) >= _MATCH_LIMIT:
                    break
            if len(matches) >= _MATCH_LIMIT:
                break
        if len(matches) >= _MATCH_LIMIT:
            break

    merged = False
    for rule, eid, subst in matches:
        rhs = _instantiate(egraph, rule.rhs, subst)
        if rhs is None:
            continue
        a = egraph.find(eid)
        b = egraph.find(rhs)
        if a != b:
            egraph.merge(a, b)
            merged = True
    return merged


def _constant_fold(egraph):
    merged = False
    for eid in egraph.all_eclasses():
        for en in list(egraph.eclass_enodes(eid)):
            if en[0] != "op":
                continue
            _, op, lid, rid = en
            lid, rid = egraph.find(lid), egraph.find(rid)
            lval = rval = None
            for ln in egraph.eclass_enodes(lid):
                if ln[0] == "num":
                    lval = ln[1]
                    break
            for rn in egraph.eclass_enodes(rid):
                if rn[0] == "num":
                    rval = rn[1]
                    break
            if lval is not None and rval is not None:
                if op == "+":
                    res = lval + rval
                elif op == "*":
                    res = lval * rval
                else:
                    continue
                res_id = egraph._add_enode(("num", res))
                if res_id is None:
                    continue
                a, b = egraph.find(eid), egraph.find(res_id)
                if a != b:
                    egraph.merge(a, b)
                    merged = True
    return merged


# ======================================================================
# Extraction
# ======================================================================

def _extract(egraph, eid):
    """Extract cheapest Expr from an e-class (cost = AST node count)."""
    memo = {}

    def go(eid):
        eid = egraph.find(eid)
        if eid in memo:
            return memo[eid]
        memo[eid] = (float("inf"), None)  # cycle sentinel

        best_c, best_e = float("inf"), None
        for en in egraph.eclass_enodes(eid):
            if en[0] == "num":
                c, e = 1, Num(en[1])
            elif en[0] == "var":
                c, e = 1, Var(en[1])
            elif en[0] == "op":
                lc, le = go(egraph.find(en[2]))
                rc, re = go(egraph.find(en[3]))
                if le is None or re is None:
                    continue
                c = 1 + lc + rc
                e = BinOp(en[1], le, re)
            else:
                continue
            if c < best_c:
                best_c, best_e = c, e

        memo[eid] = (best_c, best_e)
        return memo[eid]

    _, expr = go(eid)
    return expr


# ======================================================================
# Public entry point
# ======================================================================

def optimize(expr_str, rules, iter_limit=30):
    """Parse, saturate, extract the cheapest equivalent expression."""
    expr = parse(expr_str)
    eg = EGraph()
    root = eg.add_expr(expr)

    for _ in range(iter_limit):
        if eg._next >= _NODE_LIMIT:
            break
        changed = _apply_rules(eg, rules)
        changed |= _constant_fold(eg)
        eg.rebuild()
        if not changed:
            break

    result = _extract(eg, root)
    return result if result is not None else expr
