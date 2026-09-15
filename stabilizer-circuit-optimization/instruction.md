You are given five quantum error-correcting codes in `/app/codes.json`. Each code entry contains stabilizer generators (Pauli strings) and a baseline state-preparation circuit in [Stim](https://github.com/quantumlib/Stim) format. The baseline circuits are correct (they prepare states stabilized by all generators) but highly sub-optimal in two-qubit gate count.

Write `/app/optimize.py` that reads `/app/codes.json`, produces an optimized Stim circuit for each code, and writes results to `/app/results.json`.

## Requirements

1. Each optimized circuit must **preserve all stabilizer generators** of its code. A stabilizer `S` is preserved if the state prepared by the circuit is a +1 eigenstate of `S` (verifiable via `stim.TableauSimulator.peek_observable_expectation`).

2. Each optimized circuit must use **strictly fewer two-qubit gates** (CX, CZ, SWAP) than its baseline.

3. The **total two-qubit gate count** across all five optimized circuits must be **at most 45**.

4. Circuits may only use gates from the Clifford group: `H`, `S`, `X`, `Z`, `CX`, `CZ`, `SWAP`.

5. Each circuit must operate on exactly `n` qubits (as specified in the code entry). No ancilla qubits.

## Output format

`/app/results.json` must be a JSON object:

```json
{
  "circuits": {
    "<code_name>": "<stim_circuit_string>",
    ...
  }
}
```

where each value is a valid Stim circuit string (newline-separated gate instructions). The keys must match the `name` field from `/app/codes.json`.

## Background

Stabilizer codes are central to quantum error correction. A stabilizer code is defined by a set of Pauli operators (stabilizer generators) that all commute and whose joint +1 eigenspace is the code space. A state-preparation circuit maps |0...0> to a state in this code space.

The baseline circuits were produced by naive Gaussian elimination on the stabilizer tableau, yielding correct but bloated circuits with many redundant two-qubit gates. Your task is to produce equivalent circuits with substantially fewer entangling operations.

Two-qubit gates in a Stim circuit with "packed" notation (e.g., `CX 0 1 2 3`) count as one gate per pair of qubit targets (that example is 2 CX gates).