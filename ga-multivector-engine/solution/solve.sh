#!/usr/bin/env bash

# Fix the Rust library source
cp /solution/lib_rs_fixed.rs /app/libga/src/lib.rs

# Rebuild the Rust shared library
cd /app/libga && cargo build --release 2>&1

# Fix the Python ctypes wrapper
cp /solution/ga_engine_fixed.py /app/ga_engine.py

# Verify the fixes
cd /app
python3 -c "
from ga_engine import (
    mask_tables, blade_grade, reorder_sign, metric,
    geo_product, inner_product, reverse_mv, sandwich, grade_involution
)
import math

# Verify mask_tables ordering
mt3, inv3 = mask_tables(3)
assert mt3 == [0, 1, 2, 4, 3, 5, 6, 7], f'mask_tables(3) wrong: {mt3}'
mt4, _ = mask_tables(4)
assert mt4 == [0, 1, 2, 4, 8, 3, 5, 9, 6, 10, 12, 7, 11, 13, 14, 15]

# Verify reorder_sign for high-bit blades
assert reorder_sign(4, 1) == -1, 'e2*e0 sign wrong'
assert reorder_sign(7, 7) == -1, 'e012*e012 sign wrong'
assert reorder_sign(5, 5) == -1, 'e02*e02 sign wrong'

# Verify metric for Cl(2,1,0)
assert metric(('Cl', 2, 1, 0), 0) == -1
assert metric(('Cl', 2, 1, 0), 1) == 1

# Verify PGA degenerate product
pga_result = geo_product([0,1,0,0,0,0,0,0], [0,1,0,0,0,0,0,0], 3, 'PGA')
assert abs(pga_result[0]) < 1e-12, f'PGA e0*e0 should be 0, got {pga_result[0]}'

# Verify PGA cross product
pga_cross = geo_product([0,1,0,0,0,0,0,0], [0,0,1,0,0,0,0,0], 3, 'PGA')
assert abs(pga_cross[4] - 1.0) < 1e-12, f'PGA e0*e1 should produce e01'

# Verify inner product
ip = inner_product([0,1,0,0,0,0,0,0], [0,1,0,0,0,0,0,0], 3, 'VGA')
assert abs(ip[0] - 1.0) < 1e-12, f'e0.e0 should be 1, got {ip[0]}'

# Verify reverse sign pattern
rev = reverse_mv([1, 1, 1, 1, 1, 1, 1, 1], 3)
assert rev == [1, 1, 1, 1, -1, -1, -1, -1], f'reverse wrong: {rev}'

# Verify sandwich rotation
c, s = math.cos(math.pi / 4), math.sin(math.pi / 4)
R = [c, 0, 0, 0, -s, 0, 0, 0]
e0 = [0, 1, 0, 0, 0, 0, 0, 0]
rot = sandwich(R, e0, 3, 'VGA')
assert abs(rot[2] - 1.0) < 1e-9, f'Rotation failed: {rot}'

# Verify grade involution
gi = grade_involution([1, 2, 3, 4, 5, 6, 7, 8], 3)
assert gi == [1, -2, -3, -4, 5, 6, 7, -8], f'Grade involution wrong: {gi}'

print('All solution verifications passed')
"
