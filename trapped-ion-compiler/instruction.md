A broken quantum compilation pipeline exists at `/app/`. It was intended to compile the 3-qubit quantum circuit at `/app/input_circuit.qasm` for an IonQ trapped-ion QPU using BQSKit (pre-installed, v1.2.1), but it fails on execution due to multiple errors across its source files.

Diagnose all issues, fix the implementations, add any missing components, and produce a successful compilation.

## File Layout

The pipeline consists of these source files in `/app/`:

- **`gates.py`** — Custom gate definitions. Must export three classes: `MSGate`, `GPIGate`, `GPI2Gate`. Each must subclass both `bqskit.ir.gate.Gate` and `bqskit.qis.unitary.differentiable.DifferentiableUnitary`, implementing `get_unitary`, `get_grad` (returning shape `(1, d, d)` ndarray), and `get_unitary_and_grad`. Each must also implement `__eq__` and `__hash__` so that gates of the same type compare equal and can be used as dict keys and set members, and so that circuits containing them survive `pickle` round-trips.
- **`model.py`** — Hardware model. Must export `get_trapped_ion_model()` returning a `bqskit.compiler.machine.MachineModel` with 3 qubits, all-to-all coupling, and a gate set containing `MSGate`, `GPIGate`, `GPI2Gate`, and `bqskit.ir.gates.parameterized.rz.RZGate`.
- **`native_check_pass.py`** — Must export `NativeGateCheckPass`, a subclass of `bqskit.compiler.basepass.BasePass` whose constructor accepts a set of native gate types. Its `async run(self, circuit, data)` method must populate `data['all_native']` (bool) and `data['gate_counts']` (dict mapping gate name strings to integer counts).
- **`compile_pipeline.py`** — Orchestrates compilation. Must load the input circuit, compile it against the trapped-ion model, run `NativeGateCheckPass`, and write the outputs below.

## Gate Definitions

The correct unitary matrices are:

- **MSGate** (2-qubit, 1 parameter `theta`): the Molmer-Sorensen XX interaction `exp(-i * theta * X x X)`. Unitary: diagonal `cos(theta)`, anti-diagonal `-i * sin(theta)`.
- **GPIGate** (1-qubit, 1 parameter `phi`): `[[0, exp(-i*phi)], [exp(i*phi), 0]]`. This is an involutory gate (`GPI(phi)^2 = I`).
- **GPI2Gate** (1-qubit, 1 parameter `phi`): `(1/sqrt(2)) * [[1, -i*exp(-i*phi)], [-i*exp(i*phi), 1]]`.

All gates must be unitary for all parameter values. Analytic gradients must match finite-difference approximations to within `1e-5`.

## Required Outputs in `/app/`

- **`compiled_unitary.npy`** — the compiled circuit's unitary matrix saved as a NumPy `.npy` file.
- **`report.json`** — JSON object with exactly these keys:
  - `original_gate_count` (int): gate count of the input circuit
  - `compiled_gate_count` (int): gate count of the compiled circuit (must be > 0)
  - `unitary_distance` (float): global-phase-invariant distance `1 - |Tr(U_orig^dag @ U_compiled)| / d` (must be < 1e-4)
  - `all_native` (bool): whether every gate in the compiled circuit is from the native gate set (must be `true`)
  - `gate_counts` (dict): non-empty mapping of gate names to counts