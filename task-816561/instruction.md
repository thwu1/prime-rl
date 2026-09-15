Create `/app/toric_decoder.py` — a module that decodes independent X and Z errors on the d×d toric code and estimates logical error rates. `pymatching` and `numpy` are available in the environment.

## Toric Code Lattice

The d×d toric code lives on a square lattice with periodic boundary conditions (torus). It has 2d² qubits on edges, d² Z-stabilizers on vertices, d² X-stabilizers on faces, and encodes 2 logical qubits. Qubit indexing: horizontal edge h(i,j) = i\*d+j connects vertex (i,j) to vertex (i,(j+1)%d); vertical edge v(i,j) = d²+i\*d+j connects vertex (i,j) to vertex ((i+1)%d,j). All indices are 0-based. Support d ≥ 3.

## Logical Observables

- X observable 0: parity of X errors on {h(i,0) : 0 ≤ i < d}
- X observable 1: parity of X errors on {v(0,j) : 0 ≤ j < d}
- Z observable 0: parity of Z errors on {h(0,j) : 0 ≤ j < d}
- Z observable 1: parity of Z errors on {v(i,0) : 0 ≤ i < d}

## Required Functions

- `build_z_matching(d, p)` → `pymatching.Matching` — returns a decoder that, given Z-stabilizer syndromes, predicts X logical observable values. The parameter `p` is the per-qubit error probability.
- `build_x_matching(d, p)` → `pymatching.Matching` — returns a decoder that, given X-stabilizer syndromes, predicts Z logical observable values.
- `z_syndrome(d, x_errors)` — Z-stabilizer syndrome from X errors. Input shape `(num_shots, 2d²)` uint8, output shape `(num_shots, d²)` uint8.
- `x_syndrome(d, z_errors)` — X-stabilizer syndrome from Z errors. Same shapes.
- `actual_x_observables(d, x_errors)` — ground-truth X observable values. Output shape `(num_shots, 2)` uint8.
- `actual_z_observables(d, z_errors)` — ground-truth Z observable values. Same shape.
- `logical_error_rate(d, p, num_shots, seed)` → float — Monte Carlo logical error rate under independent noise where each qubit gets an X error with probability `p` and a Z error with probability `p` independently. Sample X errors first, then Z errors, from `numpy.random.default_rng(seed)`. A logical error occurs when any decoded observable disagrees with the ground truth for either error type.
- `estimate_threshold(distances, p_values, num_shots, seed)` → dict mapping `(d, p)` tuples to logical error rates. Per-point seed: `seed + d*1000 + p_index` where `p_index` is the index of `p` in `p_values`.