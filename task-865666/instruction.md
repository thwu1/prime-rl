Build a quantum error correction analysis pipeline at `/app/qec_pipeline.py` that benchmarks rotated surface code performance across multiple code distances and noise levels, producing a structured JSON report at `/app/results.json`.

Stim (stabilizer circuit simulator) and PyMatching (MWPM decoder) are pre-installed. Use `stim.Circuit.generated("surface_code:rotated_memory_z", ...)` to generate circuits with uniform circuit-level depolarizing noise — all four noise parameters (`after_clifford_depolarization`, `after_reset_flip_probability`, `before_measure_flip_probability`, `before_round_data_depolarization`) set to the same value `p`. Use `rounds = 3 * d` for each code distance `d`.

Sweep distances `d ∈ {3, 5, 7}` and noise levels `p ∈ {0.001, 0.002, 0.004, 0.006, 0.008, 0.01}`.

For each `(d, p)` configuration, the report must include:

- **Circuit metadata**: `num_qubits`, `num_detectors`, `num_observables`, `num_measurements`, and `shortest_graphlike_error_weight` (the length of `circuit.shortest_graphlike_error()`).
- **Error rates**: Run Monte Carlo sampling (≥10,000 shots) with PyMatching MWPM decoding. Record `num_shots`, `num_errors`, `logical_error_rate_per_shot`, and `logical_error_rate_per_round`. The per-round rate is: `ε_round = 1 - (1 - ε_shot)^(1/rounds)`.
- **Error suppression factors** Λ for consecutive distance pairs `(3→5)` and `(5→7)` at each noise level: `Λ = ε_round(d_low) / ε_round(d_high)`.
- **Threshold estimate**: the physical error rate where Λ ≈ 1 (i.e., increasing code distance stops helping). Estimate by interpolation across noise levels.
- **Footprint projection** at `p = 0.001`: fit `log(ε_round)` vs `d` linearly, project the distance `d*` needed for `ε_round < 10⁻¹²`, and compute `projected_physical_qubits = 2d*² - 1`.

The JSON must follow this structure (keys in `circuit_metadata` and `error_rates` use format `d<D>_p<P>`, e.g., `d3_p0.001`; keys in `suppression_factors` use `d<D1>_d<D2>_p<P>`):

```json
{
  "circuit_metadata": {
    "d3_p0.001": {
      "distance": 3, "rounds": 9, "noise_level": 0.001,
      "num_qubits": ..., "num_detectors": ..., "num_observables": ...,
      "num_measurements": ..., "shortest_graphlike_error_weight": ...
    }
  },
  "error_rates": {
    "d3_p0.001": {
      "distance": 3, "noise_level": 0.001, "num_shots": ..., "num_errors": ...,
      "logical_error_rate_per_shot": ..., "logical_error_rate_per_round": ...
    }
  },
  "suppression_factors": {
    "d3_d5_p0.001": {
      "d_low": 3, "d_high": 5, "noise_level": 0.001, "lambda": ...
    }
  },
  "threshold_estimate": ...,
  "footprint_projection": {
    "noise_level": 0.001,
    "target_error_rate_per_round": 1e-12,
    "projected_distance": ...,
    "projected_physical_qubits": ...
  }
}
```

Run `python3 /app/qec_pipeline.py` to generate the report.