#!/bin/bash

pip3 install stim==1.15.0 -q

# Deploy the fault propagation analyzer to /app
cp /solution/ft_solver.py /app/ft_analyzer.py

# Verify it works
cd /app
python3 -c "
from ft_analyzer import propagate_fault, compute_ft_score
# Quick smoke test
assert propagate_fault('H 0', 0, 0, 'X', 1) == 'Z'
score = compute_ft_score('H 0\nCX 0 1', [0,1], [], 3)
print(f'Bell FT score: {score:.6f}')
assert abs(score - 10/18) < 1e-9
print('Solution verified.')
"
