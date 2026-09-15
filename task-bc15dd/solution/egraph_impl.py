"""
E-Graph Equality Saturation Optimizer

Implements an e-graph with union-find, e-matching, equality saturation,
and cost-based extraction for arithmetic expression optimization.

"""

import sys
import json
from collections import defaultdict


# =================================================================
# S-expression parser and printer
# =================================================================

def tokenize(s):
    return s.replace('(', ' ( ').replace(')', ' ) ').split()


def parse_sexpr(s):
    """Parse S-expression string to tree.
    Returns (op, [children]) for operations,
            ('const', val) for constants,
            ('var', name) for variables.
    """
    tokens = tokenize(s)
    tree, _ = _parse(tokens, 0)
    return tree


def _parse(tokens, pos):
    if tokens[pos] == '(':
        op = tokens[pos + 1]
        children = []
        pos += 2
        while tokens[pos] != ')':
            child, pos = _parse(tokens, pos)
            children.append(child)
        return (op, children), pos + 1
    else:
        tok = tokens[pos]
        try:
            return ('const', int(tok)), pos + 1
        except ValueError:
            return ('var', tok), pos + 1


def tree_to_sexpr(tree):
    """Convert tree back to S-expression string."""
    if tree[0] == 'const':
        return str(tree[1])
    elif tree[0] == 'var':
        return tree[1]
    else:
        op, children = tree[0], tree[1]
        return '(' + op + ' ' + ' '.join(tree_to_sexpr(c) for c in children) + ')'


# =================================================================
# E-Graph data structure
# =================================================================

class EGraph:
    def __init__(self):
        self._parent = {}
        self._rank = {}
        self._classes = {}       # canonical eid -> set of enodes
        self._hashcons = {}      # enode (tuple) -> eid
        self._next_id = 0

    def _new_id(self):
        eid = self._next_id
        self._next_id += 1
        self._parent[eid] = eid
        self._rank[eid] = 0
        self._classes[eid] = set()
        return eid

    def find(self, eid):
        """Find root with path compression."""
        root = eid
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[eid] != root:
            nxt = self._parent[eid]
            self._parent[eid] = root
            eid = nxt
        return root

    def _union(self, a, b):
        """Union by rank, merging eclass node sets."""
        a, b = self.find(a), self.find(b)
        if a == b:
            return a
        if self._rank[a] < self._rank[b]:
            a, b = b, a
        self._parent[b] = a
        if self._rank[a] == self._rank[b]:
            self._rank[a] += 1
        self._classes[a] = self._classes.get(a, set()) | self._classes.get(b, set())
        if b in self._classes:
            del self._classes[b]
        return a

    def canonicalize(self, enode):
        """Canonicalize enode by resolving children to roots."""
        label, children = enode
        return (label, tuple(self.find(c) for c in children))

    def add_enode(self, enode):
        """Add enode, returning its eclass id (existing or new)."""
        enode = self.canonicalize(enode)
        if enode in self._hashcons:
            return self.find(self._hashcons[enode])
        eid = self._new_id()
        self._classes[eid].add(enode)
        self._hashcons[enode] = eid
        return eid

    def add_expr(self, tree):
        """Add a parsed expression tree, returning root eclass id."""
        if tree[0] == 'const':
            return self.add_enode(('c:{}'.format(tree[1]), ()))
        elif tree[0] == 'var':
            return self.add_enode(('v:{}'.format(tree[1]), ()))
        else:
            op, children = tree[0], tree[1]
            child_eids = tuple(self.add_expr(c) for c in children)
            return self.add_enode((op, child_eids))

    def merge(self, a, b):
        """Merge two eclasses, return canonical id."""
        return self._union(a, b)

    def rebuild(self):
        """Restore congruence closure invariant."""
        for _safety in range(100):
            new_hashcons = {}
            to_merge = []
            for enode, eid in self._hashcons.items():
                canon = self.canonicalize(enode)
                canon_eid = self.find(eid)
                if canon in new_hashcons:
                    existing = self.find(new_hashcons[canon])
                    if existing != canon_eid:
                        to_merge.append((existing, canon_eid))
                else:
                    new_hashcons[canon] = canon_eid
            self._hashcons = new_hashcons

            # Rebuild class sets with canonical keys and enodes
            new_classes = defaultdict(set)
            for eid, enodes in self._classes.items():
                root = self.find(eid)
                for en in enodes:
                    new_classes[root].add(self.canonicalize(en))
            self._classes = dict(new_classes)

            if not to_merge:
                break
            for a, b in to_merge:
                self._union(a, b)

    def eclass_ids(self):
        """All canonical eclass ids."""
        return list(self._classes.keys())

    def enodes_in(self, eid):
        """Enodes in the given eclass."""
        eid = self.find(eid)
        return self._classes.get(eid, set())


