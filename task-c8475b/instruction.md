Create `/app/model_fidelity.py` — a Python script using PyBaMM (pre-installed in the environment) to compare the Single Particle Model (SPM) and Single Particle Model with electrolyte (SPMe) for a lithium-ion cell. Use the Chen2020 parameter set (LG M50, ~5 Ah NMC/graphite cell, voltage window 2.5–4.2 V). The script must write all results to `/app/results.json`.

## Analysis Requirements

**Rate capability comparison**: Simulate galvanostatic discharges at C-rates C/20, C/5, C/2, 1C, 2C, and 3C using both SPM and SPMe. Set the discharge current via the `Current function [A]` parameter (positive current = discharge) and solve over a sufficient time span for the model to reach the lower voltage cutoff. For each rate, compute: delivered capacity (Ah), maximum and RMS voltage error between the two models (mV), and relative capacity difference (%). Compare voltages on a common discharge-capacity basis by interpolating both voltage curves onto a shared capacity grid.

**Incremental capacity analysis (ICA)**: At C/20, compute |dQ/dV| vs V for both models with appropriate numerical smoothing. Identify peak voltage positions (local maxima of |dQ/dV| exceeding 1 Ah/V).

**Critical C-rate**: Determine the lowest tested C-rate at which SPM RMS voltage error first exceeds 10 mV relative to SPMe. Report `null` if no tested rate exceeds this threshold.

**Voltage decomposition**: Using the 1C SPMe discharge solution, extract the open-circuit voltage, terminal voltage, and total overpotential at the point where 50% of total discharge capacity has been delivered. Report OCV and terminal voltage in volts and total overpotential in millivolts.

**Discharge energy at 1C**: Compute total discharge energy (Wh) for both SPM and SPMe at 1C by integrating V × I over time. Report the percentage difference between models.

## Output Format (`/app/results.json`)

```json
{
  "discharge_comparison": {
    "C/20": {
      "spm_capacity_Ah": 0.0,
      "spme_capacity_Ah": 0.0,
      "max_voltage_error_mV": 0.0,
      "rms_voltage_error_mV": 0.0,
      "capacity_diff_pct": 0.0
    },
    "C/5": { "...": "same fields" },
    "C/2": { "...": "same fields" },
    "1C": { "...": "same fields" },
    "2C": { "...": "same fields" },
    "3C": { "...": "same fields" }
  },
  "ica_peaks": {
    "spm": {"peak_voltages_V": [3.4, 3.6]},
    "spme": {"peak_voltages_V": [3.4, 3.6]}
  },
  "critical_crate": 0.5,
  "voltage_decomposition_1C_50pct": {
    "ocv_V": 3.65,
    "terminal_voltage_V": 3.55,
    "total_overpotential_mV": 100.0
  },
  "energy_1C": {
    "spm_energy_Wh": 17.0,
    "spme_energy_Wh": 16.8,
    "energy_difference_pct": 1.2
  }
}
```

The script must complete within 5 minutes.