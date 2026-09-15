Implement `/app/elastic_verifier.py`. It reads `/app/potential_params.json` and `/app/config.json` (both pre-existing) and produces `/app/results.json`.

**Inputs** (pre-existing at `/app/`):

- `potential_params.json`: Morse pair potential — `{"type":"morse","parameters":{"D":<eV>,"alpha":<1/Å>,"r0":<Å>,"cutoff":<Å>}}`
- `config.json`: `{"crystal_structure":"fcc"|"bcc"|"sc","approximate_lattice_constant":<Å>,"supercell_size":[nx,ny,nz],"perturbation_amplitude":<Å>,"random_seed":<int>}`

**Command:** `python3 /app/elastic_verifier.py` must exit 0 and write `/app/results.json`:

```json
{
  "equilibrium_lattice_constant": <float>,
  "elastic_constants": {
    "C11": <float, eV/angstrom^3>,
    "C12": <float, eV/angstrom^3>,
    "C44": <float, eV/angstrom^3>,
    "bulk_modulus": <float, eV/angstrom^3>
  },
  "force_verification": {
    "max_relative_error": <float>,
    "grade": "<A|B|C|D|F>",
    "num_atoms_tested": <int>,
    "num_components_tested": <int>,
    "num_outliers_excluded": <int>
  }
}
```

**Acceptance criteria:**

1. `equilibrium_lattice_constant`: energy-minimizing lattice constant for the given periodic cubic crystal using the configured supercell. Must fall within a physically reasonable range (roughly 2.5–6.0 Angstrom depending on structure).

2. `C11`, `C12`, `C44`: independent elastic constants of a cubic crystal in eV/angstrom^3. Must satisfy Born stability conditions: C11 > 0, C44 > 0, C11 > |C12|, and bulk_modulus > 0. Each elastic constant must be less than 50 eV/angstrom^3 in magnitude. For a central-force pair potential, the Cauchy relation C12 ≈ C44 must hold within 6% relative difference.

3. `bulk_modulus` must equal `(C11 + 2*C12) / 3` within 1e-6 relative tolerance.

4. Force verification compares analytical forces from the Morse potential against numerical force estimates on a randomly perturbed 2x2x2 non-periodic cluster built at the equilibrium lattice constant. Perturbation amplitude and random seed come from `config.json`. Force components whose numerical uncertainty is a statistical outlier must be excluded before computing `max_relative_error`. `num_atoms_tested` equals the total atom count in the 2x2x2 cluster (32 for FCC with 4 atoms/cell, 16 for BCC with 2 atoms/cell, 8 for SC with 1 atom/cell). `num_components_tested` equals `3 * num_atoms_tested`.

5. Grade thresholds on `max_relative_error`: A < 1e-8, B < 1e-5, C < 1e-2, D < 10, F >= 10. A smooth Morse potential must achieve grade A or B.

6. Must produce correct results for any valid Morse parameters and any of fcc/bcc/sc structures. No hardcoded physical constants or pre-computed results. The equilibrium lattice constant is cross-validated within 1e-4 relative tolerance and C11 within 1% relative tolerance against independent computations.