# =================================================================
# Pattern representation and parsing
# =================================================================

class PVar:
    __slots__ = ('name',)
    def __init__(self, name):
        self.name = name

class PNode:
    __slots__ = ('label', 'children')
    def __init__(self, label, children):
        self.label = label
        self.children = children

class PConst:
    __slots__ = ('value',)
    def __init__(self, value):
        self.value = value


def parse_pattern(s):
    tokens = tokenize(s)
    pat, _ = _parse_pat(tokens, 0)
    return pat


def _parse_pat(tokens, pos):
    if tokens[pos] == '(':
        label = tokens[pos + 1]
        children = []
        pos += 2
        while tokens[pos] != ')':
            child, pos = _parse_pat(tokens, pos)
            children.append(child)
        return PNode(label, children), pos + 1
    elif tokens[pos].startswith('?'):
        return PVar(tokens[pos][1:]), pos + 1
    else:
        return PConst(int(tokens[pos])), pos + 1


# =================================================================
# E-matching
# =================================================================

def ematch_all(egraph, pattern):
    """Find all (eclass_id, substitution) matches for pattern."""
    results = []
    for eid in egraph.eclass_ids():
        for subst in _ematch_ec(egraph, pattern, eid, {}):
            results.append((eid, subst))
    return results


def _ematch_ec(egraph, pat, eid, subst):
    """Match pattern against eclass. Yields substitutions."""
    eid = egraph.find(eid)
    if isinstance(pat, PVar):
        if pat.name in subst:
            if egraph.find(subst[pat.name]) == eid:
                yield dict(subst)
        else:
            s = dict(subst)
            s[pat.name] = eid
            yield s
    elif isinstance(pat, PConst):
        target = 'c:{}'.format(pat.value)
        for enode in egraph.enodes_in(eid):
            if enode[0] == target and len(enode[1]) == 0:
                yield dict(subst)
                break
    elif isinstance(pat, PNode):
        for enode in egraph.enodes_in(eid):
            label, children = enode
            if label == pat.label and len(children) == len(pat.children):
                yield from _ematch_children(egraph, pat.children, children, 0, subst)


def _ematch_children(egraph, pats, eids, idx, subst):
    """Recursively match pattern children against enode children."""
    if idx == len(pats):
        yield dict(subst)
        return
    for s in _ematch_ec(egraph, pats[idx], eids[idx], subst):
        yield from _ematch_children(egraph, pats, eids, idx + 1, s)


# =================================================================
# Rule application helpers
# =================================================================

def build_rhs(egraph, pat, subst):
    """Construct the RHS of a rewrite rule in the egraph."""
    if isinstance(pat, PVar):
        return subst[pat.name]
    elif isinstance(pat, PConst):
        return egraph.add_enode(('c:{}'.format(pat.value), ()))
    elif isinstance(pat, PNode):
        child_eids = tuple(build_rhs(egraph, c, subst) for c in pat.children)
        return egraph.add_enode((pat.label, child_eids))


# =================================================================
# Rewrite rules
# =================================================================

RULES = []

def rule(lhs_s, rhs_s):
    RULES.append((parse_pattern(lhs_s), parse_pattern(rhs_s)))

# Commutativity
rule("(+ ?a ?b)", "(+ ?b ?a)")
rule("(* ?a ?b)", "(* ?b ?a)")

# Associativity
rule("(+ (+ ?a ?b) ?c)", "(+ ?a (+ ?b ?c))")
rule("(+ ?a (+ ?b ?c))", "(+ (+ ?a ?b) ?c)")
rule("(* (* ?a ?b) ?c)", "(* ?a (* ?b ?c))")
rule("(* ?a (* ?b ?c))", "(* (* ?a ?b) ?c)")

# Factoring (reverse distributivity)
rule("(+ (* ?a ?b) (* ?a ?c))", "(* ?a (+ ?b ?c))")

# Identity
rule("(+ ?a 0)", "?a")
rule("(* ?a 1)", "?a")

# Zero
rule("(* ?a 0)", "0")

# Double
rule("(+ ?a ?a)", "(* ?a 2)")

