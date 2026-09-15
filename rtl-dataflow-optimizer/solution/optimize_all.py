#!/usr/bin/env python3
"""
Runs the optimizer on all RTL programs and writes optimized versions.

"""

import sys
import os

sys.path.insert(0, '/app')
from rtl import load_program, save_program
from optimizer import optimize

PROGRAMS_DIR = '/app/programs'
OUTPUT_DIR = '/app/optimized'
NAMES = ['poly_eval', 'const_arith', 'dead_triangle', 'branch_const', 'cascade', 'loop_constprop', 'nested_diamond', 'strength_chain']

os.makedirs(OUTPUT_DIR, exist_ok=True)

for name in NAMES:
    prog = load_program(os.path.join(PROGRAMS_DIR, f'{name}.json'))
    opt = optimize(prog)
    save_program(opt, os.path.join(OUTPUT_DIR, f'{name}.json'))
    print(f'Optimized {name}')

print('All programs optimized.')
