#!/bin/bash

pip3 install mpmath==1.3.0 -q

cp /solution/fp_improver_solution.py /app/fp_improver.py

# Verify the solution works by running it
python3 -c "
import sys
sys.path.insert(0, '/app')
import fp_improver
from mpmath import mp, mpf

# Parse all benchmarks
with open('/app/benchmarks.fpcore') as f:
    exprs = fp_improver.parse_fpcore(f.read())
assert len(exprs) == 6, f'Expected 6, got {len(exprs)}'

# Verify each improved function exists and computes something
mp.prec = 200
for expr in exprs:
    fn = fp_improver.get_improved(expr.name)
    assert callable(fn), f'{expr.name}: not callable'

# Spot-check NMSE 3.1 accuracy at x=1e16
improved = fp_improver.get_improved('NMSE example 3.1')
computed = improved(1e16)
exact = float(mp.sqrt(mpf('1e16') + 1) - mp.sqrt(mpf('1e16')))
rel_err = abs(computed - exact) / abs(exact) if exact != 0 else abs(computed)
bits = -mp.log(rel_err, 2) if rel_err > 0 else 53
print(f'NMSE 3.1 at 1e16: computed={computed:.6e}, exact={exact:.6e}, bits={float(bits):.1f}')

# Spot-check expm1 accuracy at x=1e-16
improved = fp_improver.get_improved('expm1 (example 3.7)')
computed = improved(1e-16)
exact_mp = mp.exp(mpf('1e-16')) - 1
rel_err = abs(mpf(computed) - exact_mp) / abs(exact_mp)
bits = float(-mp.log(rel_err, 2)) if rel_err > 0 else 53
print(f'expm1 at 1e-16: computed={computed:.6e}, bits={bits:.1f}')

# Spot-check quadp with cancellation
improved = fp_improver.get_improved('quadp (p42, positive)')
computed = improved(1.0, 1e8, 1.0)
d = mp.sqrt(mpf('1e16') - 4)
exact_mp = (-mpf('1e8') + d) / 2
rel_err = abs(mpf(computed) - exact_mp) / abs(exact_mp)
bits = float(-mp.log(rel_err, 2)) if rel_err > 0 else 53
print(f'quadp at (1,1e8,1): computed={computed:.6e}, bits={bits:.1f}')

print('All solution checks passed.')
"
