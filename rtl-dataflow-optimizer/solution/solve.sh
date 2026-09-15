#!/bin/bash

# Copy solution files into /app
cp /solution/optimizer_impl.py /app/optimizer.py
cp /solution/optimize_all.py /app/optimize_all.py
cp /solution/render_cfgs.py /app/render_cfgs.py
cp /solution/project_makefile /app/Makefile

# Run the build pipeline
cd /app
make all

# Verify semantic correctness
python3 -c "
import sys, os
sys.path.insert(0, '/app')
from rtl import load_program, interpret
from optimizer import optimize

programs_dir = '/app/programs'
tests = {
    'poly_eval': [([5], 51), ([0], 6), ([10], 146)],
    'const_arith': [([5], 40), ([0], 0), ([3], 24)],
    'dead_triangle': [([5, 3], 8), ([0, 0], 0)],
    'branch_const': [([5], 15), ([0], 10)],
    'cascade': [([3, 4], 56), ([0, 0], 0)],
    'loop_constprop': [([5], 55), ([3], 14), ([0], 0)],
    'nested_diamond': [([5, 3], 30), ([0, 3], -3), ([-2, 4], -20)],
    'strength_chain': [([5], 5), ([0], 0), ([-7], -7)],
}

for name, cases in tests.items():
    prog = load_program(os.path.join(programs_dir, f'{name}.json'))
    opt = optimize(prog)
    for args, expected in cases:
        result = interpret(opt, args)
        assert result == expected, f'{name}({args}): expected {expected}, got {result}'
    print(f'{name}: OK')

# Check build artifacts
names = ['poly_eval', 'const_arith', 'dead_triangle', 'branch_const',
         'cascade', 'loop_constprop', 'nested_diamond', 'strength_chain']
for name in names:
    assert os.path.exists(f'/app/optimized/{name}.json'), f'Missing optimized/{name}.json'
    for sfx in ['before', 'after']:
        assert os.path.exists(f'/app/cfg_output/{name}_{sfx}.svg'), f'Missing cfg_output/{name}_{sfx}.svg'

print('All verification checks passed.')
"
