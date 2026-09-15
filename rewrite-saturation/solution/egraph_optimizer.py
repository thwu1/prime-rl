#!/usr/bin/env python3
"""
E-graph based expression optimizer using equality saturation.

Reads an S-expression from a file, applies rewrite rules via equality
saturation over an e-graph, and extracts the lowest-cost equivalent
expression under the given cost model. Additionally generates LLVM IR
code and SMT-LIB2 equivalence proofs.
"""

import json
import os
import sys


# ===================== S-Expression Parser =====================

def tokenize(s):
    tokens = []
    i = 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
        elif c == '(':
            tokens.append('(')
            i += 1
        elif c == ')':
            tokens.append(')')
            i += 1
        elif c == ';':
            while i < len(s) and s[i] != '\n':
                i += 1
        else:
            j = i
            while j < len(s) and not s[j].isspace() and s[j] not in '()':
                j += 1
            tok = s[i:j]
            i = j
            try:
                tokens.append(int(tok))
            except ValueError:
                tokens.append(tok)
    return tokens


def parse_sexp(s):
    tokens = tokenize(s)
    if not tokens:
        raise ValueError("Empty expression")
    result, pos = _parse_at(tokens, 0)
    return result


def _parse_at(tokens, pos):
    if pos >= len(tokens):
        raise ValueError("Unexpected end of input")
    if tokens[pos] == '(':
        pos += 1
        items = []
        while pos < len(tokens) and tokens[pos] != ')':
            item, pos = _parse_at(tokens, pos)
            items.append(item)
        if pos >= len(tokens):
            raise ValueError("Missing closing paren")
        return items, pos + 1
    elif tokens[pos] == ')':
        raise ValueError("Unexpected )")
    else:
        return tokens[pos], pos + 1


def sexp_to_str(sexp):
    if isinstance(sexp, list):
        return '(' + ' '.join(sexp_to_str(x) for x in sexp) + ')'
    return str(sexp)


# ===================== Variable Extraction =====================

def _collect_vars(sexp, result):
    if isinstance(sexp, int):
        return
    if isinstance(sexp, str):
        result.add(sexp)
        return
    for child in sexp[1:]:
        _collect_vars(child, result)


def extract_vars(sexp):
    """Extract sorted list of variable names from an expression."""
    vs = set()
    _collect_vars(sexp, vs)
    return sorted(vs)


# ===================== E-Graph =====================

