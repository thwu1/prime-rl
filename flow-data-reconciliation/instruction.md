An industrial pipe network has 16 mass flow sensors (`m1`–`m16`) distributed across a system of junctions where pipes merge and split. The measurements are noisy, and some sensors carry unknown systematic biases (gross errors) that corrupt readings well beyond normal measurement noise. Conservation of mass at each junction provides physical redundancy that makes both measurement correction and sensor fault detection possible.

## Input Files

- `/app/measurements.csv` — Semicolon-delimited. Columns: variable name, measured value (kg/s), half-width confidence interval. The half-width confidence interval is defined as `w_i = 1.96 × σ_i` where `σ_i` is the measurement standard deviation.
- `/app/correlation.csv` — Semicolon-delimited lower-triangular correlation matrix. Off-diagonal elements `r_ij` define the covariance as `S_ij = r_ij × σ_i × σ_j`. Variables absent from the matrix have zero correlation.
- `/app/constraints.json` — Linear mass balance constraint equations at junction nodes (each equals zero).

## Requirements

Create `/app/reconcile.py` that produces corrected flow measurements and identifies faulty sensors. Specifically, the program must produce:

- **Corrected measurements** for all 16 sensors that exactly satisfy every mass balance constraint, accounting for measurement uncertainties and inter-sensor correlations when determining corrections.
- **Faulty sensor identification** — some sensors are so biased that the corrected result is statistically inconsistent at 95% confidence when those sensors are treated as reliable. These faulty sensors must be detected and reported in the order they are identified.
- **Updated uncertainty estimates** (half-width confidence intervals) for each sensor after correction.
- **Statistical validation** — the final corrected result (after handling faulty sensors) must be statistically consistent with the expected measurement noise, confirmed by a chi-square goodness-of-fit test using the number of independent constraints as degrees of freedom.

Run: `cd /app && python3 reconcile.py`

## Output Files (write to `/app/results/`)

- `reconciled_values.csv` — Comma-delimited with header: `variable_name,measured_value,reconciled_value,measured_hwci,reconciled_hwci`
- `gross_errors.json` — JSON list of detected gross error variable names in detection order
- `analysis.json` — JSON with keys: `global_test_statistic` (float), `chi_square_critical` (float), `global_test_passed` (bool), `num_independent_constraints` (int), `detected_gross_errors` (list)