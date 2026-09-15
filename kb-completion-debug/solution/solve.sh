#!/bin/bash

pip3 install z3-solver==4.13.0.0 -q

# Fix the 3 bugs in ordering.py and rewriting.py
python3 /solution/fix_bugs.py

# Replace completion.py with fixed + gt_fn-enabled version
cp /solution/completion_fixed.py /app/completion.py

# Install complete KBO implementation
cp /solution/kbo_complete.py /app/kbo.py

# Install complete Z3 weight finder
cp /solution/wf_complete.py /app/weight_finder.py

echo ""
echo "Verifying with LPO..."
cd /app && python3 run_completion.py

echo ""
echo "Verifying with KBO..."
python3 -c "
from term import Var, Fun
from kbo import KBOConfig, kbo_gt
from weight_finder import find_kbo_weights
from completion import complete
from rewriting import normalize

def mul(a, b): return Fun('mul', (a, b))
def inv(a): return Fun('inv', (a,))
e = Fun('e', ())
x, y, z = Var('x'), Var('y'), Var('z')

axioms = [
    (mul(e, x), x),
    (mul(inv(x), x), e),
    (mul(mul(x, y), z), mul(x, mul(y, z))),
]
symbols = {'mul': 2, 'inv': 1, 'e': 0}

print('Finding KBO weights with Z3...')
result = find_kbo_weights(axioms, symbols)
print(f'  w0={result[\"w0\"]}, weights={result[\"weights\"]}, prec={result[\"precedence\"]}')

cfg = KBOConfig(result['weights'], result['w0'], result['precedence'])
gt_fn = lambda s, t: kbo_gt(s, t, cfg)

print('Running completion with KBO...')
rules = complete(axioms, gt_fn=gt_fn)
print(f'KBO completion succeeded with {len(rules)} rules')
for i, (l, r) in enumerate(rules, 1):
    print(f'  R{i:2d}: {l} --> {r}')

a, b = Var('a'), Var('b')
print()
print(f'mul(a, e) -> {normalize(mul(a, e), rules)}')
print(f'mul(a, inv(a)) -> {normalize(mul(a, inv(a)), rules)}')
print(f'inv(inv(a)) -> {normalize(inv(inv(a)), rules)}')
print(f'inv(mul(a, b)) -> {normalize(inv(mul(a, b)), rules)}')
print('KBO verification complete.')
"
