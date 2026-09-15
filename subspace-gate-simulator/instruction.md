A quantum circuit at `/app/circuit.json` must be simulated to produce the final state vector. Implement a simulator in Julia.

## Entry Point

Create `/app/simulate.jl` invokable as:

    julia /app/simulate.jl <input_circuit.json> <output_state.json>

It reads the circuit, simulates it from the all-zeros initial state, and writes the output state vector. Julia 1.10 and the `JSON.jl` package are pre-installed.

Execute your simulator on `/app/circuit.json` and write the result to `/app/output.json`.

## Quantum States and Gates

An n-qubit quantum state is a unit-norm complex vector of 2^n amplitudes. Index `i` corresponds to the basis state where qubit `j` has value `(i >> j) & 1` (little-endian). The initial state has amplitude 1 at index 0.

A k-qubit gate is a 2^k x 2^k unitary matrix that transforms the 2^k amplitudes across the target qubits' subspace while preserving all other qubit configurations. Controlled gates additionally condition on specified control qubits matching given values (0 or 1 per control).

## Circuit Format

```json
{
  "n_qubits": <int>,
  "gates": [{
    "gate": "<name>",
    "targets": [<qubit_indices>],
    "params": {"theta": <float>},
    "controls": [{"qubit": <int>, "value": 0|1}],
    "matrix_real": [[...]], "matrix_imag": [[...]]
  }]
}
```

Fields `params`, `controls`, `matrix_real`, `matrix_imag` are present only when applicable.

Standard gates: `H` = (1/sqrt2)[[1,1],[1,-1]], `X` = [[0,1],[1,0]], `Y` = [[0,-i],[i,0]], `Z` = [[1,0],[0,-1]], `S` = [[1,0],[0,i]], `T` = [[1,0],[0,e^{i*pi/4}]], `RX(t)` = [[cos(t/2),-i*sin(t/2)],[-i*sin(t/2),cos(t/2)]], `RY(t)` = [[cos(t/2),-sin(t/2)],[sin(t/2),cos(t/2)]], `RZ(t)` = [[e^{-it/2},0],[0,e^{it/2}]], `SWAP` = [[1,0,0,0],[0,0,1,0],[0,1,0,0],[0,0,0,1]], `CUSTOM` = explicit `matrix_real`/`matrix_imag`.

## Output Format

```json
{"n_qubits": <int>, "state": [[re_0, im_0], [re_1, im_1], ...]}
```

2^n entries as [real, imaginary] pairs.

## Constraints

The simulator must handle systems of 20 or more qubits for single-gate operations within 2GB of memory.