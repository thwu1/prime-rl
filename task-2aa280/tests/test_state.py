"""
Tests for the Dynamic Optimization Solver with Native C Kernel.

Verifies:
1. Build system (Makefile, C source, shared library compilation)
2. C kernel correctness (cone_fitness, batch_distances)
3. Python ctypes integration (solver.py uses ctypes + libdopt)
4. API conformance (class and method signatures)
5. Budget compliance (solver respects evaluation budget)
6. GMPB benchmark correctness (sanity checks)
7. Offline error below thresholds on 4 problem instances
"""


import ctypes
import math
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, '/app')

from gmpb import GMPB, GMPBConfig

BENCHMARK_SEED = 42
SOLVER_SEED = 123


# ---- Build system tests ----

def test_c_source_exists():
    """C kernel source must exist at /app/dopt_kernel.c."""
    assert os.path.exists('/app/dopt_kernel.c'), \
        "dopt_kernel.c not found at /app/"


def test_makefile_exists():
    """Makefile must exist at /app/Makefile."""
    assert os.path.exists('/app/Makefile'), \
        "Makefile not found at /app/"


def test_build_produces_library():
    """Running make must produce /app/libdopt.so."""
    result = subprocess.run(
        ['make', '-C', '/app'],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, \
        f"make failed (rc={result.returncode}): {result.stderr}"
    assert os.path.exists('/app/libdopt.so'), \
        "libdopt.so not produced by make"


# ---- C kernel correctness tests ----

def _load_kernel():
    """Load the compiled C kernel."""
    if not os.path.exists('/app/libdopt.so'):
        subprocess.run(['make', '-C', '/app'], check=True,
                       capture_output=True, timeout=60)
    lib = ctypes.CDLL('/app/libdopt.so')
    DPtr = ctypes.POINTER(ctypes.c_double)
    lib.cone_fitness.restype = ctypes.c_double
    lib.cone_fitness.argtypes = [DPtr, DPtr, DPtr, DPtr,
                                 ctypes.c_int, ctypes.c_int]
    lib.batch_distances.restype = None
    lib.batch_distances.argtypes = [DPtr, DPtr, ctypes.c_int,
                                    ctypes.c_int, DPtr]
    return lib


def test_kernel_exports_cone_fitness():
    """libdopt.so must export the cone_fitness symbol."""
    lib = _load_kernel()
    assert lib.cone_fitness is not None


def test_kernel_exports_batch_distances():
    """libdopt.so must export the batch_distances symbol."""
    lib = _load_kernel()
    assert lib.batch_distances is not None


def test_cone_fitness_correctness():
    """cone_fitness must compute max_p [h_p - w_p * ||x - c_p||] correctly."""
    lib = _load_kernel()
    # 2D, 2 peaks
    # Peak 0: pos=[1,0], h=10, w=1 -> dist=1.0, val=9.0
    # Peak 1: pos=[0,2], h=20, w=2 -> dist=2.0, val=16.0
    # Expected: 16.0
    x = (ctypes.c_double * 2)(0.0, 0.0)
    positions = (ctypes.c_double * 4)(1.0, 0.0, 0.0, 2.0)  # row-major
    heights = (ctypes.c_double * 2)(10.0, 20.0)
    widths = (ctypes.c_double * 2)(1.0, 2.0)

    result = lib.cone_fitness(x, positions, heights, widths, 2, 2)
    assert abs(result - 16.0) < 1e-10, \
        f"cone_fitness returned {result}, expected 16.0"


def test_cone_fitness_at_peak_center():
    """cone_fitness at a peak center should equal the peak height."""
    lib = _load_kernel()
    # x at peak 0 center: dist=0, val=h[0]=50.0
    x = (ctypes.c_double * 3)(1.0, 2.0, 3.0)
    positions = (ctypes.c_double * 6)(1.0, 2.0, 3.0, 10.0, 10.0, 10.0)
    heights = (ctypes.c_double * 2)(50.0, 30.0)
    widths = (ctypes.c_double * 2)(5.0, 5.0)

    result = lib.cone_fitness(x, positions, heights, widths, 2, 3)
    assert abs(result - 50.0) < 1e-10, \
        f"cone_fitness at peak center returned {result}, expected 50.0"


def test_batch_distances_correctness():
    """batch_distances must compute correct Euclidean distances."""
    lib = _load_kernel()
    # x=[0,0], positions=[[3,4],[0,5]]
    # dist to [3,4] = 5.0, dist to [0,5] = 5.0
    x = (ctypes.c_double * 2)(0.0, 0.0)
    positions = (ctypes.c_double * 4)(3.0, 4.0, 0.0, 5.0)
    out = (ctypes.c_double * 2)()

    lib.batch_distances(x, positions, 2, 2, out)
    assert abs(out[0] - 5.0) < 1e-10, \
        f"distance to [3,4] = {out[0]}, expected 5.0"
    assert abs(out[1] - 5.0) < 1e-10, \
        f"distance to [0,5] = {out[1]}, expected 5.0"


def test_batch_distances_higher_dim():
    """batch_distances works in higher dimensions."""
    lib = _load_kernel()
    dim = 5
    # x = [1,1,1,1,1], pos = [0,0,0,0,0]
    # dist = sqrt(5)
    x = (ctypes.c_double * dim)(*([1.0] * dim))
    positions = (ctypes.c_double * dim)(*([0.0] * dim))
    out = (ctypes.c_double * 1)()

    lib.batch_distances(x, positions, 1, dim, out)
    expected = math.sqrt(dim)
    assert abs(out[0] - expected) < 1e-10, \
        f"distance = {out[0]}, expected {expected}"


# ---- Python integration tests ----

def test_solver_file_exists():
    """solver.py must exist at /app/solver.py."""
    assert os.path.exists('/app/solver.py'), "solver.py not found at /app/"


def test_solver_uses_ctypes():
    """solver.py must use ctypes to interface with the C kernel."""
    with open('/app/solver.py', 'r') as f:
        source = f.read()
    assert 'ctypes' in source, \
        "solver.py must import/use ctypes to load the C kernel"
    assert 'libdopt' in source, \
        "solver.py must reference libdopt.so"


def _import_solver():
    """Import the DynamicOptimizer class from solver.py."""
    from solver import DynamicOptimizer
    return DynamicOptimizer


def test_solver_class_exists():
    """DynamicOptimizer class must exist with required methods."""
    DynamicOptimizer = _import_solver()
    solver = DynamicOptimizer(dim=5, bounds=(-50.0, 50.0), seed=0)
    assert hasattr(solver, 'optimize_environment'), \
        "DynamicOptimizer must have optimize_environment method"
    assert hasattr(solver, 'on_change'), \
        "DynamicOptimizer must have on_change method"
    assert callable(solver.optimize_environment)
    assert callable(solver.on_change)


# ---- Budget compliance tests ----

def test_budget_respected():
    """Solver must not exceed the evaluation budget."""
    DynamicOptimizer = _import_solver()
    config = GMPBConfig(num_peaks=5, dimension=3, change_frequency=200,
                        shift_severity=1.0, num_environments=3)
    gmpb = GMPB(config, seed=BENCHMARK_SEED)
    solver = DynamicOptimizer(dim=3, bounds=(-50.0, 50.0), seed=0)

    for env in range(3):
        before = gmpb.eval_count
        solver.optimize_environment(gmpb.evaluate, 200)
        used = gmpb.eval_count - before
        assert used <= 200, f"Env {env}: used {used} > 200 evaluations"
        if env < 2:
            gmpb.change_environment()
            solver.on_change()


# ---- GMPB sanity tests ----

def test_gmpb_optimum_fitness():
    """Fitness at the optimum position should equal the peak height."""
    config = GMPBConfig(num_peaks=5, dimension=3, change_frequency=100,
                        shift_severity=1.0, num_environments=2)
    gmpb = GMPB(config, seed=99)
    opt_pos, opt_fit = gmpb.get_optimum()
    actual = gmpb.evaluate(opt_pos)
    assert abs(actual - opt_fit) < 1e-10, \
        f"Fitness at optimum {actual} != expected {opt_fit}"


def test_gmpb_change_environment():
    """Environment change should alter peak state."""
    config = GMPBConfig(num_peaks=5, dimension=3, change_frequency=100,
                        shift_severity=2.0, num_environments=3)
    gmpb = GMPB(config, seed=42)
    pos_before = gmpb.positions.copy()
    gmpb.change_environment()
    pos_after = gmpb.positions.copy()
    assert not np.allclose(pos_before, pos_after), \
        "Peaks should move after change"


# ---- Performance tests ----

def _run_instance(num_peaks, dimension, change_frequency, shift_severity,
                  num_environments=20):
    """Run one benchmark instance and return the offline error."""
    DynamicOptimizer = _import_solver()
    config = GMPBConfig(
        num_peaks=num_peaks,
        dimension=dimension,
        change_frequency=change_frequency,
        shift_severity=shift_severity,
        num_environments=num_environments,
    )
    gmpb = GMPB(config, seed=BENCHMARK_SEED)
    solver = DynamicOptimizer(dim=dimension, bounds=(-50.0, 50.0),
                              seed=SOLVER_SEED)

    for env in range(num_environments):
        eval_before = gmpb.eval_count
        solver.optimize_environment(gmpb.evaluate, change_frequency)
        evals_used = gmpb.eval_count - eval_before
        assert evals_used <= change_frequency, (
            f"Env {env}: solver used {evals_used} evals, "
            f"budget was {change_frequency}"
        )
        if env < num_environments - 1:
            gmpb.change_environment()
            solver.on_change()

    return gmpb.offline_error()


def test_instance_a():
    """Instance A: 10 peaks, 5D, 5000 evals/env, shift=1.5, 20 envs."""
    error = _run_instance(
        num_peaks=10, dimension=5, change_frequency=5000,
        shift_severity=1.5, num_environments=20
    )
    assert error < 9.0, \
        f"Instance A: offline error {error:.4f} exceeds threshold 9.0"


def test_instance_b():
    """Instance B: 25 peaks, 5D, 5000 evals/env, shift=1.0, 20 envs."""
    error = _run_instance(
        num_peaks=25, dimension=5, change_frequency=5000,
        shift_severity=1.0, num_environments=20
    )
    assert error < 10.0, \
        f"Instance B: offline error {error:.4f} exceeds threshold 10.0"


def test_instance_c():
    """Instance C: 10 peaks, 5D, 1000 evals/env, shift=2.0, 20 envs."""
    error = _run_instance(
        num_peaks=10, dimension=5, change_frequency=1000,
        shift_severity=2.0, num_environments=20
    )
    assert error < 20.0, \
        f"Instance C: offline error {error:.4f} exceeds threshold 20.0"


def test_instance_d():
    """Instance D: 10 peaks, 10D, 5000 evals/env, shift=1.5, 20 envs."""
    error = _run_instance(
        num_peaks=10, dimension=10, change_frequency=5000,
        shift_severity=1.5, num_environments=20
    )
    assert error < 15.0, \
        f"Instance D: offline error {error:.4f} exceeds threshold 15.0"
