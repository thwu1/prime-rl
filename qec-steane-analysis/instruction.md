Build `/app/analyze.py` using `bloqade-tsim` (pre-installed; `import tsim`) to simulate the [[7,1,3]] Steane code with logical T-gate injection. The script must produce `/app/results.json`.

## Problem

The [[7,1,3]] Steane code encodes 1 logical qubit into 7 physical qubits with distance 3. Construct a tsim circuit that applies a logical T gate, encodes into the Steane code, and measures all qubits. The circuit must include stabilizer check detectors and a logical observable.

The resulting circuit must have exactly: 7 qubits, 7 measurements, 3 detectors, 1 observable, and T-count = 1. The noiseless logical observable should yield 1 with probability sin²(π/8) ≈ 0.1464 (tolerance ±0.015).

## Noise Analysis

Add circuit-level depolarizing noise for p ∈ {0.001, 0.005, 0.01, 0.05, 0.1}. Sample ≥10,000 shots per configuration. For each noise level, extract the detector error model (DEM) via `circuit.detector_error_model()` and compute the statistics described below.

## Output Schema

`/app/results.json`:

```json
{
  "circuit": {"num_qubits": int, "num_measurements": int, "num_detectors": int, "num_observables": int, "t_count": int},
  "noiseless": {"observable_rate": float},
  "noisy": [{"p": float, "num_dem_mechanisms": int, "num_l0_flipping_mechanisms": int, "raw_obs_rate": float, "detection_event_rate": float, "post_selected_obs_rate": float, "post_selection_yield": float}]
}
```

### Field Definitions

- `observable_rate` / `raw_obs_rate`: fraction of shots where the logical observable = 1
- `post_selected_obs_rate`: fraction where observable = 1 among shots with no detector events (null if no shots survive post-selection)
- `post_selection_yield`: fraction of shots with zero detection events
- `detection_event_rate`: fraction of shots with ≥1 detection event
- `num_dem_mechanisms`: count of `error(...)` entries in the DEM
- `num_l0_flipping_mechanisms`: of those, how many include logical observable L0 among their targets (must not exceed `num_dem_mechanisms`)
- `noisy` array sorted ascending by `p`

## Expected Physical Behavior

All rates must be valid probabilities in [0, 1]. The following constraints must hold:

- Every noise level must produce ≥1 DEM error mechanism, and ≥1 mechanism must flip L0
- Detection event rate must be positive at every noise level and must increase from lowest to highest p
- Post-selection yield must decrease from lowest to highest p
- At moderate noise (0.005 ≤ p ≤ 0.05), post-selection should bring the observable rate closer to sin²(π/8) than the raw rate (within ±0.02 tolerance)
- At p = 0.1, raw observable rate must deviate from sin²(π/8) by more than 0.01
- At p ≤ 0.002, raw observable rate must remain within 0.03 of sin²(π/8)