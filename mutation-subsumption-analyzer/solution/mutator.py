#!/usr/bin/env python3

"""
Mutation Testing Subsumption Analyzer

Implements AOR, ROR, LCR mutation operators on the Python AST.
Builds a kill matrix, computes strict subsumption, identifies dominator mutants.
"""

import ast
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE = '/app/project/src/mathlib.py'
TESTS = '/app/project/tests/test_mathlib.py'
RESULTS = '/app/results'
TIMEOUT_PER_MUTANT = 30  # seconds

# ---------------------------------------------------------------------------
# Operator replacement tables
# ---------------------------------------------------------------------------

AOR = {
    ast.Add:      [ast.Sub, ast.Mult],
    ast.Sub:      [ast.Add, ast.Mult],
    ast.Mult:     [ast.Div, ast.Add],
    ast.Div:      [ast.Mult, ast.Sub],
    ast.Mod:      [ast.Mult, ast.Add],
    ast.FloorDiv: [ast.Mult, ast.Add],
}

ROR = {
    ast.Lt:    [ast.LtE, ast.GtE],
    ast.LtE:   [ast.Lt, ast.Gt],
    ast.Gt:    [ast.GtE, ast.LtE],
    ast.GtE:   [ast.Gt, ast.Lt],
    ast.Eq:    [ast.NotEq],
    ast.NotEq: [ast.Eq],
}

LCR = {
    ast.And: [ast.Or],
    ast.Or:  [ast.And],
}

SYM = {
    'Add': '+', 'Sub': '-', 'Mult': '*', 'Div': '/', 'Mod': '%',
    'FloorDiv': '//', 'Pow': '**',
    'Lt': '<', 'LtE': '<=', 'Gt': '>', 'GtE': '>=',
    'Eq': '==', 'NotEq': '!=',
    'And': 'and', 'Or': 'or',
}

# ---------------------------------------------------------------------------
# Mutation point collection
# ---------------------------------------------------------------------------

class Collector(ast.NodeVisitor):
    """Walk the AST and record every applicable mutation point."""

    def __init__(self):
        self.points = []
        self._func = []

    @property
    def func(self):
        return self._func[-1] if self._func else '<module>'

    def visit_FunctionDef(self, node):
        self._func.append(node.name)
        self.generic_visit(node)
        self._func.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_BinOp(self, node):
        cls = type(node.op)
        if cls in AOR:
            for repl in AOR[cls]:
                self.points.append(dict(
                    op='AOR', func=self.func,
                    line=node.lineno, col=node.col_offset,
                    orig_cls=cls, repl_cls=repl,
                    orig=SYM.get(cls.__name__, '?'),
                    repl_sym=SYM.get(repl.__name__, '?'),
                    kind='BinOp',
                ))
        self.generic_visit(node)

    def visit_Compare(self, node):
        for idx, cmp_op in enumerate(node.ops):
            cls = type(cmp_op)
            if cls in ROR:
                for repl in ROR[cls]:
                    self.points.append(dict(
                        op='ROR', func=self.func,
                        line=node.lineno, col=node.col_offset,
                        orig_cls=cls, repl_cls=repl,
                        orig=SYM.get(cls.__name__, '?'),
                        repl_sym=SYM.get(repl.__name__, '?'),
                        kind='Compare', idx=idx,
                    ))
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        cls = type(node.op)
        if cls in LCR:
            for repl in LCR[cls]:
                self.points.append(dict(
                    op='LCR', func=self.func,
                    line=node.lineno, col=node.col_offset,
                    orig_cls=cls, repl_cls=repl,
                    orig=SYM.get(cls.__name__, '?'),
                    repl_sym=SYM.get(repl.__name__, '?'),
                    kind='BoolOp',
                ))
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Mutation application
# ---------------------------------------------------------------------------

class Applier(ast.NodeTransformer):
    """Apply exactly one mutation to a fresh AST copy."""

    def __init__(self, point):
        self.p = point
        self.done = False

    def visit_BinOp(self, node):
        self.generic_visit(node)
        if (not self.done
                and self.p['kind'] == 'BinOp'
                and node.lineno == self.p['line']
                and node.col_offset == self.p['col']
                and type(node.op) == self.p['orig_cls']):
            node.op = self.p['repl_cls']()
            self.done = True
        return node

    def visit_Compare(self, node):
        self.generic_visit(node)
        if (not self.done
                and self.p['kind'] == 'Compare'
                and node.lineno == self.p['line']
                and node.col_offset == self.p['col']):
            idx = self.p['idx']
            if idx < len(node.ops) and type(node.ops[idx]) == self.p['orig_cls']:
                node.ops[idx] = self.p['repl_cls']()
                self.done = True
        return node

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        if (not self.done
                and self.p['kind'] == 'BoolOp'
                and node.lineno == self.p['line']
                and node.col_offset == self.p['col']
                and type(node.op) == self.p['orig_cls']):
            node.op = self.p['repl_cls']()
            self.done = True
        return node


