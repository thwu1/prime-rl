"""
Correct Benchmark Function Evaluator

All base functions, transformations, hybrid/composition constructions,
and constraint violations implemented correctly.
"""
import numpy as np
import json

D = 10

# Data Loading
shifts = np.load('/app/data/shifts.npy')
rotations = np.load('/app/data/rotations.npy')
shuffle_f9 = np.load('/app/data/shuffle_f9.npy')
shuffle_f10 = np.load('/app/data/shuffle_f10.npy')
comp_optima_11 = np.load('/app/data/comp_optima_11.npy')
comp_optima_12 = np.load('/app/data/comp_optima_12.npy')
comp_rotations_11 = np.load('/app/data/comp_rotations_11.npy')
comp_rotations_12 = np.load('/app/data/comp_rotations_12.npy')
test_points = np.load('/app/data/test_points.npy')

BIASES = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200]


# ============================================================
# Base Functions
# ============================================================

def sphere(z):
    return np.sum(z ** 2)

def elliptic(z):
    n = len(z)
    if n == 1:
        return z[0] ** 2
    coeffs = np.power(10.0, 6.0 * np.arange(n) / (n - 1))
    return np.sum(coeffs * z ** 2)

def bent_cigar(z):
    return z[0] ** 2 + 1e6 * np.sum(z[1:] ** 2)

def discus(z):
    return 1e6 * z[0] ** 2 + np.sum(z[1:] ** 2)

def rosenbrock(z):
    result = 0.0
    for i in range(len(z) - 1):
        result += 100.0 * (z[i] ** 2 - z[i + 1]) ** 2 + (z[i] - 1.0) ** 2
    return result

def ackley(z):
    n = len(z)
    sum_sq = np.sum(z ** 2)
    sum_cos = np.sum(np.cos(2.0 * np.pi * z))
    return -20.0 * np.exp(-0.2 * np.sqrt(sum_sq / n)) - np.exp(sum_cos / n) + 20.0 + np.e

def griewank(z):
    n = len(z)
    sum_sq = np.sum(z ** 2) / 4000.0
    prod_cos = np.prod(np.cos(z / np.sqrt(np.arange(1, n + 1, dtype=float))))
    return sum_sq - prod_cos + 1.0

def rastrigin(z):
    return np.sum(z ** 2 - 10.0 * np.cos(2.0 * np.pi * z) + 10.0)


# ============================================================
# Transformation
# ============================================================

def shift_rotate(x, shift_idx, rotation_idx):
    y = x - shifts[shift_idx]
    z = rotations[rotation_idx] @ y
    return z


# ============================================================
# Shifted & Rotated Functions F1-F8
# ============================================================

def F1(x):
    z = shift_rotate(x, 0, 0)
    return sphere(z) + 100

def F2(x):
    z = shift_rotate(x, 1, 1)
    return elliptic(z) + 200

def F3(x):
    z = shift_rotate(x, 2, 2)
    return bent_cigar(z) + 300

def F4(x):
    z = shift_rotate(x, 3, 3)
    return discus(z) + 400

def F5(x):
    z = shift_rotate(x, 4, 4)
    z_hat = z + 1.0
    return rosenbrock(z_hat) + 500

def F6(x):
    z = shift_rotate(x, 5, 5)
    return ackley(z) + 600

def F7(x):
    z = shift_rotate(x, 6, 6)
    return rastrigin(z) + 700

def F8(x):
    z = shift_rotate(x, 7, 7)
    return griewank(z) + 800


# ============================================================
# Hybrid Functions F9-F10
# ============================================================

def _hybrid(x, shift_idx, rotation_idx, shuffle, base_funcs, partition, bias):
    y = x - shifts[shift_idx]
    z = rotations[rotation_idx] @ y
    z_s = z[shuffle]
    result = 0.0
    start = 0
    for func, size in zip(base_funcs, partition):
        group = z_s[start:start + size]
        result += func(group)
        start += size
    return result + bias

def F9(x):
    return _hybrid(x, 8, 8, shuffle_f9,
                   [bent_cigar, ackley, rastrigin],
                   [3, 3, 4], 900)

def F10(x):
    return _hybrid(x, 9, 9, shuffle_f10,
                   [elliptic, sphere, griewank, rastrigin],
                   [3, 3, 2, 2], 1000)


# ============================================================
# Composition Functions F11-F12
# ============================================================

def _composition(x, optima, rot_matrices, sigmas, lambdas, comp_biases,
                 base_funcs, overall_bias):
    K = len(base_funcs)
    n = len(x)
    w = np.zeros(K)

    for k in range(K):
        delta = x - optima[k]
        dist_sq = np.sum(delta ** 2)
        if dist_sq < 1e-30:
            w[k] = 1e100
        else:
            w[k] = (1.0 / np.sqrt(dist_sq)) * np.exp(-dist_sq / (2.0 * n * sigmas[k] ** 2))

    w_sum = np.sum(w)
    if w_sum == 0:
        w = np.ones(K) / K
    else:
        w = w / w_sum

    result = 0.0
    for k in range(K):
        delta = x - optima[k]
        z = rot_matrices[k] @ delta
        f_val = base_funcs[k](z)
        result += w[k] * (lambdas[k] * f_val + comp_biases[k])

    return result + overall_bias

def F11(x):
    return _composition(
        x,
        comp_optima_11,
        comp_rotations_11,
        sigmas=np.array([10.0, 20.0, 30.0]),
        lambdas=np.array([1.0, 10.0, 1.0]),
        comp_biases=np.array([0.0, 100.0, 200.0]),
        base_funcs=[sphere, ackley, rastrigin],
        overall_bias=1100
    )

def F12(x):
    return _composition(
        x,
        comp_optima_12,
        comp_rotations_12,
        sigmas=np.array([10.0, 20.0, 30.0, 40.0, 50.0]),
        lambdas=np.array([10.0, 1.0, 10.0, 1.0, 1.0]),
        comp_biases=np.array([0.0, 100.0, 200.0, 300.0, 400.0]),
        base_funcs=[elliptic, bent_cigar, discus, sphere, griewank],
        overall_bias=1200
    )


# ============================================================
# Constraint Functions
# ============================================================

def constraint_violation_F1(x):
    g = np.sum((x - shifts[0]) ** 2) / D - 5000.0
    return max(0.0, g)

def constraint_violation_F3(x):
    g = np.max(np.abs(x)) - 80.0
    return max(0.0, g)

def constraint_violation_F9(x):
    g = np.max(np.abs(x - shifts[8])) - 50.0
    return max(0.0, g)


# ============================================================
# Main Evaluation
# ============================================================
if __name__ == '__main__':
    func_list = [F1, F2, F3, F4, F5, F6, F7, F8, F9, F10, F11, F12]

    optima = [shifts[i] for i in range(10)]
    optima.append(comp_optima_11[0])
    optima.append(comp_optima_12[0])

    results = {}
    for i, func in enumerate(func_list):
        fname = f'F{i+1}'
        results[fname] = {
            'optimum': float(func(optima[i])),
            'test_points': [float(func(tp)) for tp in test_points]
        }

    constraint_map = {
        'F1': constraint_violation_F1,
        'F3': constraint_violation_F3,
        'F9': constraint_violation_F9,
    }
    results['constraints'] = {}
    for fname, cfunc in constraint_map.items():
        results['constraints'][fname] = {
            'violations': [float(cfunc(tp)) for tp in test_points]
        }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")
