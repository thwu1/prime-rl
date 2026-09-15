#!/usr/bin/env python3

"""
Magma equational theory lattice analyzer.

Uses Z3 for order-4 counterexample search, Graphviz for Hasse diagram
rendering, and computes duality and lattice-theoretic properties.
"""

import json
import itertools
import os
import subprocess
import sys


# =======================================================================
# Equation parsing: infix with *, parens, single-letter variables
# =======================================================================

def tokenize(s):
    tokens = []
    for ch in s:
        if ch.isspace():
            continue
        elif ch in '()*=':
            tokens.append(ch)
        elif ch.isalpha():
            tokens.append(ch)
        else:
            raise ValueError(f"Unexpected character: {ch!r}")
    return tokens


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def consume(self, expected=None):
        tok = self.tokens[self.pos]
        if expected is not None and tok != expected:
            raise ValueError(f"Expected {expected!r}, got {tok!r}")
        self.pos += 1
        return tok

    def parse_primary(self):
        if self.peek() == '(':
            self.consume('(')
            node = self.parse_expr()
            self.consume(')')
            return node
        else:
            return ('var', self.consume())

    def parse_expr(self):
        left = self.parse_primary()
        while self.peek() == '*':
            self.consume('*')
            right = self.parse_primary()
            left = ('op', left, right)
        return left


def parse_equation(s):
    tokens = tokenize(s)
    p = Parser(tokens)
    lhs = p.parse_expr()
    p.consume('=')
    rhs = p.parse_expr()
    return lhs, rhs


# =======================================================================
# AST utilities
# =======================================================================

def get_variables(node):
    if node[0] == 'var':
        return {node[1]}
    return get_variables(node[1]) | get_variables(node[2])


def get_variables_ordered(node, result=None, seen=None):
    """Collect variables in left-to-right order of first appearance."""
    if result is None:
        result, seen = [], set()
    if node[0] == 'var':
        if node[1] not in seen:
            result.append(node[1])
            seen.add(node[1])
    else:
        get_variables_ordered(node[1], result, seen)
        get_variables_ordered(node[2], result, seen)
    return result


def evaluate(node, env, table):
    if node[0] == 'var':
        return env[node[1]]
    l = evaluate(node[1], env, table)
    r = evaluate(node[2], env, table)
    return table[l][r]


def satisfies(lhs, rhs, table):
    n = len(table)
    variables = sorted(get_variables(lhs) | get_variables(rhs))
    for vals in itertools.product(range(n), repeat=len(variables)):
        env = dict(zip(variables, vals))
        if evaluate(lhs, env, table) != evaluate(rhs, env, table):
            return False
    return True


# =======================================================================
# Magma enumeration (orders 1-3)
# =======================================================================

def enumerate_magmas(n):
    for values in itertools.product(range(n), repeat=n * n):
        yield [list(values[i * n:(i + 1) * n]) for i in range(n)]


# =======================================================================
# Z3-based order-4 counterexample search
# =======================================================================

def z3_search_counterexample(eq_src, eq_tgt, n):
    """
    Use Z3 to find an order-n magma satisfying eq_src but violating eq_tgt.
    Returns the operation table if found, None otherwise.
    """
    from z3 import Solver, Int, And, Or, If, sat, IntVal

    s = Solver()
    s.set("timeout", 60000)  # 60 second timeout per query

    # Create table variables
    M = [[Int(f'm_{i}_{j}') for j in range(n)] for i in range(n)]
    for i in range(n):
        for j in range(n):
            s.add(And(M[i][j] >= 0, M[i][j] < n))

    def eval_z3(node, env):
        """Evaluate AST node with Z3 expressions."""
        if node[0] == 'var':
            return env[node[1]]
        l_val = eval_z3(node[1], env)
        r_val = eval_z3(node[2], env)

        if isinstance(l_val, int) and isinstance(r_val, int):
            return M[l_val][r_val]

        # Build If-Then-Else chain for symbolic table lookup
        result = M[0][0]
        for i in range(n):
            for j in range(n):
                if i == 0 and j == 0:
                    continue
                result = If(And(l_val == i, r_val == j), M[i][j], result)
        return result

    # Source equation must hold for ALL variable assignments
    src_lhs, src_rhs = eq_src
    src_vars = sorted(get_variables(src_lhs) | get_variables(src_rhs))
    for vals in itertools.product(range(n), repeat=len(src_vars)):
        env = dict(zip(src_vars, vals))
        lv = eval_z3(src_lhs, env)
        rv = eval_z3(src_rhs, env)
        s.add(lv == rv)

    # Target equation must be violated for at least one assignment
    tgt_lhs, tgt_rhs = eq_tgt
    tgt_vars = sorted(get_variables(tgt_lhs) | get_variables(tgt_rhs))
    violations = []
    for vals in itertools.product(range(n), repeat=len(tgt_vars)):
        env = dict(zip(tgt_vars, vals))
        lv = eval_z3(tgt_lhs, env)
        rv = eval_z3(tgt_rhs, env)
        violations.append(lv != rv)
    s.add(Or(*violations))

    if s.check() == sat:
        model = s.model()
        table = [[model[M[i][j]].as_long() for j in range(n)] for i in range(n)]
        return table
    return None


