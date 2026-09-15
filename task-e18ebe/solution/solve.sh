#!/bin/bash

# Install dependencies
pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Deploy the solver implementation
cp /solution/sedov_impl.py /app/sedov.py

# Verify the solver loads and produces correct results
python3 -c "
import sys
sys.path.insert(0, '/app')
import sedov
import numpy as np

# Verify energy integrals for spherical case
e1, e2, alpha = sedov.sedov_alpha(1.4, 3, 0.0)
assert abs(e1 - 2.96269e-02) < 1e-5, f'eval1 mismatch: {e1}'
assert abs(alpha - 8.51060e-01) < 1e-3, f'alpha mismatch: {alpha}'

# Verify Sedov functions at a known point (spherical, v=0.33)
lam, f, g, h = sedov.sedov_funcs(0.33, 1.4, 3, 0.0)
assert abs(lam - 0.9913) < 1e-3, f'lambda mismatch: {lam}'

# Verify physical solution
r = np.linspace(0.0, 1.2, 121)
result = sedov.sedov_solution(r, 1.0)
assert abs(result['shock_position'] - 1.0) < 0.02, f'shock position: {result[\"shock_position\"]}'

# Verify singular case alpha
_, _, alpha_sing = sedov.sedov_alpha(1.4, 2, 1.66667)
assert abs(alpha_sing - 4.80856) < 1e-4, f'singular alpha: {alpha_sing}'

# Verify vacuum case alpha
_, _, alpha_vac = sedov.sedov_alpha(1.4, 2, 1.7)
assert abs(alpha_vac - 5.18062) < 1e-2, f'vacuum alpha: {alpha_vac}'

print('All solver verifications passed.')
"
