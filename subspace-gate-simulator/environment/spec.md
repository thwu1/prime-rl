# Quantum State-Vector Simulation via Bit-Mask Subspace Iteration

## State Vector Representation

An n-qubit quantum state is represented as a complex vector of length 2^n. Index `i` of the state vector corresponds to the computational basis state where qubit `j` has value `(i >> j) & 1` (little-endian bit ordering).

For example, in a 3-qubit system:
- Index 0 (`000`) = all qubits zero
- Index 5 (`101`) = qubits 0 and 2 are one, qubit 1 is zero

## The Subspace Iteration Technique

A k-qubit unitary gate U (a 2^k x 2^k matrix) acts on k specified target qubits. The naive approach constructs a full 2^n x 2^n matrix via Kronecker products, which is O(2^{2n}) in time and space. The subspace iteration technique avoids this by processing 2^k elements at a time:

### Algorithm

1. **Identify the index partition.** Each full-space index i can be decomposed into:
   - The k bits at target qubit positions (the "gate indices")
   - The remaining n-k bits (the "iteration indices")

2. **Iterate over the iteration subspace.** For each of the 2^{n-k} configurations of the non-target qubits:
   - **Compute the base index**: an index where all target qubit bits are 0, and non-target bits are set according to the current iteration configuration
   - **Compute 2^k full-space indices** by OR-ing the base index with each "complement offset"
   - **Extract** the 2^k-element sub-vector from the state at these indices
   - **Multiply** by the gate matrix U
   - **Write back** the result to those state indices

3. **Computing base indices.** Given the sorted list of non-target qubit positions [p_0, p_1, ...], for iteration index `s` (0 to 2^{n-k}-1), set bit `p_b` of the base index to `(s >> b) & 1`.

4. **Computing complement offsets.** For target qubits [q_0, q_1, ..., q_{k-1}], the j-th offset (j = 0 to 2^k - 1) is: `sum of (1 << q_b) for each b where (j >> b) & 1 == 1`. Matrix column j and row i use the same encoding: target qubit q_b has value `(j >> b) & 1`.

## Controlled Gates

A controlled gate applies U only when specified control qubits match specified values (0 or 1):

1. Treat both target qubits and control qubits as "fixed" — the iteration subspace excludes all of them.
2. Compute a **control offset**: for each control qubit with required value 1, set its bit in the offset.
3. The base index = iteration configuration bits OR control offset (control bits are pre-set).
4. Apply U to the target qubit subspace as before.

This means the iteration has 2^{n-k-m} steps (m = number of control qubits) and only modifies state entries where control qubits match their specified values.

## Standard Gate Definitions

All matrices use the convention that column j corresponds to input basis state j, row i to output basis state i.

| Gate | Matrix |
|------|--------|
| H | `(1/sqrt(2)) * [[1, 1], [1, -1]]` |
| X | `[[0, 1], [1, 0]]` |
| Y | `[[0, -i], [i, 0]]` |
| Z | `[[1, 0], [0, -1]]` |
| S | `[[1, 0], [0, i]]` |
| T | `[[1, 0], [0, exp(i*pi/4)]]` |
| RX(t) | `[[cos(t/2), -i*sin(t/2)], [-i*sin(t/2), cos(t/2)]]` |
| RY(t) | `[[cos(t/2), -sin(t/2)], [sin(t/2), cos(t/2)]]` |
| RZ(t) | `[[exp(-i*t/2), 0], [0, exp(i*t/2)]]` |
| SWAP | `[[1,0,0,0], [0,0,1,0], [0,1,0,0], [0,0,0,1]]` |

## Performance Characteristics

The subspace iteration approach is O(2^n * 2^k) per gate application, compared to O(2^{2n}) for the Kronecker product approach. For typical 1-qubit gates (k=1), this is O(2^n) — the theoretical minimum since every element must be touched. This enables simulation of circuits with 20+ qubits for single-qubit gates without excessive memory usage.
