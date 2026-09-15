#!/usr/bin/env python3
"""
Solution: fix all bugs across Python and C code, build C library, regenerate results.

Bugs fixed:
1. matrices.py moler(): U = I + triu(ones,1) -> U = I - triu(ones,1)
2. matrices.py frank(): j >= i -> j >= i - 1 (include first subdiagonal)
3. estimators.py hager_cond1(): return norm1_Ainv -> return norm1_A * norm1_Ainv
4. c_src/blocked_est.c: convergence check est_new >= est -> est_new <= est
5. c_src/Makefile: add -llapack -lblas to LIBS for LAPACK linking
6. benchmark.py: hardcoded 0.5 -> config["crossover_threshold"] (0.05)

"""
import subprocess
import os


def fix_matrices():
    """Fix Moler sign error and Frank missing subdiagonal."""
    path = "/app/matrices.py"
    with open(path) as f:
        code = f.read()

    # Bug 1: Moler matrix uses + instead of -
    code = code.replace(
        "U = np.eye(n) + np.triu(np.ones((n, n)), 1)",
        "U = np.eye(n) - np.triu(np.ones((n, n)), 1)",
    )

    # Bug 2: Frank matrix missing subdiagonal
    code = code.replace(
        "if j >= i:",
        "if j >= i - 1:",
    )

    with open(path, "w") as f:
        f.write(code)
    print("Fixed matrices.py")


def fix_estimators():
    """Fix Hager estimator missing ||A||_1 factor."""
    path = "/app/estimators.py"
    with open(path) as f:
        code = f.read()

    # Bug 3: returns norm1_Ainv instead of norm1_A * norm1_Ainv
    code = code.replace(
        "return norm1_Ainv",
        "return norm1_A * norm1_Ainv",
    )

    with open(path, "w") as f:
        f.write(code)
    print("Fixed estimators.py")


def fix_c_code():
    """Fix convergence check in Hager iteration."""
    path = "/app/c_src/blocked_est.c"
    with open(path) as f:
        code = f.read()

    # Bug 4: convergence check uses >= (breaks when estimate improves)
    # should be <= (break when estimate stops improving)
    code = code.replace(
        "if (k > 0 && est_new >= est) break;",
        "if (k > 0 && est_new <= est) break;",
    )

    with open(path, "w") as f:
        f.write(code)
    print("Fixed blocked_est.c")


def fix_makefile():
    """Add LAPACK and BLAS link flags to Makefile."""
    path = "/app/c_src/Makefile"
    with open(path) as f:
        code = f.read()

    # Bug 5: missing -llapack -lblas for LAPACK functions
    code = code.replace(
        "LIBS = -lm",
        "LIBS = -llapack -lblas -lm",
    )

    with open(path, "w") as f:
        f.write(code)
    print("Fixed Makefile")


def build_c_library():
    """Build the C shared library."""
    result = subprocess.run(
        ["make", "-C", "/app/c_src"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("Build failed:")
        print(result.stderr)
        raise RuntimeError("Failed to build C library")
    print("Built libblocked_est.so")


def fix_benchmark():
    """Fix hardcoded crossover threshold."""
    path = "/app/benchmark.py"
    with open(path) as f:
        code = f.read()

    # Bug 6: hardcoded 0.5 instead of reading from config
    # Need to add threshold variable and use it
    code = code.replace(
        "    all_results = {}",
        "    threshold = config.get('crossover_threshold', 0.05)\n    all_results = {}",
    )
    code = code.replace(
        "if np.isfinite(sn) and sn >= 0.5:",
        "if np.isfinite(sn) and sn >= threshold:",
    )

    with open(path, "w") as f:
        f.write(code)
    print("Fixed benchmark.py")


def regenerate_results():
    """Run benchmark to generate correct results.json."""
    result = subprocess.run(
        ["python3", "/app/benchmark.py"],
        capture_output=True, text=True,
        cwd="/app",
    )
    if result.returncode != 0:
        print("Benchmark failed:")
        print(result.stderr)
        raise RuntimeError("Failed to run benchmark")
    print(result.stdout)
    print("Regenerated results.json")


def main():
    fix_matrices()
    fix_estimators()
    fix_c_code()
    fix_makefile()
    build_c_library()
    fix_benchmark()
    regenerate_results()
    print("All fixes applied and results regenerated.")


if __name__ == "__main__":
    main()
