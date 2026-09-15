A skeleton Python package at `/app/quantum_sim/` defines an API for simulating parameterized quantum circuits. The complete API specification is documented in `/app/quantum_sim/__init__.py`, and standard gate constants are provided in `/app/quantum_sim/gates.py` with rotation gate functions stubbed as `NotImplementedError`.

Complete the package so that it correctly simulates quantum circuits of up to 12 qubits within 10 seconds, supports controlled gates and parameterized rotation gates, and computes gradients of expectation values with respect to circuit parameters to within 1e-5 of finite-difference reference values.

A C source file at `/app/quantum_sim/kernel.c` declares two functions — `apply_single_qubit_gate` and `apply_controlled_single_qubit_gate` — that must be implemented and compiled into a shared library `/app/quantum_sim/libqsim.so`. The Python engine module must load this library via `ctypes` and dispatch all single-qubit and single-control-single-target gate operations through these native functions. Multi-qubit or multi-control gates may fall back to pure-Python subspace iteration that does not construct full 2^n x 2^n matrices.

A `Makefile` at `/app/Makefile` provides target stubs:
- `build`: compiles `kernel.c` into `libqsim.so` using `gcc`
- `benchmark`: depends on `build`, processes all JSON circuit files in `/app/circuits/`, writes per-circuit JSON results to `/app/results/`, and inserts summary rows into a SQLite database at `/app/results/benchmark.db` via the `sqlite3` CLI. The table schema is `results(name TEXT PRIMARY KEY, n_qubits INTEGER, expectation_value REAL, n_params INTEGER, n_gradients INTEGER)`.
- `report`: queries `/app/results/benchmark.db` via `sqlite3` and prints a columnar summary
- `clean`: removes build artifacts and results

A CLI skeleton exists at `/app/run_circuit.py`. Complete it to read JSON circuit definitions from the path given as a positional argument (see `/app/circuits/` for example circuits and their schema). It must output a JSON object to stdout containing at least `"expectation_value"`, and when invoked with `--gradients`, also include a `"gradients"` array. Output must be parseable by `jq`.

Qubit convention: qubit 0 is the least significant bit of the state vector index.