# =======================================================================
# Duality computation
# =======================================================================

def dual_ast(node):
    """Compute dual of AST by swapping children of every binary-op node."""
    if node[0] == 'var':
        return node
    return ('op', dual_ast(node[2]), dual_ast(node[1]))


def rename_ast(node, mapping):
    """Rename variables in AST according to mapping."""
    if node[0] == 'var':
        return ('var', mapping[node[1]])
    return ('op', rename_ast(node[1], mapping), rename_ast(node[2], mapping))


def equations_match_up_to_renaming(eq1_lhs, eq1_rhs, eq2_lhs, eq2_rhs):
    """Check if two equations are identical up to variable renaming."""
    vars1 = get_variables_ordered(eq1_lhs) + [
        v for v in get_variables_ordered(eq1_rhs)
        if v not in get_variables_ordered(eq1_lhs)
    ]
    vars1 = list(dict.fromkeys(vars1))
    vars2_set = get_variables(eq2_lhs) | get_variables(eq2_rhs)
    vars2 = sorted(vars2_set)

    if len(vars1) != len(vars2):
        return False

    for perm in itertools.permutations(vars2):
        mapping = dict(zip(vars1, perm))
        renamed_lhs = rename_ast(eq1_lhs, mapping)
        renamed_rhs = rename_ast(eq1_rhs, mapping)
        # Check both orientations (equation is symmetric: a=b iff b=a)
        if (renamed_lhs, renamed_rhs) == (eq2_lhs, eq2_rhs):
            return True
        if (renamed_rhs, renamed_lhs) == (eq2_lhs, eq2_rhs):
            return True
    return False


def compute_duality(equations):
    """
    For each equation, compute its dual and find matching equation.
    Returns dict: eq_id -> {"dual_id": str|None, "self_dual": bool}
    """
    parsed = {}
    for eq in equations:
        lhs, rhs = parse_equation(eq['law'])
        parsed[eq['id']] = (lhs, rhs)

    result = {}
    eq_ids = [eq['id'] for eq in equations]

    for eid in eq_ids:
        lhs, rhs = parsed[eid]
        dual_lhs = dual_ast(lhs)
        dual_rhs = dual_ast(rhs)

        dual_id = None
        for other_id in eq_ids:
            o_lhs, o_rhs = parsed[other_id]
            if equations_match_up_to_renaming(dual_lhs, dual_rhs, o_lhs, o_rhs):
                dual_id = other_id
                break

        self_dual = (dual_id == eid)
        result[eid] = {"dual_id": dual_id, "self_dual": self_dual}

    return result


# =======================================================================
# Graphviz DOT generation and SVG rendering
# =======================================================================

def generate_dot(hasse, equations_data):
    """Generate DOT digraph for the Hasse diagram."""
    lines = ['digraph hasse {']
    lines.append('  rankdir=BT;')
    lines.append('  node [shape=box, style=filled, fillcolor=lightyellow, '
                 'fontname="Helvetica"];')
    lines.append('  edge [color=navy];')

    eq_names = {eq['id']: eq['name'] for eq in equations_data['equations']}

    for eid in sorted(eq_names.keys()):
        name = eq_names[eid].replace('_', ' ')
        lines.append(f'  {eid} [label="{eid}\\n{name}"];')

    for src in sorted(hasse.keys()):
        for tgt in sorted(hasse[src]):
            lines.append(f'  {src} -> {tgt};')

    lines.append('}')
    return '\n'.join(lines)


