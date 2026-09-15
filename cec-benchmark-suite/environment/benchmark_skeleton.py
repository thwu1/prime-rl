"""
CEC 2026-Style Benchmark Function Evaluator

Complete all functions marked TODO following the specification in /app/spec.md.
Run this script to generate /app/results.json.
"""
import numpy as np
import json

D = 10

# ============================================================
# Data Loading
# ============================================================
shifts = np.load('/app/data/shifts.npy')           # (10, D)
rotations = np.load('/app/data/rotations.npy')       # (10, D, D)
shuffle_f9 = np.load('/app/data/shuffle_f9.npy')     # (D,)
shuffle_f10 = np.load('/app/data/shuffle_f10.npy')   # (D,)
comp_optima_11 = np.load('/app/data/comp_optima_11.npy')       # (3, D)
comp_optima_12 = np.load('/app/data/comp_optima_12.npy')       # (5, D)
comp_rotations_11 = np.load('/app/data/comp_rotations_11.npy') # (3, D, D)
comp_rotations_12 = np.load('/app/data/comp_rotations_12.npy') # (5, D, D)
test_points = np.load('/app/data/test_points.npy')   # (5, D)

BIASES = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200]

# ============================================================
# Base Functions (operate on arbitrary-dimension vector z)
# ============================================================

def sphere(z):
    """f(z) = sum(z_i^2). See spec.md Section: Base Functions."""
    # TODO: implement
    raise NotImplementedError

def elliptic(z):
    """High Conditioned Elliptic. See spec.md."""
    # TODO: implement
    raise NotImplementedError

def bent_cigar(z):
    """Bent Cigar. See spec.md."""
    # TODO: implement
    raise NotImplementedError

def discus(z):
    """Discus (Tablet). See spec.md."""
    # TODO: implement
    raise NotImplementedError

def rosenbrock(z):
    """Rosenbrock. See spec.md. Expects raw z; caller handles +1 shift."""
    # TODO: implement
    raise NotImplementedError

def ackley(z):
    """Ackley. See spec.md."""
    # TODO: implement
    raise NotImplementedError

def griewank(z):
    """Griewank. See spec.md. Note sqrt(i+1) denominator (0-based)."""
    # TODO: implement
    raise NotImplementedError

def rastrigin(z):
    """Rastrigin. See spec.md."""
    # TODO: implement
    raise NotImplementedError

# ============================================================
# Transformation: Shift and Rotate
# ============================================================

def shift_rotate(x, shift_idx, rotation_idx):
    """Apply y = x - shifts[shift_idx], then z = rotations[rotation_idx] @ y.
    Returns z."""
    # TODO: implement
    raise NotImplementedError

# ============================================================
# Shifted & Rotated Functions F1-F8
# ============================================================

def F1(x):
    """Shifted Rotated Sphere, bias=100"""
    # TODO: implement using shift_rotate and sphere
    raise NotImplementedError

def F2(x):
    """Shifted Rotated Elliptic, bias=200"""
    # TODO: implement
    raise NotImplementedError

def F3(x):
    """Shifted Rotated Bent Cigar, bias=300"""
    # TODO: implement
    raise NotImplementedError

def F4(x):
    """Shifted Rotated Discus, bias=400"""
    # TODO: implement
    raise NotImplementedError

def F5(x):
    """Shifted Rotated Rosenbrock, bias=500. Remember z+1 transform."""
    # TODO: implement
    raise NotImplementedError

def F6(x):
    """Shifted Rotated Ackley, bias=600"""
    # TODO: implement
    raise NotImplementedError

def F7(x):
    """Shifted Rotated Rastrigin, bias=700"""
    # TODO: implement
    raise NotImplementedError

def F8(x):
    """Shifted Rotated Griewank, bias=800"""
    # TODO: implement
    raise NotImplementedError

# ============================================================
# Hybrid Functions F9-F10
# ============================================================

def F9(x):
    """Hybrid 1: [bent_cigar, ackley, rastrigin], partition [3,3,4], bias=900.
    Uses shifts[8], rotations[8], shuffle_f9."""
    # TODO: implement following hybrid construction in spec.md
    raise NotImplementedError

def F10(x):
    """Hybrid 2: [elliptic, sphere, griewank, rastrigin], partition [3,3,2,2], bias=1000.
    Uses shifts[9], rotations[9], shuffle_f10."""
    # TODO: implement
    raise NotImplementedError

# ============================================================
# Composition Functions F11-F12
# ============================================================

def F11(x):
    """Composition 1: 3 components [sphere, ackley, rastrigin].
    sigma=[10,20,30], lambda=[1,10,1], comp_bias=[0,100,200], overall_bias=1100.
    Uses comp_optima_11, comp_rotations_11."""
    # TODO: implement following composition construction in spec.md
    raise NotImplementedError

def F12(x):
    """Composition 2: 5 components [elliptic, bent_cigar, discus, sphere, griewank].
    sigma=[10,20,30,40,50], lambda=[10,1,10,1,1], comp_bias=[0,100,200,300,400],
    overall_bias=1200. Uses comp_optima_12, comp_rotations_12."""
    # TODO: implement
    raise NotImplementedError

# ============================================================
# Constraint Functions
# ============================================================

def constraint_violation_F1(x):
    """g(x) = (1/D)*sum((x_i - o_0_i)^2) - 5000. Violation = max(0, g(x))."""
    # TODO: implement
    raise NotImplementedError

def constraint_violation_F3(x):
    """g(x) = max(|x_i|) - 80. Violation = max(0, g(x))."""
    # TODO: implement
    raise NotImplementedError

def constraint_violation_F9(x):
    """g(x) = max(|x_i - o_8_i|) - 50. Violation = max(0, g(x))."""
    # TODO: implement
    raise NotImplementedError

# ============================================================
# Main Evaluation
# ============================================================
if __name__ == '__main__':
    func_list = [F1, F2, F3, F4, F5, F6, F7, F8, F9, F10, F11, F12]

    # Designated optima for each function
    optima = [shifts[i] for i in range(10)]       # F1-F10
    optima.append(comp_optima_11[0])               # F11
    optima.append(comp_optima_12[0])               # F12

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
