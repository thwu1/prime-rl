The environment includes the TABOO Fortran 90 program source and related materials under `/app/reference/`, and an Earth model configuration at `/app/data/earth_model.dat`. A Fortran compiler (`gfortran`) is available.

The configuration file uses the TABOO `Make_Model` keyword format, specifying model-type identifiers (number of viscoelastic layers, profile code), lithospheric thickness, and layer viscosities. The `Harmonic_Degrees` section specifies the degree range. Resolving these identifiers to physical layer parameters (radii, densities, shear rigidities) requires consulting the reference Fortran source. The task type is loading (not tidal).

Create `/app/love_numbers.py` that reads `/app/data/earth_model.dat`, resolves the complete physical model, and computes viscoelastic loading Love numbers and the relaxation-mode spectrum for a self-gravitating, incompressible, layered Earth.

Running `python3 /app/love_numbers.py` must write `/app/output/results.json` containing:

```json
{
  "degrees": [2, 3, ...],
  "elastic": {"h": [...], "l": [...], "k": [...]},
  "fluid":   {"h": [...], "l": [...], "k": [...]},
  "spectrum": {"2": [s1, s2, ...], "3": [...], ...},
  "residues": {
    "h": {"2": [r1, ...], ...},
    "l": {"2": [r1, ...], ...},
    "k": {"2": [r1, ...], ...}
  }
}
```

`degrees` spans the full range from the configuration. `elastic` and `fluid` each contain `h`, `l`, `k` arrays of length `len(degrees)`, ordered by degree. `spectrum` maps each degree (string key) to its physical relaxation rates (kyr⁻¹) — only real-valued, strictly negative eigenvalues of the secular polynomial. `residues` maps each component to a degree-keyed dictionary of viscoelastic amplitudes, element-wise aligned with spectrum entries for that degree.

Verification criteria:

- Elastic `h` and `l` at sampled degrees: relative tolerance 5 x 10⁻⁴
- Fluid `h` and `l` at sampled degrees: relative tolerance 5 x 10⁻³
- Spectrum mode count and values at sampled degrees: relative tolerance 5 x 10⁻³
- Self-consistency for each X in {h, l, k} at sampled degrees: X_f = X_e - sum_j(X_v(j) / s(j)) within 1 x 10⁻⁸ relative tolerance
- All elastic `h` values must be negative across all degrees
- All elastic `k` values must be negative across all degrees
- Fluid `h` must be strictly less than elastic `h` at every degree