def apply_mutation(source: str, point: dict) -> str | None:
    """Return mutated source string, or None on failure."""
    try:
        tree = ast.parse(source)
        applier = Applier(point)
        new_tree = applier.visit(tree)
        if not applier.done:
            return None
        ast.fix_missing_locations(new_tree)
        return ast.unparse(new_tree)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------

def get_test_names(test_file: str) -> list[str]:
    with open(test_file) as f:
        tree = ast.parse(f.read())
    return [n.name for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')]


def _parse_junit(xml_path: str) -> dict[str, bool]:
    """Parse JUnit XML -> {test_name: passed}."""
    results = {}
    try:
        root = ET.parse(xml_path).getroot()
        for tc in root.iter('testcase'):
            name = tc.get('name')
            if name:
                failed = (tc.find('failure') is not None
                          or tc.find('error') is not None)
                results[name] = not failed
    except Exception:
        pass
    return results


def run_baseline(test_file: str) -> dict[str, bool]:
    xml = '/tmp/_baseline.xml'
    try:
        subprocess.run(
            [sys.executable, '-B', '-m', 'pytest', test_file,
             f'--junit-xml={xml}', '--tb=no', '-q'],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {}
    results = _parse_junit(xml)
    if os.path.exists(xml):
        os.unlink(xml)
    return results


def run_mutant_tests(mutated_src: str, source_file: str,
                     test_file: str, test_names: list[str]) -> dict[str, bool]:
    """Run test suite against mutated source.  Returns {test: passed}."""
    backup = source_file + '._mut_bak'
    xml = f'/tmp/_mutant_{os.getpid()}.xml'

    os.rename(source_file, backup)
    try:
        with open(source_file, 'w') as f:
            f.write(mutated_src)

        try:
            subprocess.run(
                [sys.executable, '-B', '-m', 'pytest', test_file,
                 f'--junit-xml={xml}', '--tb=no', '-q'],
                capture_output=True, text=True, timeout=TIMEOUT_PER_MUTANT,
            )
        except subprocess.TimeoutExpired:
            # All tests "fail" on timeout → mutant killed
            return {t: False for t in test_names}

        results = _parse_junit(xml)
        if not results:
            # Could not parse results → treat as all failed
            return {t: False for t in test_names}
        return results
    finally:
        # Restore original source
        if os.path.exists(source_file):
            os.unlink(source_file)
        os.rename(backup, source_file)
        if os.path.exists(xml):
            os.unlink(xml)


# ---------------------------------------------------------------------------
# Subsumption analysis
# ---------------------------------------------------------------------------

def compute_subsumption(ids: list[str], matrix: list[list[int]]):
    """
    Compute strict subsumption and identify dominator (subsuming) mutants.

    A strictly subsumes B  ⟺  kill_set(A) ⊂ kill_set(B)   (proper subset)

    Dominators = killable mutants NOT strictly subsumed by any other.
    """
    # Build kill sets for killable mutants only
    kill_sets: dict[str, frozenset] = {}
    for i, mid in enumerate(ids):
        ks = frozenset(j for j, v in enumerate(matrix[i]) if v == 1)
        if ks:
            kill_sets[mid] = ks

    killable = list(kill_sets.keys())

    # Find strict subsumption edges
    edges: list[list[str]] = []
    subsumed: set[str] = set()

    for i, a in enumerate(killable):
        ks_a = kill_sets[a]
        for b in killable[i + 1:]:
            ks_b = kill_sets[b]
            if ks_a < ks_b:          # a strictly subsumes b
                edges.append([a, b])
                subsumed.add(b)
            elif ks_b < ks_a:        # b strictly subsumes a
                edges.append([b, a])
                subsumed.add(a)

    dominators = [m for m in killable if m not in subsumed]
    return edges, dominators


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    os.makedirs(RESULTS, exist_ok=True)

    # Read source
    with open(SOURCE) as f:
        source = f.read()

    original_unparsed = ast.unparse(ast.parse(source))

    # ---- Step 1: collect mutation points ----
    collector = Collector()
    collector.visit(ast.parse(source))
    points = collector.points

    for i, p in enumerate(points):
        p['id'] = f'M{i:04d}'

    print(f'[1/4] Collected {len(points)} mutation points  '
          f'(AOR={sum(1 for p in points if p["op"]=="AOR")}, '
          f'ROR={sum(1 for p in points if p["op"]=="ROR")}, '
          f'LCR={sum(1 for p in points if p["op"]=="LCR")})')

    # ---- Step 2: run baseline tests ----
    test_names = get_test_names(TESTS)
    baseline = run_baseline(TESTS)
    passing = [t for t in test_names if baseline.get(t, False)]
    print(f'[2/4] Baseline: {len(passing)}/{len(test_names)} tests pass')

    # ---- Step 3: execute mutants ----
    print(f'[3/4] Executing {len(points)} mutants ...')
    matrix: list[list[int]] = []
    statuses: list[str] = []

    for i, pt in enumerate(points):
        label = (f'  [{i+1}/{len(points)}] {pt["id"]}: {pt["op"]} '
                 f'{pt["orig"]}→{pt["repl_sym"]}  L{pt["line"]}  {pt["func"]}')

        mutated = apply_mutation(source, pt)
        if mutated is None:
            print(f'{label}  SKIP')
            matrix.append([0] * len(test_names))
            statuses.append('survived')
            continue

        # Check syntactic equivalence (trivial equivalent mutant detection)
        if mutated.strip() == original_unparsed.strip():
            print(f'{label}  EQUIVALENT')
            matrix.append([0] * len(test_names))
            statuses.append('equivalent')
            continue

        results = run_mutant_tests(mutated, SOURCE, TESTS, test_names)

        row = []
        for t in test_names:
            originally_passed = baseline.get(t, False)
            now_passed = results.get(t, True)
            if originally_passed and not now_passed:
                row.append(1)   # killed
            else:
                row.append(0)
        matrix.append(row)

        killed_by = sum(row)
        if killed_by > 0:
            statuses.append('killed')
            print(f'{label}  KILLED ({killed_by} tests)')
        else:
            statuses.append('survived')
            print(f'{label}  SURVIVED')

    # ---- Step 4: subsumption & output ----
    print('[4/4] Computing subsumption ...')
    ids = [p['id'] for p in points]
    edges, dominators = compute_subsumption(ids, matrix)

    killed = statuses.count('killed')
    survived = statuses.count('survived')
    equivalent = statuses.count('equivalent')
    timeout = statuses.count('timeout')
    total = len(points)
    denom = total - equivalent

    ops_info = {}
    for op_name in ('AOR', 'ROR', 'LCR'):
        idxs = [i for i, p in enumerate(points) if p['op'] == op_name]
        ops_info[op_name] = {
            'generated': len(idxs),
            'killed': sum(1 for i in idxs if statuses[i] == 'killed'),
        }

    sub_killed = sum(1 for d in dominators
                     if statuses[ids.index(d)] == 'killed')

    metrics = {
        'total_mutants': total,
        'killed': killed,
        'survived': survived,
        'equivalent': equivalent,
        'timeout': timeout,
        'mutation_score': round(killed / denom, 4) if denom > 0 else 0.0,
        'operators': ops_info,
        'subsuming_mutants_total': len(dominators),
        'subsuming_mutants_killed': sub_killed,
        'subsuming_mutation_score': (
            round(sub_killed / len(dominators), 4) if dominators else 0.0
        ),
    }

    # ---- Write JSON outputs ----
    mutants_out = [
        {
            'id': p['id'],
            'operator': p['op'],
            'function': p['func'],
            'line': p['line'],
            'original': p['orig'],
            'replacement': p['repl_sym'],
            'status': statuses[i],
        }
        for i, p in enumerate(points)
    ]

    _write_json('mutants.json', mutants_out)
    _write_json('kill_matrix.json', {
        'mutant_ids': ids,
        'test_names': test_names,
        'matrix': matrix,
    })
    _write_json('subsumption.json', {
        'subsuming_mutant_ids': dominators,
        'subsumption_edges': edges,
    })
    _write_json('metrics.json', metrics)

    # ---- Summary ----
    print(f'\n=== Summary ===')
    print(f'Total mutants:      {total}')
    print(f'Killed:             {killed}')
    print(f'Survived:           {survived}')
    print(f'Equivalent:         {equivalent}')
    print(f'Mutation score:     {metrics["mutation_score"]:.2%}')
    print(f'Subsuming mutants:  {len(dominators)}')
    print(f'Subsuming score:    {metrics["subsuming_mutation_score"]:.2%}')
    print(f'Results → {RESULTS}/')


def _write_json(name, obj):
    with open(os.path.join(RESULTS, name), 'w') as f:
        json.dump(obj, f, indent=2)


if __name__ == '__main__':
    main()
