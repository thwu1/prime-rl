# PDE Convergence Benchmark

This benchmark tests convergence properties of numerical PDE solvers across
four canonical problems: two Poisson equation variants (5-point and compact
stencil), the heat equation, and linear advection.

## Architecture

- `kernels/` — C source for performance-critical numerical kernels
- `Makefile` — Builds the shared library `libpde_kernels.so`
- `bindings.py` — Python ctypes bindings for the C kernels
- `solvers/` — Python solver modules (some use C kernels via bindings)
- `run_benchmark.py` — Driver that runs all solvers and writes `results.json`

## Usage

Build the C kernels, then run the benchmark:

    make
    python3 run_benchmark.py
