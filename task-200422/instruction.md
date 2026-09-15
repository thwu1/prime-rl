Assess whether a quantum processor's noise profile supports fault-tolerant operation with the rotated surface code. Determine the error suppression factor and project physical qubit overhead to achieve a per-round logical error rate below 10⁻¹².

## Noise Profile

- `after_clifford_depolarization`: 1×10⁻³
- `before_measure_flip_probability`: 2×10⁻³
- `after_reset_flip_probability`: 1×10⁻³
- `before_round_data_depolarization`: 1×10⁻³

## Environment

Stim circuits for `surface_code:rotated_memory_z` at distances 3, 5, 7 (rounds = 3d) are at `/app/circuits/d3.stim`, `/app/circuits/d5.stim`, `/app/circuits/d7.stim`. A draft analysis at `/app/draft_analysis.py` produces unreliable results.

## Deliverable

Write `/app/results.json`:

```json
{
  "noise_model": {
    "after_clifford_depolarization": ...,
    "before_measure_flip_probability": ...,
    "after_reset_flip_probability": ...,
    "before_round_data_depolarization": ...
  },
  "distances": {
    "3": {
      "rounds": ...,
      "num_qubits": ...,
      "num_detectors": ...,
      "num_observables": ...,
      "shots": ...,
      "logical_errors": ...,
      "per_shot_error_rate": ...,
      "per_round_error_rate": ...
    },
    "5": { "..." },
    "7": { "..." }
  },
  "exponential_fit": {
    "slope": ...,
    "intercept": ...,
    "r_squared": ...
  },
  "lambda_suppression_factor": ...,
  "projected_distance_for_1e12": ...,
  "projected_physical_qubits": ...
}
```

All fields required per distance entry. Minimum 100,000 shots per distance. `projected_distance_for_1e12` must be an odd integer — the minimum code distance for per-round logical error rate below 10⁻¹². `projected_physical_qubits` is the rotated surface code qubit count at that distance.