#!/usr/bin/env python3
"""Emit per-program instruction count statistics as newline-delimited JSON."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ir_parser import parse_program

PROGRAMS = ['prog1', 'prog2', 'prog3', 'prog4', 'prog5']
PROGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'programs')

for p in PROGRAMS:
    with open(os.path.join(PROGS_DIR, f'{p}.ir')) as f:
        orig = parse_program(f.read())
    with open(os.path.join(PROGS_DIR, f'{p}.opt.ir')) as f:
        opt = parse_program(f.read())
    oc = sum(len(b.instructions) for func in orig.functions for b in func.blocks)
    nc = sum(len(b.instructions) for func in opt.functions for b in func.blocks)
    pct = round(100.0 * (1.0 - nc / oc), 1)
    print(json.dumps({p: {'original_count': oc, 'optimized_count': nc, 'reduction_pct': pct}}))
