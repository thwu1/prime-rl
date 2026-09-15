`bloqade-tsim` is pre-installed. Use it to analyze the noise resilience of a [[7,1,3]] Steane code that encodes the logical state H T |+⟩.

Write `/app/analyze.py` that produces `/app/results.json` conforming to the schema below.

## Encoded Circuit Requirements

- 7 data qubits (indices 0–6), qubit 6 carries the logical information
- Encodes H T |+⟩ into the [[7,1,3]] Steane code with parameterized depolarizing noise rate `p`
- Exactly 3 detectors (Z-type stabilizer parity checks)
- Exactly 1 logical observable
- T-count of 1

Also build an unencoded single-qubit reference circuit preparing H T |+⟩ with depolarizing noise at rate `p`.

## Output Schema (`/app/results.json`)

All fields below are required.

### Structure (at p=0.01)

| Field | Type | Constraint |
|---|---|---|
| `num_qubits` | int | Must be 7 |
| `num_detectors` | int | Must be 3 |
| `num_observables` | int | Must be 1 |
| `tcount` | int | Must be 1 |

### Detector Error Model (at p=0.01)

| Field | Type | Constraint |
|---|---|---|
| `num_dem_errors` | int | Must be > 0 |
| `dem_error_probs` | list[float] | Length must equal `num_dem_errors`; each value strictly in (0, 1) |

### Noiseless Sampling (p=0, 200,000 shots)

| Field | Type | Constraint |
|---|---|---|
| `noiseless_obs_rate` | float | Fraction of shots where the logical observable is True; must be within ±0.005 of sin²(π/8) ≈ 0.14645 |
| `noiseless_det_rate` | float | Fraction of shots where any detector fired; must be exactly 0.0 |

### Noisy Sampling (p=0.01, 200,000 shots)

| Field | Type | Constraint |
|---|---|---|
| `noisy_det_rate` | float | Must be > 0.02 |
| `noisy_raw_obs_rate` | float | Must be in range (0.10, 0.25) |
| `noisy_postselected_obs_rate` | float | Observable rate after discarding shots where any detector fired; deviation from sin²(π/8) must be smaller than `noisy_raw_obs_rate`'s deviation from sin²(π/8) |

### Noise Sweep (200,000 shots each, p ∈ [0.001, 0.005, 0.01, 0.05, 0.1])

`sweep_results`: list of 5 objects ordered by ascending `p`, each containing:

| Field | Type | Constraint |
|---|---|---|
| `p` | float | The noise rate (must match the list above) |
| `postselected_obs_rate` | float | In [0, 1]; at p=0.001 must be within ±0.01 of sin²(π/8) |
| `detection_rate` | float | In [0, 1]; must increase monotonically across the sweep |
| `yield` | float | In (0, 1]; must decrease monotonically across the sweep |
| `physical_obs_rate` | float | Observable rate from the unencoded reference circuit; in [0, 1] |

At p=0.01: |postselected_obs_rate − sin²(π/8)| must be strictly less than |physical_obs_rate − sin²(π/8)| (the encoding must provide measurable advantage).