Five noise scenarios in `/app/scenarios.json` each define a Bell-diagonal channel on shared entangled pairs between Alice and Bob. Design LOCC-compliant quantum circuits that consume multiple noisy pairs to distill one pair with higher fidelity, simulate the protocols via density-matrix methods, and report numerical results.

## Noise Model

A noisy Bell pair has density matrix rho = p1|Phi+><Phi+| + p2|Phi-><Phi-| + p3|Psi+><Psi+| + p4|Psi-><Psi-|, with fidelity F = <Phi+|rho|Phi+>. Each scenario specifies mixing weights, a maximum number of input pairs (<=8), and a fidelity threshold.

## Qubit Layout

For N input pairs: 2N qubits. Alice holds q_0..q_{N-1}, Bob holds q_N..q_{2N-1}. Pair k maps to qubits k and 2N-1-k (outside-in). The output pair is the innermost: (q_{N-1}, q_N).

## LOCC Constraint

Two-qubit gates may only act within one party's qubits — never across the Alice/Bob boundary. Single-qubit gates, measurements, and classical feedforward are unrestricted. An LOCC validator is provided at `/app/validate_locc.py` (usage: `python3 /app/validate_locc.py <qasm_file> <num_bell_pairs>`).

## Objective

For each scenario, choose the number of input pairs N, design a distillation circuit, and determine the post-selected measurement outcomes on ancilla qubits that yield the distilled state on the output pair. Maximize claim_strength = fidelity * success_probability while exceeding the scenario's fidelity threshold.

## Deliverables

1. `/app/circuits/S1.qasm` through `S5.qasm` — OpenQASM 3.0 circuit files, one per scenario.

2. `/app/simulator.py` — exports `compute_fidelity_phi_plus(rho)` accepting a 4x4 complex numpy array, returning fidelity w.r.t. |Phi+>.

3. `/app/results.json` — keys "S1".."S5", each with fields: `fidelity` (float), `success_probability` (float), `claim_strength` (float), `num_bell_pairs` (int), `meets_threshold` (bool).