def render_svg(dot_path, svg_path):
    """Render DOT file to SVG using graphviz dot command."""
    result = subprocess.run(
        ['dot', '-Tsvg', dot_path, '-o', svg_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Graphviz error: {result.stderr}", file=sys.stderr)
        raise RuntimeError(f"dot command failed: {result.stderr}")


# =======================================================================
# Lattice properties computation
# =======================================================================

def compute_lattice_properties(hasse, eq_ids):
    """Compute width, height, maximal, minimal, connected components."""
    adj = {eid: list(hasse.get(eid, [])) for eid in eq_ids}

    # Transitive closure for full implication relation
    implies = {eid: {eid} for eid in eq_ids}
    for eid in eq_ids:
        stack = list(adj[eid])
        while stack:
            node = stack.pop()
            if node not in implies[eid]:
                implies[eid].add(node)
                stack.extend(adj.get(node, []))

    # Maximal elements: not a source of any Hasse edge (nothing weaker implied)
    # In the ordering Ei <= Ej iff Ei implies Ej, maximal = weakest = not implied
    # by anything strictly stronger = no incoming Hasse edges
    # Actually: maximal in poset = nothing strictly above.
    # Ei <= Ej means Ei implies Ej (Ei is at least as strong).
    # Maximal Ej: no Ej < Ek (nothing Ej implies beyond itself).
    num_maximal = sum(1 for eid in eq_ids if not adj[eid])

    # Minimal elements: not a target of any Hasse edge
    targets = set()
    for eid in eq_ids:
        targets.update(adj[eid])
    num_minimal = sum(1 for eid in eq_ids if eid not in targets)

    # Connected components (undirected Hasse graph)
    undirected = {eid: set() for eid in eq_ids}
    for eid in eq_ids:
        for tgt in adj[eid]:
            undirected[eid].add(tgt)
            undirected[tgt].add(eid)
    visited = set()
    num_cc = 0
    for eid in eq_ids:
        if eid not in visited:
            num_cc += 1
            stack = [eid]
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                stack.extend(undirected[node])

    # Width: maximum antichain size
    width = 0
    for r in range(len(eq_ids), 0, -1):
        found = False
        for subset in itertools.combinations(eq_ids, r):
            is_antichain = True
            for a, b in itertools.combinations(subset, 2):
                if b in implies[a] or a in implies[b]:
                    is_antichain = False
                    break
            if is_antichain:
                width = r
                found = True
                break
        if found:
            break

    # Height: longest chain (edges in longest path)
    memo = {}

    def longest_path_from(node):
        if node in memo:
            return memo[node]
        if not adj[node]:
            memo[node] = 0
            return 0
        best = max(1 + longest_path_from(tgt) for tgt in adj[node])
        memo[node] = best
        return best

    height = max(longest_path_from(eid) for eid in eq_ids)

    return {
        "width": width,
        "height": height,
        "num_maximal": num_maximal,
        "num_minimal": num_minimal,
        "num_connected_components": num_cc,
    }


# =======================================================================
# Main
# =======================================================================

def main():
    with open('/app/equations.json') as f:
        data = json.load(f)

    equations = []
    for eq in data['equations']:
        eid = eq['id']
        lhs, rhs = parse_equation(eq['law'])
        equations.append((eid, lhs, rhs))

    eq_ids = [e[0] for e in equations]

    # -------------------------------------------------------------------
    # Phase 1: Enumerate magmas at orders 1-3
    # -------------------------------------------------------------------
    sat_sets = {eid: set() for eid in eq_ids}
    magma_db = {}

    for order in (1, 2, 3):
        total = order ** (order * order)
        print(f"Enumerating order-{order} magmas ({total} tables)...",
              file=sys.stderr)
        for idx, table in enumerate(enumerate_magmas(order)):
            magma_db[(order, idx)] = table
            for eid, lhs, rhs in equations:
                if satisfies(lhs, rhs, table):
                    sat_sets[eid].add((order, idx))

    # -------------------------------------------------------------------
    # Phase 2: Compute spectrum (orders 1-3)
    # -------------------------------------------------------------------
    spectrum = {}
    for eid in eq_ids:
        counts = [0, 0, 0]
        for order, _ in sat_sets[eid]:
            counts[order - 1] += 1
        spectrum[eid] = counts

    # -------------------------------------------------------------------
    # Phase 3: Joint spectrum at order 3
    # -------------------------------------------------------------------
    o3 = {eid: {key for key in sat_sets[eid] if key[0] == 3} for eid in eq_ids}
    joint = {}
    for ei in eq_ids:
        joint[ei] = {}
        for ej in eq_ids:
            joint[ei][ej] = len(o3[ei] & o3[ej])

    # -------------------------------------------------------------------
    # Phase 4: Implications at order <= 3
    # -------------------------------------------------------------------
    implications_o3 = {}
    for ei in eq_ids:
        impl = []
        for ej in eq_ids:
            if sat_sets[ei].issubset(sat_sets[ej]):
                impl.append(ej)
        implications_o3[ei] = sorted(impl)

    # -------------------------------------------------------------------
    # Phase 5: Z3 order-4 verification
    # -------------------------------------------------------------------
    print("Using Z3 to verify implications at order 4...", file=sys.stderr)
    parsed_eqs = {eid: (lhs, rhs) for eid, lhs, rhs in equations}

    # For each implication at order <= 3, check if it still holds at order 4
    order4_counterexamples = {}
    implications = {eid: list(implications_o3[eid]) for eid in eq_ids}

    for ei in eq_ids:
        for ej in implications_o3[ei]:
            if ei == ej:
                continue
            print(f"  Z3 checking {ei} => {ej} at order 4...", file=sys.stderr)
            ce = z3_search_counterexample(parsed_eqs[ei], parsed_eqs[ej], 4)
            if ce is not None:
                print(f"    FOUND counterexample! {ei} does NOT imply {ej} at order 4",
                      file=sys.stderr)
                implications[ei].remove(ej)
                order4_counterexamples[(ei, ej)] = ce

    # -------------------------------------------------------------------
    # Phase 6: Counterexamples (smallest order)
    # -------------------------------------------------------------------
    counterexamples = {}
    for ei in eq_ids:
        for ej in eq_ids:
            if ei == ej:
                continue
            if ej in implications[ei]:
                continue
            # Find smallest counterexample from orders 1-3
            diff = sat_sets[ei] - sat_sets[ej]
            if diff:
                best = min(diff, key=lambda k: (k[0], k[1]))
                counterexamples[f"{ei}->{ej}"] = {
                    "order": best[0],
                    "table": magma_db[best],
                }
            elif (ei, ej) in order4_counterexamples:
                counterexamples[f"{ei}->{ej}"] = {
                    "order": 4,
                    "table": order4_counterexamples[(ei, ej)],
                }

    # -------------------------------------------------------------------
    # Phase 7: Hasse diagram (transitive reduction)
    # -------------------------------------------------------------------
    adj = {}
    for ei in eq_ids:
        adj[ei] = set()
        for ej in eq_ids:
            if ei != ej and ej in implications[ei]:
                adj[ei].add(ej)

    def reachable_without(src, tgt):
        visited = set()
        stack = [k for k in adj[src] if k != tgt]
        while stack:
            node = stack.pop()
            if node == tgt:
                return True
            if node in visited:
                continue
            visited.add(node)
            for nxt in adj[node]:
                if nxt not in visited:
                    stack.append(nxt)
        return False

    hasse = {}
    for ei in eq_ids:
        direct = [ej for ej in adj[ei] if not reachable_without(ei, ej)]
        hasse[ei] = sorted(direct)

    # -------------------------------------------------------------------
    # Phase 8: Duality
    # -------------------------------------------------------------------
    print("Computing equation duality...", file=sys.stderr)
    duality = compute_duality(data['equations'])

    # -------------------------------------------------------------------
    # Phase 9: DOT and SVG
    # -------------------------------------------------------------------
    os.makedirs('/app/results', exist_ok=True)
    print("Generating Hasse diagram DOT and SVG...", file=sys.stderr)
    dot_content = generate_dot(hasse, data)
    dot_path = '/app/results/hasse.dot'
    svg_path = '/app/results/hasse.svg'

    with open(dot_path, 'w') as f:
        f.write(dot_content)

    render_svg(dot_path, svg_path)

    # -------------------------------------------------------------------
    # Phase 10: Lattice properties
    # -------------------------------------------------------------------
    print("Computing lattice properties...", file=sys.stderr)
    lattice_props = compute_lattice_properties(hasse, eq_ids)

    # -------------------------------------------------------------------
    # Write all JSON outputs
    # -------------------------------------------------------------------

    outputs = [
        ('spectrum.json', spectrum),
        ('joint_spectrum.json', joint),
        ('implications.json', implications),
        ('counterexamples.json', counterexamples),
        ('hasse.json', hasse),
        ('duality.json', duality),
        ('lattice_properties.json', lattice_props),
    ]

    for fname, obj in outputs:
        with open(f'/app/results/{fname}', 'w') as f:
            json.dump(obj, f, indent=2)

    print("All outputs written to /app/results/", file=sys.stderr)


if __name__ == '__main__':
    main()
