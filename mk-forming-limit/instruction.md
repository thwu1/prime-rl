Implement a Marciniak-Kuczynski (M-K) forming limit curve predictor at `/app/mk_flc.py`.

**Usage:** `python3 /app/mk_flc.py <config_json> <output_csv>`

**Input config** (`config_json`): JSON with this structure:

```json
{
  "yield_function": {
    "type": "von_mises" or "hill48",
    "R0": float, "R45": float, "R90": float
  },
  "hardening": {"type": "swift", "K": float, "eps0": float, "n": float},
  "mk_params": {"f0": float, "psi0_deg": float},
  "alpha_range": [float, ...]
}
```

`R0`/`R45`/`R90` are Lankford coefficients (present only for `hill48`). `f0` is the initial band-to-sheet thickness ratio (0 < f0 < 1). `psi0_deg` is the initial groove angle in degrees (0 for all evaluations). `alpha_range` lists stress ratios sigma2/sigma1 in [0, 1]; each value produces one FLC point.

**Output** (`output_csv`): CSV with header `minor_strain,major_strain`, one row per converged point, sorted ascending by `minor_strain`. Strains are true (logarithmic) principal strains of the uniform region at necking onset.

The M-K model predicts sheet metal forming limits by analyzing strain localization in a sheet containing a pre-existing band of reduced thickness under proportional plane-stress loading. The band's stress state evolves subject to force equilibrium (traction continuity across the band interface) and geometric strain compatibility (continuous deformation parallel to the band). Necking onset occurs when the equivalent strain-rate ratio between band and uniform region exceeds 10.

**Yield functions** (plane stress, sigma12 = 0):
- `von_mises`: isotropic
- `hill48`: anisotropic, parameterized by Lankford coefficients R0, R45, R90

**Hardening:** Swift law: sigma_bar = K * (eps0 + eps_bar)^n

Handle the plane-strain singularity where the minor strain rate vanishes. Note that the stress ratio at which plane strain occurs differs between yield functions.

Seed configurations are provided at `/app/material_vm.json` (von Mises) and `/app/material_h48.json` (Hill48).
