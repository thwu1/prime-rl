import random
random.seed(42)
P = 998244353
N = 8
f = [1] + [random.randint(0, P-1) for _ in range(N-1)]
# Write input
import os
os.makedirs('/app/data', exist_ok=True)
os.makedirs('/app/output', exist_ok=True)
with open('/app/data/params.txt', 'w') as fp:
    fp.write(f'{N}\n{P}\n')
with open('/app/data/polynomial.txt', 'w') as fp:
    for c in f:
        fp.write(f'{c}\n')
print("f =", f)
print("Input files written.")