class EGraph:
    def __init__(self):
        self._parent = {}
        self._rank = {}
        self._nodes = {}       # eid -> set of enodes (tuples, ints, or strs)
        self._hashcons = {}    # enode -> eid
        self._analysis = {}    # eid -> int (constant value) or absent
        self._next_id = 0

    def _new_id(self):
        eid = self._next_id
        self._next_id += 1
        self._parent[eid] = eid
        self._rank[eid] = 0
        self._nodes[eid] = set()
        return eid

    def find(self, x):
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def _canon(self, node):
        if not isinstance(node, tuple):
            return node
        return tuple(
            self.find(c) if isinstance(c, int) and c in self._parent else c
            for c in node
        )

    def add_node(self, node):
        node = self._canon(node)
        if node in self._hashcons:
            return self.find(self._hashcons[node])
        eid = self._new_id()
        self._nodes[eid].add(node)
        self._hashcons[node] = eid
        self._run_analysis(eid, node)
        return eid

    def merge(self, a, b):
        a, b = self.find(a), self.find(b)
        if a == b:
            return a
        if self._rank[a] < self._rank[b]:
            a, b = b, a
        self._parent[b] = a
        if self._rank[a] == self._rank[b]:
            self._rank[a] += 1
        self._nodes[a] |= self._nodes.get(b, set())
        if b in self._nodes:
            del self._nodes[b]
        if b in self._analysis:
            if a not in self._analysis:
                self._analysis[a] = self._analysis[b]
            del self._analysis[b]
        return a

    def rebuild(self):
        while True:
            new_hc = {}
            merged = False
            for node, eid in list(self._hashcons.items()):
                root = self.find(eid)
                canon = self._canon(node)
                if canon in new_hc:
                    existing = self.find(new_hc[canon])
                    if existing != root:
                        self.merge(existing, root)
                        merged = True
                else:
                    new_hc[canon] = root
            self._hashcons = new_hc
            new_nodes = {}
            for eid, ns in list(self._nodes.items()):
                r = self.find(eid)
                if r not in new_nodes:
                    new_nodes[r] = set()
                for n in ns:
                    new_nodes[r].add(self._canon(n))
            self._nodes = new_nodes
            if not merged:
                break

    def _run_analysis(self, eid, node):
        if isinstance(node, int):
            self._analysis[eid] = node
            return
        if isinstance(node, str) or not isinstance(node, tuple):
            return
        op = node[0]
        if len(node) == 3:
            lv = self._analysis.get(self.find(node[1]))
            rv = self._analysis.get(self.find(node[2]))
            if lv is not None and rv is not None:
                val = _eval_op(op, lv, rv)
                if val is not None:
                    self._analysis[eid] = val
        elif len(node) == 2 and op == 'neg':
            cv = self._analysis.get(self.find(node[1]))
            if cv is not None:
                self._analysis[eid] = -cv

    def propagate_constants(self):
        changed = True
        while changed:
            changed = False
            for eid in list(self._nodes.keys()):
                eid = self.find(eid)
                if eid not in self._nodes:
                    continue
                if eid not in self._analysis:
                    for node in list(self._nodes.get(eid, [])):
                        self._run_analysis(eid, node)
                        if eid in self._analysis:
                            changed = True
                            break
                if eid in self._analysis:
                    val = self._analysis[eid]
                    if isinstance(val, int) and val not in self._nodes.get(eid, set()):
                        self._nodes.setdefault(eid, set()).add(val)
                        if val in self._hashcons:
                            other = self.find(self._hashcons[val])
                            if other != self.find(eid):
                                self.merge(other, eid)
                                changed = True
                        else:
                            self._hashcons[val] = self.find(eid)
                        changed = True

    def add_sexp(self, sexp):
        if isinstance(sexp, (int, str)):
            return self.add_node(sexp)
        if isinstance(sexp, list):
            children = [self.add_sexp(c) for c in sexp[1:]]
            return self.add_node(tuple([sexp[0]] + children))
        raise ValueError(f"Bad sexp: {sexp}")

    def eclasses(self):
        seen = set()
        for eid in list(self._nodes.keys()):
            r = self.find(eid)
            if r not in seen:
                seen.add(r)
                yield r

    def get_nodes(self, eid):
        return self._nodes.get(self.find(eid), set())


def _eval_op(op, a, b):
    if op == '+': return a + b
    if op == '-': return a - b
    if op == '*': return a * b
    if op == '/' and b != 0: return a // b
    if op == '<<' and 0 <= b <= 64: return a << b
    if op == '>>' and 0 <= b <= 64: return a >> b
    return None


# ===================== Pattern Matching =====================

class PVar:
    __slots__ = ('name',)
    def __init__(self, name):
        self.name = name

class PConst:
    __slots__ = ('value',)
    def __init__(self, value):
        self.value = value

class PNode:
    __slots__ = ('op', 'children')
    def __init__(self, op, children):
        self.op = op
        self.children = children


def parse_pattern(sexp):
    if isinstance(sexp, int):
        return PConst(sexp)
    if isinstance(sexp, str):
        return PVar(sexp) if sexp.startswith('?') else PConst(sexp)
    if isinstance(sexp, list):
        return PNode(sexp[0], [parse_pattern(c) for c in sexp[1:]])
    raise ValueError(f"Bad pattern sexp: {sexp}")


