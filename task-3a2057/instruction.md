`/app/benchmarks.fpcore` contains six floating-point expressions in [FPCore](https://fpbench.org/) format — the standard interchange format for floating-point analysis tools like Herbie and FPBench. Each expression specifies a mathematical computation, its input variables, domain preconditions, and a symbolic name. `/app/naive.c` and `/app/naive.h` provide naive C implementations of these expressions, each suffering from catastrophic cancellation or significant precision loss in specific input regions.

Build a complete accuracy optimization pipeline producing these artifacts in `/app/`:

**`improved.c` / `improved.h`** — C source implementing six functions with signatures `double improved_<name>(...)` matching the corresponding `naive_<name>` functions. Only standard `math.h` functions are permitted (no extended-precision libraries in the production code). Each must achieve relative error below `1e-12` compared to arbitrary-precision evaluation across all input regions, including near singularities and cancellation points.

**`Makefile`** — Must support `make libimproved.so` to produce a position-independent shared library from `improved.c`, linked against libm.

**`bindings.py`** — Python module using `ctypes` to load `libimproved.so` from the same directory. Must expose each improved function as a callable with correctly declared `argtypes` and `restype` (all `ctypes.c_double`).

**`report.json`** — Accuracy audit comparing naive versus improved implementations. A JSON array of six objects, each containing: `"name"` (matching the FPCore `:name`), `"naive_max_relerr"`, `"improved_max_relerr"`, `"improvement_ratio"` (naive_max divided by improved_max), and `"test_points_count"`. Relative errors must be computed against arbitrary-precision references at inputs spanning both numerically easy and challenging regions (near cancellation points, large magnitudes, near-zero).