#!/bin/bash

pip3 install numpy==2.1.3 -q

# Fix native C accelerator: source, Makefile, then build
cp /solution/discount_fixed.c /app/native/discount.c
cp /solution/Makefile_fixed /app/native/Makefile
make -C /app/native

# Deploy the corrected TVM library (with fixed ctypes integration)
cp /solution/tvm_fixed.py /app/tvm.py

# Verify the full system
python3 -c "
import sys, ctypes, os
sys.path.insert(0, '/app')
import numpy as np
from datetime import date
from decimal import Decimal
import tvm

print('=== Native C backend ===')
assert os.path.exists('/app/native/libdiscount.so'), 'Library not found'
lib = ctypes.CDLL('/app/native/libdiscount.so')
assert hasattr(lib, 'npv_native'), 'npv_native missing'
assert tvm._npv_native is not None, 'Backend not loaded in tvm'
print('Native backend loaded and integrated')

# Test native NPV directly
npv_fn = lib.npv_native
npv_fn.argtypes = [ctypes.c_double, ctypes.POINTER(ctypes.c_double), ctypes.c_int]
npv_fn.restype = ctypes.c_double
vals = [0.0, 1.0, 2.0, 3.0, 4.0]
c = (ctypes.c_double * 5)(*vals)
assert np.isnan(npv_fn(-1.0, c, 5)), 'Native rate=-1 guard failed'
print('Native rate=-1: NaN')

print()
print('=== Python bug fixes ===')

irr_val = tvm.irr([-5, 10.5, 1, -8, 1])
assert abs(irr_val - 0.0886) < 0.01
print(f'IRR selection: {irr_val:.6f}')

npv_val = tvm.npv(-1, [0, 1, 2, 3, 4])
assert np.isnan(npv_val)
print('NPV rate=-1: NaN')

ipmt_val = tvm.ipmt(0.001988079518355057, 2, 360, 300000, 0, 1)
assert abs(ipmt_val - (-594.107158)) / 594.107158 < 1e-4
print(f'IPMT begin per=2: {ipmt_val:.6f}')

mirr_val = tvm.mirr([-120000, 39000, 30000, 21000, 37000, 46000], 0.10, 0.12)
assert abs(mirr_val - 0.126094) < 0.001
print(f'MIRR exponent: {mirr_val:.6f}')

rate_val = tvm.rate(Decimal('10'), Decimal('0'), Decimal('-3500'), Decimal('10000'))
assert isinstance(rate_val, Decimal)
print(f'rate Decimal: {rate_val}')

print()
print('=== New implementations ===')

xnpv_val = tvm.xnpv(0.1, [-1000, 1100], [date(2019,1,1), date(2020,1,1)])
assert abs(xnpv_val) < 0.01
print(f'xnpv: {xnpv_val:.8f}')

xirr_val = tvm.xirr([-1000, 1100], [date(2019,1,1), date(2020,1,1)])
assert abs(xirr_val - 0.1) < 0.001
print(f'xirr: {xirr_val:.6f}')

cf = [-10000, 2750, 4250, 3250, 2750]
ds = [date(2020,1,1), date(2020,7,1), date(2021,1,1), date(2021,7,1), date(2022,1,1)]
r = tvm.xirr(cf, ds)
residual = tvm.xnpv(r, cf, ds)
assert abs(residual) < 1e-6
print(f'xirr congruence: xnpv={residual:.10f}')

print()
print('All verifications passed.')
"
