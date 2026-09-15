Implement a dynamic optimization algorithm that minimizes offline error on the Moving Peaks Benchmark.

The benchmark landscape is implemented as a C shared library. Source code is at `/app/src/gmpb.c` with the API defined in `/app/src/gmpb.h`. Build it into `/app/libgmpb.so` using `/app/Makefile`.

Problem instance configurations (peak count, dimension, change frequency, shift severity) and offline error thresholds are stored in the SQLite database `/app/config.db`. Query it to understand the evaluation criteria for each of the 6 instances (F1–F6).

The evaluation harness `/app/runner.py` loads `libgmpb.so` via Python `ctypes` and reads configurations from SQLite. It evaluates your optimizer through the ask/tell interface. Study it to understand the ctypes bindings and evaluation protocol.

Implement the `Optimizer` class in `/app/optimizer.py`:
- `__init__(dimension, bounds, num_peaks, seed)`
- `ask()` returns candidate solution vectors for evaluation
- `tell(solutions, values, environment_changed)` receives fitness values and a boolean flag indicating whether the environment just changed

The landscape `f(x) = max_i { h_i / (1 + w_i * ||x - c_i||^2) }` has peaks that shift position, change height, and adjust sharpness at regular intervals. The global optimum can switch between different peaks after each change. See `/app/spec.md` for the complete mathematical specification.

The offline error is the per-evaluation average of `max(0, f*(t) - best_found)`, where `f*(t)` is the true optimum and `best_found` resets each environment change. Higher fitness is better. Run `python3 /app/runner.py` to evaluate. Each instance must achieve offline error below its threshold.