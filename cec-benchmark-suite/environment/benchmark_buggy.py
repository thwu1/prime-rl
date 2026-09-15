"""
Benchmark Function Evaluator

Evaluates 12 numerical optimization benchmark functions with shift-and-rotate
transformations, hybrid constructions, and composition functions.
Reads parameters from /app/data/*.npy and writes results to /app/results.json.

F1-F8: Shifted & rotated base functions (implemented).
F9-F10: Hybrid functions — must be implemented from database specifications.
F11-F12: Composition functions — must be implemented from database specifications.
Constraint violations: must be implemented from database specifications.
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
    coeffs = np.power(10.0, 6.0 * np.arange(n) / n)
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
    return (-20.0 * np.exp(-0.2 * np.sqrt(np.sum(z ** 2) / n))
            - np.exp(np.sum(np.cos(2.0 * np.pi * z)) / n) + 20.0 + np.e)


def griewank(z):
    n = len(z)
    sum_part = np.sum(z ** 2) / 4000.0
    indices = np.arange(2, n + 2, dtype=float)
    prod_part = np.prod(np.cos(z / np.sqrt(indices)))
    return sum_part - prod_part + 1.0


def rastrigin(z):
    return np.sum(z ** 2 - 10.0 * np.cos(2.0 * np.pi * z) + 10.0)


# ============================================================
# Transformation: Shift and Rotate
# ============================================================

def shift_rotate(x, shift_idx, rotation_idx):
    y = x - shifts[shift_idx]
    return rotations[rotation_idx] @ y


# ============================================================
# Shifted & Rotated Functions F1-F8
# ============================================================

def F1(x):
    return sphere(shift_rotate(x, 0, 0)) + BIASES[0]

def F2(x):
    return elliptic(shift_rotate(x, 1, 1)) + BIASES[1]

def F3(x):
    return bent_cigar(shift_rotate(x, 2, 2)) + BIASES[2]

def F4(x):
    return discus(shift_rotate(x, 3, 3)) + BIASES[3]

def F5(x):
    z = shift_rotate(x, 4, 4)
    return rosenbrock(z) + BIASES[4]

def F6(x):
    return ackley(shift_rotate(x, 5, 5)) + BIASES[5]

def F7(x):
    return rastrigin(shift_rotate(x, 6, 6)) + BIASES[6]

def F8(x):
    return griewank(shift_rotate(x, 7, 7)) + BIASES[7]


# ============================================================
# Hybrid Functions F9-F10
# (Must be implemented from database specifications)
# ============================================================

def F9(x):
    raise NotImplementedError("F9: see function_specs and construction_formulas in benchmark.db")

def F10(x):
    raise NotImplementedError("F10: see function_specs and construction_formulas in benchmark.db")


# ============================================================
# Composition Functions F11-F12
# (Must be implemented from database specifications)
# ============================================================

def F11(x):
    raise NotImplementedError("F11: see function_specs and construction_formulas in benchmark.db")

def F12(x):
    raise NotImplementedError("F12: see function_specs and construction_formulas in benchmark.db")


# ============================================================
# Constraint Functions
# (Must be implemented from constraint_specs in benchmark.db)
# ============================================================

def constraint_violation_F1(x):
    raise NotImplementedError("See constraint_specs in benchmark.db")

def constraint_violation_F3(x):
    raise NotImplementedError("See constraint_specs in benchmark.db")

def constraint_violation_F9(x):
    raise NotImplementedError("See constraint_specs in benchmark.db")


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

    results['constraints'] = {}
    for fname, cfunc in [('F1', constraint_violation_F1),
                          ('F3', constraint_violation_F3),
                          ('F9', constraint_violation_F9)]:
        results['constraints'][fname] = {
            'violations': [float(cfunc(tp)) for tp in test_points]
        }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("Results written to /app/results.json")
