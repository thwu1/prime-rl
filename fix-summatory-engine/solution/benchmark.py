#!/usr/bin/env python3
"""
Benchmark the shared library at different optimization levels (-O0, -O2, -O3)
and write evaluation.json with the results and recommendation.
"""

import ctypes
import json
import os
import shutil
import subprocess
import time


def build_library(source_dir, build_dir, opt_level):
    """Build libntsum.so in build_dir with the given optimization level."""
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    os.makedirs(build_dir)

    subprocess.run(
        ['cmake', source_dir, f'-DOPT_LEVEL=-{opt_level}'],
        cwd=build_dir, check=True,
        capture_output=True, text=True
    )
    subprocess.run(
        ['cmake', '--build', '.', '--target', 'ntsum'],
        cwd=build_dir, check=True,
        capture_output=True, text=True
    )
    lib_path = os.path.join(build_dir, 'libntsum.so')
    assert os.path.isfile(lib_path), f"Build failed for {opt_level}: {lib_path} not found"
    return lib_path


def benchmark_function(lib_path, func_name, arg, iterations=10):
    """Time a function call through ctypes, return minimum time in milliseconds."""
    lib = ctypes.CDLL(lib_path)
    fn = getattr(lib, func_name)
    fn.argtypes = [ctypes.c_longlong]
    fn.restype = ctypes.c_longlong

    # Warmup
    fn(arg)

    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn(arg)
        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000.0)  # Convert to ms

    return min(times)


def main():
    source_dir = '/app'
    test_n = 10000000
    results = {}

    for opt in ['O0', 'O2', 'O3']:
        build_dir = f'/tmp/bench_{opt}'
        lib_path = build_library(source_dir, build_dir, opt)

        pc_ms = benchmark_function(lib_path, 'ntsum_prime_count', test_n)
        m_ms = benchmark_function(lib_path, 'ntsum_mertens', test_n)

        results[opt] = {
            'prime_count_ms': round(pc_ms, 3),
            'mertens_ms': round(m_ms, 3)
        }
        print(f"{opt}: prime_count={pc_ms:.3f}ms, mertens={m_ms:.3f}ms")

    # Determine recommended level (lowest total time)
    totals = {k: v['prime_count_ms'] + v['mertens_ms'] for k, v in results.items()}
    recommended = min(totals, key=totals.get)
    speedup = totals['O0'] / totals[recommended]

    results['recommended'] = recommended
    results['speedup_vs_O0'] = round(speedup, 3)

    # Write evaluation report
    eval_path = '/app/evaluation.json'
    with open(eval_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Wrote {eval_path}")
    print(f"Recommended: {recommended} (speedup vs O0: {speedup:.2f}x)")

    # Rebuild /app/build/ with the recommended optimization level if different from O2
    if recommended != 'O2':
        print(f"Rebuilding /app/build/ with {recommended}...")
        build_dir = '/app/build'
        shutil.rmtree(build_dir, ignore_errors=True)
        os.makedirs(build_dir, exist_ok=True)
        subprocess.run(
            ['cmake', source_dir, f'-DOPT_LEVEL=-{recommended}'],
            cwd=build_dir, check=True,
            capture_output=True, text=True
        )
        subprocess.run(
            ['cmake', '--build', '.', '--target', 'ntsum'],
            cwd=build_dir, check=True,
            capture_output=True, text=True
        )
        print(f"Rebuilt with {recommended}")


if __name__ == '__main__':
    main()
