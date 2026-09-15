You have five quantum circuits in OpenQASM 2.0 format at `/app/benchmarks/`. Each uses gates from the Clifford+T set (`h`, `cx`, `t`, `tdg`, `s`, `sdg`, `z`) and contains more non-Clifford (T/Tdg) gates than the minimum required to implement the same unitary transformation.

Build a Python pipeline `/app/optimize.py` that:

1. Reads each `.qasm` file from `/app/benchmarks/`
2. Produces a circuit that implements an identical unitary (up to global phase) with fewer non-Clifford gates
3. Writes the optimized circuit in OpenQASM 2.0 format to `/app/results/<same_filename>`

Two circuits are *equivalent* if their unitary matrices differ by at most a scalar global phase factor. The maximum allowed non-Clifford gate counts are specified per benchmark in `/app/targets.json`.

`/app/circuit.py` provides a `Circuit` class for the `{H, CNOT, Rz}` gate set with `to_unitary()` for computing the full unitary matrix. You may use it or any other approach.

Run `python3 /app/optimize.py` to produce all output files in `/app/results/`.