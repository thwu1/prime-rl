#!/bin/bash

# Install dependencies
pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Deploy the Sedov solver implementation
cp /solution/sedov_impl.py /app/sedov.py

# Verify the solver works by computing energy integrals for all geometries
cd /app
python3 -c "
import sys
sys.path.insert(0, '/app')
from sedov import compute_energy_integrals, compute_postshock, solve_sedov
import numpy as np

print('=== Energy Integrals (gamma=1.4, omega=0) ===')
for geom, name in [(1, 'Planar'), (2, 'Cylindrical'), (3, 'Spherical')]:
    e1, e2, alpha = compute_energy_integrals(geom, 1.4, 0.0)
    print(f'{name}: eval1={e1:.6e}, eval2={e2:.6e}, alpha={alpha:.6e}')

print()
print('=== Post-shock State (spherical, gamma=1.4, t=1.0) ===')
_, _, alpha = compute_energy_integrals(3, 1.4, 0.0)
ps = compute_postshock(3, 1.4, 1.0, 0.851072, alpha, 1.0)
for k, v in ps.items():
    print(f'  {k} = {v:.6e}')

print()
print('=== Full Profile Test (spherical) ===')
r = np.linspace(0.1, 1.5, 50)
result = solve_sedov(r, 1.0, geometry=3, gamma=1.4, rho0=1.0, eblast=0.851072)
print(f'  Shock position r2 = {result[\"r2\"]:.6f}')
print(f'  Peak density = {np.max(result[\"density\"]):.4f}')
print(f'  Density at r=1.2 (outside shock) = {result[\"density\"][-5]:.4f}')
print('Solver verification complete.')
"
