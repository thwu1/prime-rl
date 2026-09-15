Implement a density-matrix-based quantum simulation engine for entanglement distillation under LOCC (Local Operations and Classical Communication) constraints by completing the stub at `/app/engine.py`.

## Problem

Given N noisy Bell pairs on 2N qubits with outside-in pairing (pair k uses qubits k and 2N-1-k; Alice holds 0..N-1, Bob holds N..2N-1), design distillation protocols that apply only local quantum gates and classically-conditioned corrections to purify the output pair (qubits N-1 and N). Noise applies independent bit-flip (X) with probability px and phase-flip (Z) with probability pz to one qubit of each perfect |Phi+> pair, yielding a Bell-diagonal state with coefficients a=(1-px)(1-pz), b=px(1-pz), c=(1-px)pz, d=px*pz.

Five scenarios of increasing difficulty are specified in `/app/spec.json`. For each, design an optimal distillation protocol and compute post-distillation fidelity and success probability via density matrix simulation through your engine.

## Required API

Implement these functions with exact signatures:

- `construct_bell_pair_dm(px, pz)` -> 4x4 density matrix for one noisy Bell pair in {|00>,|01>,|10>,|11>} basis
- `construct_n_pairs_dm(n, px, pz)` -> 2^(2N) x 2^(2N) density matrix for N pairs with outside-in pairing
- `validate_locc(gate_targets, n)` -> True iff all two-qubit gates act within one side
- `compute_fidelity_phi_plus(rho_2q)` -> fidelity F = <Phi+|rho|Phi+>
- `partial_trace(rho, keep_qubits, n_qubits)` -> reduced density matrix
- `run_all()` -> solve all 5 scenarios, write results to `/app/results.json`

## Output

Write `/app/results.json`:

```json
{
  "D1": {"fidelity": <float>, "success_probability": <float>},
  "D2": {"fidelity": <float>, "success_probability": <float>},
  "D3": {"fidelity": <float>, "success_probability": <float>},
  "D4": {"fidelity": <float>, "success_probability": <float>},
  "D5": {"fidelity": <float>, "success_probability": <float>}
}
```

All fidelities must exceed their respective scenario thresholds. The engine must perform actual density matrix simulation, not analytical formula shortcuts.