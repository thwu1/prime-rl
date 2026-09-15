The project at `/app/` contains a Bezier curve library that needs a high-precision arc length computation engine. The mathematical requirements are in `/app/SPEC.md`, function signatures are in `/app/arclength_stub.py`, pre-computed quadrature coefficients are in `/app/coefficients.py`, and reference test curves with known arc lengths are in `/app/reference_curves.json`.

Create two files:

1. `/app/quadrature.c` — C implementation of the functions declared in `/app/quadrature.h`. Build into `/app/libquadrature.so` using `make -C /app`.

2. `/app/arclength.py` — Python module implementing all functions from `/app/arclength_stub.py`. Must call the compiled C shared library for inner-loop integrand evaluation; a pure-Python reimplementation of that loop is not accepted.

Precision targets: relative error < 1e-12 for quadratic curves, < 1e-8 for cubic curves. The `estimate_cubic_error` function must produce a conservative bound that never underestimates the actual integration error on any curve in the reference set.

Run `python3 /app/evaluate.py` to validate your implementation.