#!/bin/bash

# Deploy the implementation
cp /solution/clifford_impl.py /app/clifford.py

# Verify the solution loads and passes basic smoke tests
python3 -c "
import sys, math
sys.path.insert(0, '/app')
import clifford

# Verify mask_tables via reference binary
import subprocess
result = subprocess.run(['/app/reference/ga_tool', 'mask_tables', '4'],
                       capture_output=True, text=True)
lines = result.stdout.strip().split('\n')
ref_mt = eval(lines[0].split(': ')[1])
mt, imt = clifford.mask_tables(4)
assert mt == ref_mt, f'mask_tables(4) mismatch vs reference'

# Verify metric via reference binary
for idx, p, q, r_val, expected_desc in [
    (0, 1, 1, 0, 'Cl(1,1,0) idx 0'),
    (0, 2, 0, 1, 'Cl(2,0,1) idx 0'),
    (3, 1, 3, 0, 'Cl(1,3,0) idx 3'),
]:
    result = subprocess.run(['/app/reference/ga_tool', 'metric', str(idx), str(p), str(q), str(r_val)],
                           capture_output=True, text=True)
    ref_val = int(result.stdout.strip())
    py_val = clifford.metric(idx, p, q, r_val)
    assert py_val == ref_val, f'metric mismatch for {expected_desc}: {py_val} != {ref_val}'

# Verify geometric product in Cl(3,0,0)
A = [1.0, 2, 3, 4, 0, 0, 0, 0]
B = [5.0, 6, 7, 8, 0, 0, 0, 0]
result = clifford.geo_product(A, B, 3, 3, 0, 0)
expected = [70.0, 16, 22, 28, -4, -8, -4, 0]
for i in range(8):
    assert abs(result[i] - expected[i]) < 1e-10, f'geo_product[{i}]: {result[i]} vs {expected[i]}'

# Verify exp_bivector (elliptic)
imt = clifford.mask_tables(3)[1]
theta = math.pi / 3
Biv = [0.0]*8
Biv[imt[6]] = theta/2
R = clifford.exp_bivector(Biv, 3, 3, 0, 0)
assert abs(R[0] - math.cos(theta/2)) < 1e-10
assert abs(R[imt[6]] - math.sin(theta/2)) < 1e-10

print('All smoke tests passed.')
"