def ematch(eg, pat, eid, visited=None):
    """Match pattern against eclass, with cycle detection via visited set."""
    eid = eg.find(eid)
    if isinstance(pat, PVar):
        return [{pat.name: eid}]
    if isinstance(pat, PConst):
        for node in eg.get_nodes(eid):
            if node == pat.value:
                return [{}]
        return []
    if isinstance(pat, PNode):
        if visited is not None and eid in visited:
            return []
        new_visited = frozenset({eid}) if visited is None else visited | {eid}
        results = []
        for node in eg.get_nodes(eid):
            if not isinstance(node, tuple):
                continue
            if node[0] != pat.op or len(node) - 1 != len(pat.children):
                continue
            child_subs = [ematch(eg, pat.children[i], eg.find(node[i + 1]), new_visited)
                          for i in range(len(pat.children))]
            combined = [{}]
            for cs in child_subs:
                nxt = []
                for ex in combined:
                    for s in cs:
                        m = _merge_sub(eg, ex, s)
                        if m is not None:
                            nxt.append(m)
                combined = nxt
                if not combined:
                    break
            results.extend(combined)
        return results
    return []


def _merge_sub(eg, s1, s2):
    r = dict(s1)
    for k, v in s2.items():
        if k in r:
            if eg.find(r[k]) != eg.find(v):
                return None
        else:
            r[k] = v
    return r


def apply_pat(eg, pat, sub):
    if isinstance(pat, PVar):
        return sub[pat.name]
    if isinstance(pat, PConst):
        return eg.add_node(pat.value)
    if isinstance(pat, PNode):
        children = [apply_pat(eg, c, sub) for c in pat.children]
        return eg.add_node(tuple([pat.op] + children))
    raise ValueError("Bad pattern")


# ===================== Saturation =====================

def saturate(eg, rules, root, max_iter=30, max_nodes=10000):
    for _ in range(max_iter):
        eg.rebuild()
        eg.propagate_constants()
        eg.rebuild()

        total = sum(len(ns) for ns in eg._nodes.values())
        if total > max_nodes:
            break

        matches = []
        for _name, lhs, rhs in rules:
            for eid in list(eg.eclasses()):
                for sub in ematch(eg, lhs, eid):
                    matches.append((eg.find(eid), rhs, sub))

        if not matches:
            break

        new_merges = 0
        for eid, rhs, sub in matches:
            new_eid = apply_pat(eg, rhs, sub)
            a, b = eg.find(eid), eg.find(new_eid)
            if a != b:
                eg.merge(a, b)
                new_merges += 1

        if new_merges == 0:
            break

    eg.rebuild()
    eg.propagate_constants()
    eg.rebuild()
    return eg.find(root)


# ===================== Extraction =====================

def extract(eg, root, cost_model):
    op_costs = cost_model.get('op_costs', {})
    memo = {}

    def best(eid, depth):
        eid = eg.find(eid)
        if eid in memo:
            return memo[eid]
        if depth > 100:
            return (float('inf'), None)
        memo[eid] = (float('inf'), None)  # cycle guard

        best_c, best_e = float('inf'), None
        for node in eg.get_nodes(eid):
            if isinstance(node, int):
                if 0 < best_c:
                    best_c, best_e = 0, node
            elif isinstance(node, str):
                if 0 < best_c:
                    best_c, best_e = 0, node
            elif isinstance(node, tuple):
                oc = op_costs.get(node[0], 1)
                children = [best(eg.find(node[i + 1]), depth + 1)
                            for i in range(len(node) - 1)]
                total = oc + sum(c[0] for c in children)
                if total < best_c and all(c[1] is not None for c in children):
                    best_c = total
                    best_e = [node[0]] + [c[1] for c in children]
        memo[eid] = (best_c, best_e)
        return (best_c, best_e)

    _, expr = best(eg.find(root), 0)
    return expr


# ===================== LLVM IR Generation =====================

