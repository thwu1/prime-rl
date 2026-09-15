CrossSim (Sandia's analog in-memory computing simulator) is installed as the `simulator` package at `/app/`. A 64-point complex DFT accelerator has been prototyped on analog crossbar arrays. Before committing to silicon, engineering needs two things: (1) a breakdown of how individual device non-idealities contribute to overall accuracy loss in the reference design, and (2) identification of the most cost-efficient architecture across the full design space.

## Reference Hardware Configuration

- Core: BITSLICED, 2 slices, bit_sliced.style=OFFSET. weight_bits=8, cell_bits=4
- Balanced style: ONE_SIDED, subtract_current_in_xbar=True. Offset style: DIGITAL_OFFSET
- Complex matrix and complex input enabled. Max subarray: 128×128. Weight percentile=100%. Input range [-1.0, 1.0]
- Device: Rmin=1000, Rmax=100000
- Programming error: NormalProportionalDevice, magnitude=0.05
- Read noise: NormalIndependentDevice, magnitude=0.03
- ADC: 6-bit SignMagnitudeADC, signed, range=MAX
- DAC: 8-bit SignMagnitudeDAC, signed, no input bitslicing

## Evaluation Conditions

The DFT accelerator operates on `scipy.linalg.dft(64)`. Evaluation uses 10 complex test vectors (dimension 64) generated with NumPy random seed 42 as `randn(10,64) + 1j*randn(10,64)`, normalized by the global maximum absolute value. For reproducibility, NumPy random seed must be set to 123 before each `AnalogCore` instantiation. Quality is measured as mean signal-to-noise ratio (dB) across all 10 test vectors.

## Design Space (72 configurations)

The full architecture design space is the Cartesian product of:

| Parameter | Values |
|---|---|
| Nslices | 1, 2, 4 |
| adc_bits | 6, 8, 10 |
| weight_mapping | BALANCED, OFFSET |
| input_slice_size | 1, 2, 4, 8 |

When Nslices=1, the core style is the weight_mapping directly; when Nslices>1, use BITSLICED with `bit_sliced.style` set to weight_mapping. Enable input bitslicing when input_slice_size < 8. All configurations use the same device error parameters as the reference.

Architecture cost is defined as: `Nslices × M × 2^adc_bits × ceil(8/input_slice_size)`, where M=2 for BALANCED and M=1 for OFFSET.

## Deliverable

Write `/app/analysis.json`:

```json
{
  "reference_analysis": {
    "baseline_snr": 0.0,
    "prog_error_only_snr": 0.0,
    "read_noise_only_snr": 0.0,
    "all_errors_snr": 0.0,
    "dominant_source": "programming_error or read_noise",
    "interaction_delta_db": 0.0
  },
  "pareto_frontier": [
    {"Nslices": 0, "adc_bits": 0, "weight_mapping": "...", "input_slice_size": 0, "snr_db": 0.0, "cost": 0}
  ],
  "dominated_count": 0,
  "recommended_config": {
    "Nslices": 0, "adc_bits": 0, "weight_mapping": "...", "input_slice_size": 0, "snr_db": 0.0, "cost": 0, "efficiency": 0.0
  }
}
```

- **reference_analysis**: `baseline_snr` is the SNR with all device non-idealities disabled (quantization-only floor). The `_only_snr` fields each have exactly one error source active. `all_errors_snr` has everything active. `dominant_source` is whichever single non-ideality causes the larger SNR degradation from baseline. `interaction_delta_db` captures whether the combined errors are superadditive (positive) or subadditive (negative) compared to the sum of individual contributions.
- **pareto_frontier**: All Pareto-optimal configurations sorted by ascending cost. A configuration is Pareto-optimal if no other has both lower-or-equal cost and higher-or-equal SNR with at least one strict inequality. `dominated_count` = 72 minus the frontier size.
- **recommended_config**: The Pareto-optimal configuration that maximizes `efficiency` = snr_db / cost.