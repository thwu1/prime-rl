Given powder X-ray diffraction data in `/app/observed_peaks.json` and crystallographic information in `/app/structure_info.json`, create `/app/refine.py` that indexes the observed diffraction peaks against the known crystal structure, refines the unit cell parameters, and identifies impurity peaks.

The observed data contains 121 measured 2-theta peak positions from a sample that is predominantly PbSO4 (orthorhombic, space group Pnma, #62) but includes a minor impurity phase contributing spurious peaks that cannot be indexed within the PbSO4 structure. A zero-point instrument offset may be present, shifting all measured angles by a constant amount.

Running `python3 /app/refine.py` must produce `/app/results.json` with this schema:

```json
{
  "refined_lattice_parameters_angstrom": {"a": ..., "b": ..., "c": ...},
  "zero_shift_degrees": ...,
  "peak_assignments": [
    {"peak_index": 0, "two_theta_observed": ..., "hkl": [h, k, l], "two_theta_calculated": ..., "is_impurity": false},
    {"peak_index": 1, "two_theta_observed": ..., "hkl": null, "two_theta_calculated": null, "is_impurity": true}
  ],
  "rms_residual_degrees": ...,
  "n_indexed": ...,
  "n_impurity": ...
}
```

Requirements:

- `peak_assignments` must contain exactly 121 entries (one per observed peak), ordered by `peak_index` (0-based, contiguous, covering indices 0 through 120).
- Peaks belonging to the main PbSO4 phase must have `hkl` as a 3-element integer list and a float `two_theta_calculated`. Only reflections permitted by Pnma systematic absence conditions may be assigned.
- Impurity peaks must have `"is_impurity": true`, `"hkl": null`, and `"two_theta_calculated": null`.
- `n_indexed + n_impurity` must equal 121 (the total peak count).
- `n_impurity` must equal the count of entries with `"is_impurity": true` in `peak_assignments`.

Acceptance criteria:

- Refined lattice parameters must each be within 0.015 angstrom of the true values.
- `zero_shift_degrees` must be within 0.02 degrees of the true offset.
- `rms_residual_degrees` (RMS of observed minus calculated 2-theta for indexed peaks only) must be positive and below 0.03 degrees.
- At least 100 peaks must be indexed (`n_indexed` >= 100).
- Between 5 and 12 impurity peaks must be detected (`n_impurity` in [5, 12]).
- At least 5 of the detected impurity peaks must be correctly identified (matching the true impurity positions in the data).
- At least 95% of Miller index assignments for main-phase peaks must be correct.
