A nuclear reactor thermal-hydraulic safety model at `/app/model.py` computes two safety outputs — peak cladding temperature (`peak_clad_temp`) and departure from nucleate boiling ratio (`dnbr`) — from four uncertain input parameters. The model function `evaluate(x)` takes a list of four values and returns `[peak_clad_temp, dnbr]`. Input distributions and UQ method configuration are defined in `/app/config.json`.

Perform a global uncertainty quantification and sensitivity analysis of this model. Use the method and settings specified in `/app/config.json`. Write results to `/app/results.json` with this exact structure:

```json
{
  "statistics": {
    "<output_name>": {"mean": <float>, "variance": <float>, "std": <float>}
  },
  "sobol_indices": {
    "<output_name>": {
      "first_order": {"<input_name>": <float>, ...},
      "total_order": {"<input_name>": <float>, ...}
    }
  }
}
```

Output names must be `peak_clad_temp` and `dnbr`. Input names must be `power_level`, `inlet_temp_perturbation`, `pressure_factor`, and `flow_rate_factor` — matching the names in `/app/config.json`. Each statistic entry must contain `mean`, `variance`, and `std` as numeric values. Each Sobol entry must contain `first_order` and `total_order` dicts mapping every input name to a numeric sensitivity index.

## Acceptance Criteria

**Statistical accuracy**: The computed mean for each output must agree with a high-fidelity Monte Carlo reference (200,000 samples) to within 0.5% relative error. Variance must agree to within 5% relative error. The `std` field must exactly equal `sqrt(variance)` for each output.

**Nominal consistency**: Each output's computed mean must be within 5% relative error of the model evaluated at the nominal (center/mean) input values `[1.0, 0.0, 1.0, 1.0]`.

**Sobol index mathematical properties**: All first-order and total-order Sobol indices must be non-negative (tolerance: >= -0.01). The sum of first-order indices for each output must not exceed 1.05. The sum of total-order indices for each output must be at least 0.90. For each input, the total-order index must be at least as large as the corresponding first-order index (within 0.02 tolerance).

**Sensitivity rankings**: Results must reflect the underlying physics:
- For `peak_clad_temp`: `inlet_temp_perturbation` must be the dominant contributor (first-order Sobol > 0.3), `power_level` must be significant (> 0.05), and `pressure_factor` must be negligible (< 0.02).
- For `dnbr`: `power_level` must be the dominant contributor (first-order Sobol > 0.3).