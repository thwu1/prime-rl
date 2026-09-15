"""
Measure floating-point accuracy for both original and improved expressions.
Computes average bits of accuracy by comparing float64 results against
mpmath reference values at high precision.
"""

import math
import json
import random
import sys

sys.path.insert(0, '/app')

from mpmath import mp, mpf
mp.dps = 60

from improved import improved_1, improved_2, improved_3, improved_4

SEED = 12345
N_SAMPLES = 2000


def log_uniform(lo, hi, rng):
    return math.exp(rng.uniform(math.log(lo), math.log(hi)))


def bits_of_accuracy(approx, exact_mp):
    exact = float(exact_mp)
    approx = float(approx)
    if math.isnan(approx) or math.isinf(approx):
        return 0.0
    if exact == 0.0:
        return 53.0 if approx == 0.0 else 0.0
    rel_err = abs(approx - exact) / abs(exact)
    if rel_err == 0.0:
        return 53.0
    return max(0.0, min(53.0, -math.log2(rel_err)))


def measure(func, ref_func, points, multivar=False):
    total = 0.0
    count = 0
    for pt in points:
        try:
            if multivar:
                exact = ref_func(*[mpf(p) for p in pt])
                approx = func(*pt)
            else:
                exact = ref_func(mpf(pt))
                approx = func(pt)
        except (OverflowError, ValueError, ZeroDivisionError):
            count += 1
            continue
        total += bits_of_accuracy(approx, exact)
        count += 1
    return total / count if count > 0 else 0.0


# Original functions (naive direct translations from FPCore)
def orig_1(x): return (math.exp(x) - 1.0 - x) / (x * x)
def orig_2(x): return (math.exp(x) + math.exp(-x)) / (math.exp(x) - math.exp(-x)) - 1.0 / x
def orig_3(x): return (math.sin(x) - x * math.cos(x)) / (x - math.sin(x))
def orig_4(x, y): return (math.exp(x) - math.exp(y)) / (x - y)

# Reference functions (mpmath high-precision)
def ref_1(x): return (mp.exp(x) - 1 - x) / (x * x)
def ref_2(x): return (mp.exp(x) + mp.exp(-x)) / (mp.exp(x) - mp.exp(-x)) - 1 / x
def ref_3(x): return (mp.sin(x) - x * mp.cos(x)) / (x - mp.sin(x))
def ref_4(x, y):
    x, y = mpf(x), mpf(y)
    return (mp.exp(x) - mp.exp(y)) / (x - y)


# Generate sample points
rng = random.Random(SEED)

# Expression 1: |x| log-uniform from [1e-12, 0.1], random sign
pts1 = []
for _ in range(N_SAMPLES):
    x = log_uniform(1e-12, 0.1, rng)
    if rng.random() < 0.5:
        x = -x
    pts1.append(x)

# Expression 2: x log-uniform from [1e-6, 10]
pts2 = [log_uniform(1e-6, 10.0, rng) for _ in range(N_SAMPLES)]

# Expression 3: x log-uniform from [1e-8, 2.0]
pts3 = [log_uniform(1e-8, 2.0, rng) for _ in range(N_SAMPLES)]

# Expression 4: x uniform [-20, 20], d = log_uniform [1e-12, 1e-2] * random sign
pts4 = []
for _ in range(N_SAMPLES):
    x = rng.uniform(-20.0, 20.0)
    d = log_uniform(1e-12, 1e-2, rng)
    if rng.random() < 0.5:
        d = -d
    y = x - d
    pts4.append((x, y))

configs = [
    {'id': 1, 'orig': orig_1, 'impr': improved_1, 'ref': ref_1, 'points': pts1, 'multivar': False},
    {'id': 2, 'orig': orig_2, 'impr': improved_2, 'ref': ref_2, 'points': pts2, 'multivar': False},
    {'id': 3, 'orig': orig_3, 'impr': improved_3, 'ref': ref_3, 'points': pts3, 'multivar': False},
    {'id': 4, 'orig': orig_4, 'impr': improved_4, 'ref': ref_4, 'points': pts4, 'multivar': True},
]

print("Measuring accuracy for 4 expressions...")
results = []

for cfg in configs:
    orig_bits = measure(cfg['orig'], cfg['ref'], cfg['points'], cfg['multivar'])
    impr_bits = measure(cfg['impr'], cfg['ref'], cfg['points'], cfg['multivar'])

    entry = {
        'id': cfg['id'],
        'original_avg_bits': round(orig_bits, 2),
        'improved_avg_bits': round(impr_bits, 2),
    }
    results.append(entry)
    print(f"  Expression {cfg['id']}: original={orig_bits:.1f} bits, improved={impr_bits:.1f} bits "
          f"(gain={impr_bits - orig_bits:.1f})")

report = {'expressions': results}

with open('/app/report.json', 'w') as f:
    json.dump(report, f, indent=2)

print("\nReport written to /app/report.json")
