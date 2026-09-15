#!/bin/bash

# Fix the Makefile: add -shared -fPIC to build a proper shared library
cp /solution/solve_makefile /app/Makefile

# Fix the C NTT code: correct modular subtraction and add inverse normalization
cp /solution/solve_ntt.c /app/ntt.c

# Fix the ctypes bindings: use c_longlong instead of c_int
cp /solution/solve_ntt_binding.py /app/ntt_binding.py

# Fix FPS operations: correct poly_inv Newton step, implement poly_exp and poly_pow
cp /solution/solve_fps.py /app/fps.py

# Rebuild the shared library
cd /app
make clean
make

# Verify correctness through computation
python3 -c "
from ntt_binding import multiply
from fps import poly_inv, poly_ln, poly_exp, poly_pow, poly_sqrt
from mod_arith import MOD, modinv

# Verify NTT multiplication against brute force
a, b = [1, 2, 3, 4, 5], [6, 7, 8]
ntt_result = multiply(a, b)
brute = [0] * (len(a) + len(b) - 1)
for i in range(len(a)):
    for j in range(len(b)):
        brute[i+j] = (brute[i+j] + a[i]*b[j]) % MOD
assert ntt_result == brute, f'multiply failed: {ntt_result} != {brute}'

# Verify with large coefficients (catches c_int vs c_longlong bug)
import random
rng = random.Random(99)
a2 = [rng.randint(MOD//2, MOD-1) for _ in range(20)]
b2 = [rng.randint(MOD//2, MOD-1) for _ in range(20)]
r2 = multiply(a2, b2)
br2 = [0] * (len(a2) + len(b2) - 1)
for i in range(len(a2)):
    for j in range(len(b2)):
        br2[i+j] = (br2[i+j] + a2[i]*b2[j]) % MOD
assert r2 == br2, 'large-coefficient multiply failed'

# Verify poly_inv identity: f * inv(f) = 1 mod x^n
n = 32
f = [1, 3, 7, 2, 11]
inv_f = poly_inv(f, n)
product = [0] * (len(f) + len(inv_f) - 1)
for i in range(len(f)):
    for j in range(len(inv_f)):
        product[i+j] = (product[i+j] + f[i]*inv_f[j]) % MOD
assert product[0] == 1 and all(product[i] == 0 for i in range(1, n)), 'poly_inv failed'

# Verify poly_exp: e^x coefficients
exp_x = poly_exp([0, 1], 8)
fact = 1
for i in range(8):
    assert exp_x[i] == modinv(fact), f'exp coeff {i} wrong'
    fact = fact * (i + 1) % MOD

# Verify exp(ln(f)) roundtrip
f = [1, 5, 3, 9, 7]
ln_f = poly_ln(f, 16)
recovered = poly_exp(ln_f, 16)
f_padded = list(f) + [0] * (16 - len(f))
assert recovered == f_padded, 'exp(ln(f)) != f'

# Verify poly_pow against repeated multiplication
f = [1, 2, 3]
p5 = poly_pow(f, 5, 32)
brute = [1]
for _ in range(5):
    new_brute = [0] * (len(brute) + len(f) - 1)
    for i in range(len(brute)):
        for j in range(len(f)):
            new_brute[i+j] = (new_brute[i+j] + brute[i]*f[j]) % MOD
    brute = new_brute
brute_padded = (brute + [0]*32)[:32]
assert p5 == brute_padded, 'poly_pow failed'

# Verify poly_sqrt: sqrt(f)^2 = f
f = [1, 2, 5, 3, 7]
sq = poly_sqrt(f, 32)
sq2 = multiply(sq, sq)[:32]
f_padded = (list(f) + [0]*32)[:32]
assert sq2 == f_padded, 'poly_sqrt failed'

print('All verifications passed')
"
