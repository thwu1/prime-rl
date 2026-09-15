# Output Specification

All output files must contain valid JSON with numeric values as JSON numbers (not strings).

## /app/results/rate_capability.json

```json
{
  "0.2C": {"capacity_ah": <float>, "energy_wh": <float>, "avg_voltage_v": <float>, "max_temp_k": <float>},
  "0.5C": {"capacity_ah": <float>, "energy_wh": <float>, "avg_voltage_v": <float>, "max_temp_k": <float>},
  "1C":   {"capacity_ah": <float>, "energy_wh": <float>, "avg_voltage_v": <float>, "max_temp_k": <float>},
  "1.5C": {"capacity_ah": <float>, "energy_wh": <float>, "avg_voltage_v": <float>, "max_temp_k": <float>},
  "2C":   {"capacity_ah": <float>, "energy_wh": <float>, "avg_voltage_v": <float>, "max_temp_k": <float>}
}
```

- `capacity_ah`: total discharge capacity in amp-hours
- `energy_wh`: total discharge energy in watt-hours
- `avg_voltage_v`: average discharge voltage (energy / capacity)
- `max_temp_k`: peak cell temperature during discharge in kelvin

## /app/results/voltage_decomposition.json

```json
{
  "0.2C": {
    "reaction_overpotential_v": <float>,
    "concentration_overpotential_v": <float>,
    "electrolyte_ohmic_v": <float>,
    "solid_phase_ohmic_v": <float>
  },
  ... (same keys for "0.5C", "1C", "1.5C", "2C")
}
```

All values are absolute magnitudes in volts, evaluated at 50% depth of discharge.

## /app/results/analysis.json

```json
{
  "critical_crate": "<C-rate label string, e.g. '2C'>",
  "peukert_exponent": <float>,
  "dominant_loss": {
    "0.2C": "<mechanism>",
    "0.5C": "<mechanism>",
    "1C":   "<mechanism>",
    "1.5C": "<mechanism>",
    "2C":   "<mechanism>"
  }
}
```

Valid mechanism names: `"reaction_overpotential"`, `"concentration_overpotential"`, `"electrolyte_ohmic"`, `"solid_phase_ohmic"`.
