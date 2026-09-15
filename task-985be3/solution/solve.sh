#!/bin/bash


# Install Z3 SMT solver for constraint feasibility checking
pip3 install z3-solver==4.13.0.0 -q

# Deploy the region decomposition engine
cp /solution/decompose_impl.py /app/decompose.py

# Verify the solution works on the example functions
cd /app
python3 -c "
from decompose import decompose
from lang import FuncDef, IfExpr, Compare, Var, Const, BinOp, Call, eval_expr

# Test simple function
f = FuncDef('f', ['x'], IfExpr(
    Compare('>', Var('x'), Const(99)), Const(100),
    IfExpr(Compare('>', Var('x'), Const(20)),
           BinOp('+', Var('x'), Const(9)),
           IfExpr(Compare('>', Var('x'), Const(-2)),
                  Const(103), Const(99)))))
r = decompose(f)
assert len(r) == 4, f'simple: expected 4, got {len(r)}'

# Test dead branch elimination
h = FuncDef('h', ['x'], IfExpr(
    Compare('>', Var('x'), Const(10)),
    IfExpr(Compare('<', Var('x'), Const(5)),
           Const(999), BinOp('*', Var('x'), Const(2))),
    BinOp('+', Var('x'), Const(1))))
r = decompose(h)
assert len(r) == 2, f'dead branch: expected 2, got {len(r)}'

# Test recursive function
s = FuncDef('sum_to', ['n'], IfExpr(
    Compare('<=', Var('n'), Const(0)), Const(0),
    BinOp('+', Var('n'),
          Call('sum_to', [BinOp('-', Var('n'), Const(1))]))),
    is_recursive=True)
funcs = {s.name: s}
r = decompose(s, funcs=funcs, unroll_depth=5)
assert len(r) >= 3, f'recursive: expected >= 3, got {len(r)}'

# Verify functional correctness for recursive case
for n in range(-5, 4):
    env = {'n': n}
    direct = eval_expr(s.body, env, funcs=funcs)
    from lang import eval_bool
    matching = [reg for reg in r
                if all(eval_bool(c, env) for c in reg.constraints)]
    assert len(matching) >= 1, f'n={n}: no match'
    ok = any(eval_expr(reg.invariant, env) == direct for reg in matching)
    assert ok, f'n={n}: wrong value'

print('All solution checks passed.')
"
