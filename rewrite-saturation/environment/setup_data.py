#!/usr/bin/env python3
"""Create task data files for the equality saturation benchmark."""
import json
import os

BASE = "/opt/eqsat"
BENCH = os.path.join(BASE, "benchmarks")
os.makedirs(BENCH, exist_ok=True)

# Rewrite rules
rules = {
    "rules": [
        {"name": "add-zero-r", "lhs": "(+ ?a 0)", "rhs": "?a"},
        {"name": "add-zero-l", "lhs": "(+ 0 ?a)", "rhs": "?a"},
        {"name": "mul-one-r", "lhs": "(* ?a 1)", "rhs": "?a"},
        {"name": "mul-one-l", "lhs": "(* 1 ?a)", "rhs": "?a"},
        {"name": "mul-zero-r", "lhs": "(* ?a 0)", "rhs": "0"},
        {"name": "mul-zero-l", "lhs": "(* 0 ?a)", "rhs": "0"},
        {"name": "sub-zero", "lhs": "(- ?a 0)", "rhs": "?a"},
        {"name": "sub-self", "lhs": "(- ?a ?a)", "rhs": "0"},
        {"name": "div-one", "lhs": "(/ ?a 1)", "rhs": "?a"},
        {"name": "add-comm", "lhs": "(+ ?a ?b)", "rhs": "(+ ?b ?a)"},
        {"name": "mul-comm", "lhs": "(* ?a ?b)", "rhs": "(* ?b ?a)"},
        {"name": "add-assoc", "lhs": "(+ (+ ?a ?b) ?c)", "rhs": "(+ ?a (+ ?b ?c))"},
        {"name": "mul-assoc", "lhs": "(* (* ?a ?b) ?c)", "rhs": "(* ?a (* ?b ?c))"},
        {"name": "dist", "lhs": "(* ?a (+ ?b ?c))", "rhs": "(+ (* ?a ?b) (* ?a ?c))"},
        {"name": "factor", "lhs": "(+ (* ?a ?b) (* ?a ?c))", "rhs": "(* ?a (+ ?b ?c))"},
        {"name": "double", "lhs": "(+ ?a ?a)", "rhs": "(* 2 ?a)"},
        {"name": "neg-neg", "lhs": "(neg (neg ?a))", "rhs": "?a"},
        {"name": "add-neg", "lhs": "(+ ?a (neg ?b))", "rhs": "(- ?a ?b)"},
        {"name": "shl-2", "lhs": "(* ?a 2)", "rhs": "(<< ?a 1)"},
        {"name": "shl-4", "lhs": "(* ?a 4)", "rhs": "(<< ?a 2)"},
        {"name": "shl-8", "lhs": "(* ?a 8)", "rhs": "(<< ?a 3)"},
        {"name": "shl-16", "lhs": "(* ?a 16)", "rhs": "(<< ?a 4)"},
        {"name": "shl-32", "lhs": "(* ?a 32)", "rhs": "(<< ?a 5)"},
    ]
}
with open(os.path.join(BASE, "rules.json"), "w") as f:
    json.dump(rules, f, indent=2)

# Cost model
cost_model = {
    "op_costs": {
        "+": 1, "-": 1, "*": 3, "/": 5,
        "<<": 1, ">>": 1, "neg": 1,
    }
}
with open(os.path.join(BASE, "cost_model.json"), "w") as f:
    json.dump(cost_model, f, indent=2)

# Benchmark expressions
benchmarks = [
    ("expr01.sexp", "(+ x 0)"),
    ("expr02.sexp", "(* y 2)"),
    ("expr03.sexp", "(+ (* a b) (* a c))"),
    ("expr04.sexp", "(neg (neg (+ a b)))"),
    ("expr05.sexp", "(+ (+ (* x 0) y) 0)"),
    ("expr06.sexp", "(* (+ a b) 4)"),
    ("expr07.sexp", "(+ (* a 8) (* a 8))"),
    ("expr08.sexp", "(+ (* 2 x) (* 2 y))"),
    ("expr09.sexp", "(+ (* (+ a b) 2) (* (+ a b) 2))"),
    ("expr10.sexp", "(+ (* x 3) (* x 5))"),
]
for name, expr in benchmarks:
    with open(os.path.join(BENCH, name), "w") as f:
        f.write(expr + "\n")
