CrossSim (Sandia National Labs' analog in-memory computing simulator, version 3.2.1) is installed and importable as `simulator`. A device characterization datasheet for an HfO2 bilayer RRAM is at `/app/device_datasheet.md`.

Create a CrossSim-compatible custom device model that implements the three error mechanisms described in the datasheet, integrate it with CrossSim's simulation engine, then quantify how each error source degrades matrix-vector multiply (MVM) accuracy and find the minimum hardware precision that keeps total error acceptable.

## Deliverables

**`/app/hfo2_rram.py`** — Device model class `HfO2BilayerRRAM` that integrates with CrossSim for MVM simulation.

**`/app/error_decomposition.py`** — Analysis script producing the results below.

**`/app/results.json`**:
```json
{
  "error_decomposition": {
    "quantization_only": <NRMSE with device errors disabled>,
    "programming_error": <NRMSE with programming error only>,
    "read_noise": <NRMSE with read noise only>,
    "drift_30d": <NRMSE with 30-day drift only>,
    "all_combined": <NRMSE with all errors enabled, t=30 days>
  },
  "dominant_error_source": "<key with highest individual NRMSE among programming_error, read_noise, drift_30d>",
  "optimal_cell_bits": <minimum in [2..10] achieving NRMSE < 0.05 with all errors at t=30d>,
  "optimal_adc_bits": <minimum from {4, 6, 8, 10, 12, 14, 16} achieving NRMSE < 0.05 at the optimal cell_bits>
}
```

## Experiment Parameters

- Weight matrix: 64x64 Gaussian, seed 123 (`np.random.RandomState(123).randn(64, 64)`)
- Input: `x[i] = sin(2*pi*3*i/64) + 0.5*cos(2*pi*7*i/64)`, i=0..63
- NRMSE metric: `||y - y_ideal|| / ||y_ideal||`, averaged over 50 trials for stochastic scenarios
- Hardware baseline: BALANCED core, Rmin=5kOhm, Rmax=500kOhm, cell_bits=6, 8-bit signed magnitude ADC with MAX range calibration