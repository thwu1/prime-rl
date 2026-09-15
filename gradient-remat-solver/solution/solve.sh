#!/bin/bash


cd /app/rematerialization

# Fix the two bugs in dp_core.c and rebuild
cp /solution/dp_core_fixed.c dp_core.c
make

# Install the solver
cp /solution/solver_impl.py solver.py

# Sanity check
cd /app
python3 -c "
from rematerialization.chain import Chain
from rematerialization.solver import compute_table, reconstruct, simulate

ch = Chain(fw=[2.0, 3.0, 1.0], bw=[1.0, 2.0, 1.0, 0.0],
           cw=[2, 3, 1, 2], cbw=[2, 4, 2, 3],
           ftmp=[1, 0, 2], btmp=[0, 1, 0, 0])
budget = 15
opt_table = compute_table(ch, budget)
opt, _ = opt_table
cmem = budget - ch.cweigth[0]
val = opt[cmem][0][ch.length]
print(f'opt[{cmem}][0][{ch.length}] = {val}')
assert abs(val - 10.0) < 1e-9, f'Expected 10.0, got {val}'
ops = reconstruct(ch, 0, ch.length, cmem, opt_table)
peak = simulate(ops, ch)
print(f'Peak memory: {peak}, Budget: {budget}')
assert peak <= budget
print('All checks passed')
"