def generate_llvm_ir(optimized_sexp, var_names):
    """Generate LLVM IR text for the optimized expression."""
    counter = [0]
    instructions = []

    llvm_op_map = {
        '+': 'add', '-': 'sub', '*': 'mul',
        '/': 'sdiv', '<<': 'shl', '>>': 'ashr',
    }

    def emit(expr):
        if isinstance(expr, int):
            return str(expr)
        if isinstance(expr, str):
            return '%' + expr
        op = expr[0]
        if op == 'neg':
            child_val = emit(expr[1])
            reg = '%t' + str(counter[0])
            counter[0] += 1
            instructions.append('  ' + reg + ' = sub i64 0, ' + child_val)
            return reg
        left_val = emit(expr[1])
        right_val = emit(expr[2])
        reg = '%t' + str(counter[0])
        counter[0] += 1
        instructions.append(
            '  ' + reg + ' = ' + llvm_op_map[op] + ' i64 ' + left_val + ', ' + right_val
        )
        return reg

    result_val = emit(optimized_sexp)

    params = ', '.join('i64 %' + v for v in var_names)
    lines = ['define i64 @optimized(' + params + ') {']
    lines.append('entry:')
    lines.extend(instructions)
    lines.append('  ret i64 ' + result_val)
    lines.append('}')
    return '\n'.join(lines) + '\n'


# ===================== SMT-LIB2 Generation =====================

def generate_smt2(original_sexp, optimized_sexp, var_names):
    """Generate SMT-LIB2 script proving equivalence over 64-bit bitvectors."""
    smt_op_map = {
        '+': 'bvadd', '-': 'bvsub', '*': 'bvmul',
        '/': 'bvsdiv', '<<': 'bvshl', '>>': 'bvashr',
        'neg': 'bvneg',
    }

    def to_smt(expr):
        if isinstance(expr, int):
            if expr >= 0:
                return '(_ bv' + str(expr) + ' 64)'
            else:
                return '(bvneg (_ bv' + str(-expr) + ' 64))'
        if isinstance(expr, str):
            return expr
        op = expr[0]
        smt_op = smt_op_map[op]
        if op == 'neg':
            return '(' + smt_op + ' ' + to_smt(expr[1]) + ')'
        return '(' + smt_op + ' ' + to_smt(expr[1]) + ' ' + to_smt(expr[2]) + ')'

    lines = ['(set-logic QF_BV)']
    for v in var_names:
        lines.append('(declare-const ' + v + ' (_ BitVec 64))')
    orig_smt = to_smt(original_sexp)
    opt_smt = to_smt(optimized_sexp)
    lines.append('(assert (not (= ' + orig_smt + ' ' + opt_smt + ')))')
    lines.append('(check-sat)')
    lines.append('(exit)')
    return '\n'.join(lines) + '\n'


# ===================== Main =====================

def load_rules(path):
    with open(path) as f:
        data = json.load(f)
    rules = []
    for r in data['rules']:
        lhs = parse_pattern(parse_sexp(r['lhs']))
        rhs = parse_pattern(parse_sexp(r['rhs']))
        rules.append((r.get('name', ''), lhs, rhs))
    return rules


def main():
    if len(sys.argv) < 2:
        print("Usage: optimize.py <expr_file>", file=sys.stderr)
        sys.exit(1)

    rules = load_rules('/opt/eqsat/rules.json')
    with open('/opt/eqsat/cost_model.json') as f:
        cost_model = json.load(f)
    with open(sys.argv[1]) as f:
        expr_str = f.read().strip()

    sexp = parse_sexp(expr_str)
    var_names = extract_vars(sexp)

    eg = EGraph()
    root = eg.add_sexp(sexp)
    root = saturate(eg, rules, root)
    optimized = extract(eg, root, cost_model)

    # Print optimized S-expression to stdout
    print(sexp_to_str(optimized))

    # Generate output files
    basename = os.path.splitext(os.path.basename(sys.argv[1]))[0]
    os.makedirs('/app/output', exist_ok=True)

    # LLVM IR
    llvm_ir = generate_llvm_ir(optimized, var_names)
    with open('/app/output/' + basename + '.ll', 'w') as f:
        f.write(llvm_ir)

    # SMT-LIB2 equivalence proof
    smt2 = generate_smt2(sexp, optimized, var_names)
    with open('/app/output/' + basename + '.smt2', 'w') as f:
        f.write(smt2)


if __name__ == '__main__':
    main()