# Strength reduction
rule("(* ?a 2)", "(<< ?a 1)")
rule("(* ?a 4)", "(<< ?a 2)")
rule("(* ?a 8)", "(<< ?a 3)")
rule("(* ?a 16)", "(<< ?a 4)")
rule("(* ?a 32)", "(<< ?a 5)")


# =================================================================
# Constant folding
# =================================================================

def _get_const(egraph, eid):
    """If eclass contains a constant, return its value."""
    eid = egraph.find(eid)
    for enode in egraph.enodes_in(eid):
        label, children = enode
        if label.startswith('c:') and len(children) == 0:
            return int(label[2:])
    return None


def apply_constant_folding(egraph):
    """Fold constant sub-expressions."""
    for eid in list(egraph.eclass_ids()):
        for enode in list(egraph.enodes_in(eid)):
            label, children = enode
            if label in ('+', '*') and len(children) == 2:
                v0 = _get_const(egraph, children[0])
                v1 = _get_const(egraph, children[1])
                if v0 is not None and v1 is not None:
                    result = v0 + v1 if label == '+' else v0 * v1
                    result_eid = egraph.add_enode(('c:{}'.format(result), ()))
                    egraph.merge(egraph.find(eid), result_eid)


# =================================================================
# Cost-based extraction
# =================================================================

COST_TABLE = {'+': 3, '*': 6, '<<': 2}

def extract_min_cost(egraph, root_eid):
    """Extract minimum-cost expression from an eclass."""
    best_cost = {}
    best_node = {}
    INF = float('inf')

    # Iterative fixpoint computation
    for _ in range(200):
        changed = False
        for eid in egraph.eclass_ids():
            eid_c = egraph.find(eid)
            for enode in egraph.enodes_in(eid_c):
                label, children = enode
                if label.startswith('c:') or label.startswith('v:'):
                    cost = 1
                else:
                    op_cost = COST_TABLE.get(label, 100)
                    child_costs = []
                    ok = True
                    for c in children:
                        cc = best_cost.get(egraph.find(c), INF)
                        if cc >= INF:
                            ok = False
                            break
                        child_costs.append(cc)
                    if not ok:
                        continue
                    cost = op_cost + sum(child_costs)

                if cost < best_cost.get(eid_c, INF):
                    best_cost[eid_c] = cost
                    best_node[eid_c] = enode
                    changed = True
        if not changed:
            break

    def recon(eid):
        eid = egraph.find(eid)
        enode = best_node[eid]
        label, children = enode
        if label.startswith('c:'):
            return ('const', int(label[2:]))
        elif label.startswith('v:'):
            return ('var', label[2:])
        else:
            return (label, [recon(egraph.find(c)) for c in children])

    return recon(egraph.find(root_eid))


# =================================================================
# Main optimize function
# =================================================================

def optimize(expr_str, max_iter=50, max_nodes=5000):
    """Optimize an S-expression using equality saturation."""
    tree = parse_sexpr(expr_str)
    eg = EGraph()
    root = eg.add_expr(tree)

    for _ in range(max_iter):
        # Pre-iteration constant folding
        apply_constant_folding(eg)
        eg.rebuild()

        # Collect all rule matches on current e-graph state
        to_apply = []
        for lhs, rhs in RULES:
            for eid, subst in ematch_all(eg, lhs):
                to_apply.append((eid, rhs, subst))
                if len(to_apply) > 5000:
                    break
            if len(to_apply) > 5000:
                break

        # Apply all collected matches
        changed = False
        for eid, rhs, subst in to_apply:
            rhs_eid = build_rhs(eg, rhs, subst)
            if eg.find(eid) != eg.find(rhs_eid):
                eg.merge(eid, rhs_eid)
                changed = True

        eg.rebuild()

        # Post-iteration constant folding
        pre_size = len(eg._hashcons)
        apply_constant_folding(eg)
        eg.rebuild()
        cf_changed = len(eg._hashcons) != pre_size

        if not changed and not cf_changed:
            break

        if len(eg._hashcons) > max_nodes:
            break

    result_tree = extract_min_cost(eg, root)
    return tree_to_sexpr(result_tree)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        print(optimize(sys.argv[1]))
    else:
        with open('/app/benchmarks.json') as f:
            data = json.load(f)
        for b in data['benchmarks']:
            result = optimize(b['expr'])
            print('Benchmark {}: {} => {}'.format(b['id'], b['expr'], result))
