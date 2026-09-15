Noisy Stim circuits for a rotated surface code Z-memory experiment are at `/data/circuit_d3.stim` (code distance 3) and `/data/circuit_d5.stim` (code distance 5). Both use uniform depolarizing noise with error rate p=0.001 and 3 syndrome measurement rounds. Generation parameters are in `/data/circuit_params.json`.

Implement `/app/noise_budget.py` to decompose the d=3 circuit's noise into four isolated mechanisms and compute each mechanism's error budget fraction:

| Mechanism    | Description |
|-------------|-------------|
| `gate_noise` | Depolarization after Clifford gates (DEPOLARIZE1 after single-qubit gates, DEPOLARIZE2 after two-qubit gates) |
| `idle_noise` | Depolarization on idle data qubits between syndrome extraction rounds |
| `prep_noise` | Bit-flip errors immediately following qubit reset operations |
| `meas_noise` | Bit-flip errors immediately preceding measurement operations |

For each mechanism, produce a Stim circuit variant of the d=3 circuit where **only** that noise source is active (all other noise removed) with all non-noise operations, detectors, and observables intact. Extract each variant's detector error model (DEM) and compute:

- `dem_error_count`: number of error entries in the DEM
- `total_error_weight`: sum of all error probabilities in the DEM
- `budget_fraction`: mechanism's total_error_weight divided by the full d=3 circuit's total DEM weight

Also extract circuit-level properties (qubit count, detector count, observable count, total DEM weight) at both code distances.

Write output to `/app/error_budget.json`:

```json
{
  "mechanisms": {
    "gate_noise": {"dem_error_count": <int>, "total_error_weight": <float>, "budget_fraction": <float>},
    "idle_noise": {"dem_error_count": <int>, "total_error_weight": <float>, "budget_fraction": <float>},
    "prep_noise": {"dem_error_count": <int>, "total_error_weight": <float>, "budget_fraction": <float>},
    "meas_noise": {"dem_error_count": <int>, "total_error_weight": <float>, "budget_fraction": <float>}
  },
  "full_circuit": {
    "num_qubits_d3": <int>,
    "num_qubits_d5": <int>,
    "num_detectors_d3": <int>,
    "num_detectors_d5": <int>,
    "num_observables_d3": <int>,
    "num_observables_d5": <int>,
    "total_dem_weight_d3": <float>,
    "total_dem_weight_d5": <float>
  }
}
```