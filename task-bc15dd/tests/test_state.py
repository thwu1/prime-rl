"""
Tests for the E-Graph Equality Saturation Optimizer.

"""

import pytest
import sys
import os
import random

sys.path.insert(0, '/app')

COST_MODEL = {'+': 3, '*': 6, '<<': 2}

BENCHMARKS = [
    {"id": 1, "expr": "(* x 8)", "max_cost": 4},
    {"id": 2, "expr": "(* 4 (+ x y))", "max_cost": 8},
    {"id": 3, "expr": "(+ (* 2 x) (* 2 y))", "max_cost": 8},
    {"id": 4, "expr": "(+ (* x 3) (* x 5))", "max_cost": 4},
    {"id": 5, "expr": "(+ (* x 4) (* x 4))", "max_cost": 4},
    {"id": 6, "expr": "(* (+ x 0) 1)", "max_cost": 1},
    {"id": 7, "expr": "(+ (* (+ a b) 2) (* (+ a b) 2))", "max_cost": 8},
    {"id": 8, "expr": "(+ (+ (* x 8) (* y 4)) (* x 8))", "max_cost": 11},
]


def tokenize(s):
    return s.replace('(', ' ( ').replace(')', ' ) ').split()


def parse(s):
    tokens = tokenize(s)
    result, _ = _parse(tokens, 0)
    return result


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


def evaluate(tree, env):
    if tree[0] == 'const':
        return tree[1]
    elif tree[0] == 'var':
        return env[tree[1]]
    else:
        op = tree[0]
        children = [evaluate(c, env) for c in tree[1]]
        if op == '+':
            return children[0] + children[1]
        elif op == '*':
            return children[0] * children[1]
        elif op == '<<':
            return children[0] << children[1]
        else:
            raise ValueError(f"Unknown operator: {op}")


def compute_cost(tree):
    if tree[0] in ('const', 'var'):
        return 1
    else:
        op = tree[0]
        op_cost = COST_MODEL.get(op, 100)
        return op_cost + sum(compute_cost(c) for c in tree[1])


def get_variables(tree):
    if tree[0] == 'const':
        return set()
    elif tree[0] == 'var':
        return {tree[1]}
    else:
        result = set()
        for c in tree[1]:
            result |= get_variables(c)
        return result


class TestOptimizerBasics:
    def test_module_exists(self):
        """The optimizer module must exist at /app/egraph_opt.py."""
        assert os.path.exists('/app/egraph_opt.py'), \
            "Optimizer file must exist at /app/egraph_opt.py"

    def test_importable(self):
        """The module must expose an optimize() function."""
        from egraph_opt import optimize
        assert callable(optimize)

    def test_returns_string(self):
        """optimize() must return a string."""
        from egraph_opt import optimize
        result = optimize("(* x 8)")
        assert isinstance(result, str), f"Expected str, got {type(result)}"

    def test_single_variable(self):
        """optimize() on a single variable returns a valid expression."""
        from egraph_opt import optimize
        result = optimize("x")
        tree = parse(result)
        rng = random.Random(99)
        for _ in range(20):
            env = {'x': rng.randint(1, 100)}
            assert evaluate(tree, env) == env['x']

    def test_single_constant(self):
        """optimize() on a single constant returns that constant."""
        from egraph_opt import optimize
        result = optimize("42")
        tree = parse(result)
        assert evaluate(tree, {}) == 42


@pytest.mark.parametrize("bench", BENCHMARKS,
                         ids=[f"bench_{b['id']}_equiv" for b in BENCHMARKS])
class TestSemanticEquivalence:
    def test_equivalence(self, bench):
        """Optimized expression must be semantically equivalent to input."""
        from egraph_opt import optimize

        original = bench["expr"]
        optimized_str = optimize(original)

        orig_tree = parse(original)
        opt_tree = parse(optimized_str)

        variables = sorted(get_variables(orig_tree) | get_variables(opt_tree))

        rng = random.Random(42)
        for trial in range(100):
            env = {v: rng.randint(1, 100) for v in variables}
            orig_val = evaluate(orig_tree, env)
            opt_val = evaluate(opt_tree, env)
            assert orig_val == opt_val, (
                f"Benchmark {bench['id']}: semantic mismatch on trial {trial}. "
                f"env={env}, original={orig_val}, optimized={opt_val}. "
                f"Input: {original}, Output: {optimized_str}"
            )


@pytest.mark.parametrize("bench", BENCHMARKS,
                         ids=[f"bench_{b['id']}_cost" for b in BENCHMARKS])
class TestCostOptimality:
    def test_cost(self, bench):
        """Optimized expression cost must not exceed max_cost."""
        from egraph_opt import optimize

        original = bench["expr"]
        max_cost = bench["max_cost"]
        optimized_str = optimize(original)

        opt_tree = parse(optimized_str)
        actual_cost = compute_cost(opt_tree)

        assert actual_cost <= max_cost, (
            f"Benchmark {bench['id']}: cost {actual_cost} exceeds max {max_cost}. "
            f"Input: {original}, Output: {optimized_str}"
        )
