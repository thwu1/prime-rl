Five CSV files at `/app/data/tga_beta_02.csv` through `/app/data/tga_beta_20.csv` contain thermogravimetric analysis (TGA) data for a material whose total mass-loss conversion is the weighted sum of two independent first-order decomposition reactions, plus small Gaussian measurement noise. The files correspond to constant heating rates of 2, 5, 10, 15, and 20 K/min. Each file has columns `temperature_K` and `total_conversion`.

Build `/app/analyze.py` that, when run via `python3 /app/analyze.py`, exits with code 0 and writes `/app/results.json` conforming to the schema below.

**Output schema** (`/app/results.json`):

```json
{
  "reaction_1": {
    "activation_energy_J_mol": <number>,
    "pre_exponential_factor_per_s": <number>,
    "weight_fraction": <number>
  },
  "reaction_2": {
    "activation_energy_J_mol": <number>,
    "pre_exponential_factor_per_s": <number>,
    "weight_fraction": <number>
  },
  "predictions_beta_7_5": {
    "480.0": <number>,
    "520.0": <number>,
    "540.0": <number>,
    "560.0": <number>,
    "580.0": <number>,
    "620.0": <number>,
    "700.0": <number>
  }
}
```

All values must be JSON numbers (int or float, not strings). Each reaction follows first-order Arrhenius kinetics.

**Constraints:**

- `reaction_1` must have strictly lower `activation_energy_J_mol` than `reaction_2`.
- All activation energies, pre-exponential factors, and weight fractions must be positive.
- Weight fractions of the two reactions must sum to 1.0 (within 0.01 tolerance).
- `predictions_beta_7_5` contains total conversion values at the listed temperatures (in Kelvin) for a heating rate of 7.5 K/min — a rate not present in the input data.
- All prediction values must lie in [0, 1] and must be monotonically non-decreasing with temperature.

**Success criteria:**

- Both activation energies within 8% relative error of ground truth.
- Both pre-exponential factors within 1.5 orders of magnitude (log₁₀ scale) of ground truth.
- Both weight fractions within 0.06 absolute error of ground truth.
- All seven prediction values within 0.04 absolute error of ground truth.
