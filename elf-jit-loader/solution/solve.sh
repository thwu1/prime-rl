#!/bin/bash

# Deploy the JIT loader implementation
cp /solution/solve_jit.py /app/jit_loader.py

# Verify correctness by loading all cells and calling functions
python3 -c "
import sys
sys.path.insert(0, '/app')
from jit_loader import JITLoader

loader = JITLoader()
loader.load(
    '/app/objects/cell1.o',
    '/app/objects/cell2.o',
    '/app/objects/cell3.o',
    '/app/objects/cell4.o',
)

results = {
    'add(10,20)': loader.call('add', 10, 20),
    'multiply(5,7)': loader.call('multiply', 5, 7),
    'get_shared()': loader.call('get_shared'),
    'compute_sum()': loader.call('compute_sum'),
    'compute_product()': loader.call('compute_product'),
    'final_result()': loader.call('final_result'),
    'poly_eval()': loader.call('poly_eval'),
    'quadratic(1,0,0,5)': loader.call('quadratic', 1, 0, 0, 5),
    'get_counter()': loader.call('get_counter'),
    'increment() #1': loader.call('increment'),
    'increment() #2': loader.call('increment'),
    'get_counter() after': loader.call('get_counter'),
}

expected = {
    'add(10,20)': 30,
    'multiply(5,7)': 35,
    'get_shared()': 42,
    'compute_sum()': 50,
    'compute_product()': 126,
    'final_result()': 176,
    'poly_eval()': 49,
    'quadratic(1,0,0,5)': 25,
    'get_counter()': 0,
    'increment() #1': 1,
    'increment() #2': 2,
    'get_counter() after': 2,
}

all_ok = True
for k in results:
    status = 'OK' if results[k] == expected[k] else 'FAIL'
    if status == 'FAIL':
        all_ok = False
    print(f'  {k} = {results[k]} (expected {expected[k]}) [{status}]')

if all_ok:
    print('All checks passed.')
else:
    print('SOME CHECKS FAILED')
    sys.exit(1)
"
