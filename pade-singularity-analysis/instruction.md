The file `/app/config.json` contains exact rational Taylor series coefficients for three analytic functions (`f1`, `f2`, `f3`), along with complex evaluation points and diagonal Pade approximant orders.

A previous analysis pipeline processed this data and wrote `/app/results.json`. The output contains multiple errors — convergence radii, singularity classifications, singularity locations, and approximant evaluations are all unreliable.

Produce a corrected `/app/results.json` that conforms to the schema below, where:

- Each convergence radius is accurate to at least 6 significant digits.
- Each singularity type is correctly classified as exactly one of: `"polar"`, `"logarithmic_branch"`, or `"algebraic_branch"`.
- Each nearest singularity location is accurate to at least 2 significant digits.
- Each Pade approximant evaluation is accurate to at least 35 significant decimal digits.

Do not modify `/app/config.json`.

## Output Schema for `/app/results.json`

The file must be valid JSON with the following structure. Top-level keys are `"f1"`, `"f2"`, `"f3"`. Each maps to an object with this schema:

```
{
  "<function_name>": {
    "convergence_radius": <string>,
    "singularity_type": <string>,
    "nearest_singularity": {
      "re": <string>,
      "im": <string>
    },
    "pade_evaluations": {
      "<m>_<n>": {
        "<point_index>": {
          "re": <string>,
          "im": <string>
        }
      }
    }
  }
}
```

Field definitions:

| Field | Type | Description |
|---|---|---|
| `convergence_radius` | string | Decimal string representation of the convergence radius (e.g. `"3.0"` or `"0.5"`). |
| `singularity_type` | string | One of the exact literals: `"polar"`, `"logarithmic_branch"`, `"algebraic_branch"`. |
| `nearest_singularity.re` | string | Decimal string for the real part of the nearest singularity location. |
| `nearest_singularity.im` | string | Decimal string for the imaginary part of the nearest singularity location. |
| `pade_evaluations` | object | Keys are `"<m>_<n>"` matching each `[m, n]` pair from `config.json`'s `pade_orders` (e.g. `"5_5"`, `"10_10"`, `"14_14"`). |
| `pade_evaluations.<m>_<n>` | object | Keys are stringified indices `"0"`, `"1"`, `"2"`, `"3"` corresponding to entries in `config.json`'s `evaluation_points`. |
| `pade_evaluations.<m>_<n>.<idx>.re` | string | Decimal string for the real part of the Pade approximant value, with at least 35 significant digits. |
| `pade_evaluations.<m>_<n>.<idx>.im` | string | Decimal string for the imaginary part of the Pade approximant value, with at least 35 significant digits. |

All numeric values are encoded as decimal strings (not JSON numbers) to preserve arbitrary precision.