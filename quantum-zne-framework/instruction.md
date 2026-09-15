`/app/simulator.py` is a density-matrix quantum circuit simulator with per-gate depolarizing noise. Study its source code — it exposes gate definitions, adjoint mappings, and the noise channel implementation. Identity circuits in `/app/circuits/` evaluate to 1.0 under zero noise but degrade significantly at `noise_level=0.01`.

Build an error mitigation system that recovers corrected expectation values closer to the noiseless ideal. The entry point must be `/app/run_benchmark.py`, processing every `.json` circuit in `/app/circuits/` and writing results to `/app/results/benchmark.json`.

Output format — JSON object keyed by circuit `id`, each entry:

```json
{
  "ideal": 0.0,
  "unmitigated": 0.0,
  "scale_factors": [1, 3, 5],
  "noisy_values": [0.0, 0.0, 0.0],
  "richardson": 0.0,
  "polynomial_2": 0.0,
  "exponential": 0.0,
  "best_method": "method_name"
}
```

- `ideal`: noiseless expectation value
- `unmitigated`: expectation at `noise_level=0.01`, no correction applied
- `scale_factors`: noise amplification levels used
- `noisy_values`: expectations at each amplified noise level, monotonically decreasing
- `richardson`, `polynomial_2`, `exponential`: corrected estimates from three distinct extrapolation approaches
- `best_method`: one of `"richardson"`, `"polynomial_2"`, `"exponential"` — whichever is closest to `ideal`

All corrected estimates must improve on the unmitigated value. For single-qubit circuits, the `exponential` estimate must be within 0.05 of ideal. The pipeline must generalize to any valid identity circuit added to `/app/circuits/`.