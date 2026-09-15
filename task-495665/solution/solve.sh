#!/usr/bin/env bash

# Deploy solution files to /app
cp /solution/touring.mod /app/touring.mod
cp /solution/solver_impl.py /app/solver.py

# Verify the solver works on one instance
python3 -c "
import sys
sys.path.insert(0, '/app')
from game import generate_instance, evaluate_tour
from solver import solve

instance = generate_instance(42, 60)
tour = solve(instance)
value, valid, err = evaluate_tour(instance, tour)
print(f'Verification: seed=42, score={value}, valid={valid}, tour_len={len(tour)}')
assert valid, f'Tour invalid: {err}'
assert value >= 800, f'Score {value} too low'
print('Solution verified successfully.')
"
