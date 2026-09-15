At `/app/` is a numerical integration pipeline combining a pure-Python adaptive Gauss-Kronrod quadrature library (`quadrature.py`) with a C shared library wrapping GSL's adaptive integration routines (`src/quad_wrapper.c`), connected through a Python ctypes bridge (`gsl_bridge.py`). The benchmark driver (`run_benchmarks.py`) evaluates 6 integrals — smooth functions, endpoint singularities, and infinite domains — with cross-validation of finite-domain results against the GSL C backend.

The pipeline is broken at every layer — `make` fails, the C wrapper and ctypes bridge produce incorrect or crashing behavior, and the Python quadrature library has numerical bugs. Infinite-domain integration is unimplemented.

Additionally, `/app/evaluate.py` is a skeleton framework for evaluating 7 GSL quadrature methods (QAG with GK15 through GK61, and QAGS) across 6 test integrands in `/app/integrands.py` that exercise algebraic singularities, logarithmic singularities, and double-endpoint singularities. No analytical reference values are provided for these integrands. Design and implement a convergence-based accuracy assessment methodology that determines per-integrand method rankings and an overall ranking (by rank-sum aggregation) without ground truth.

Produce:
- `/app/results.json` — all 6 benchmarks passing with cross-validation
- `/app/evaluation.json` — per-integrand method rankings, best values, and overall ranking (schema in `evaluate.py` docstring)