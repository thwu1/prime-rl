#!/bin/bash

# Ensure the buggy source file is present
if [ ! -f /app/bf16_arith.py ] && [ -f /opt/task/bf16_arith.py ]; then
    cp /opt/task/bf16_arith.py /app/bf16_arith.py
fi

# Apply fixes to all 7 IEEE 754 edge-case bugs
python3 /solution/solve_helper.py

# Verify the fix was applied successfully
python3 -c "
import sys
sys.path.insert(0, '/app')
from bf16_arith import bf16_add, bf16_mul, bf16_less_than, bf16_sub
from bf16_arith import is_nan, is_inf, pack
from bf16_arith import POS_ZERO, NEG_ZERO, POS_INF, NEG_INF, QNAN, MAX_POS, RD, RZ, RN_EVEN
assert bf16_add(POS_ZERO, NEG_ZERO, RD) == NEG_ZERO
assert is_nan(bf16_add(POS_INF, NEG_INF, RN_EVEN))
assert is_nan(bf16_mul(POS_ZERO, POS_INF, RN_EVEN))
assert not is_inf(bf16_add(MAX_POS, pack(0, 254, 0), RZ))
assert not bf16_less_than(QNAN, pack(0, 127, 0))
r = bf16_sub(pack(0,1,1), pack(0,1,0), RZ)
assert r == pack(0,0,1)
print('All fixes verified successfully')
"
