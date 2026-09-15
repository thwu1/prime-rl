Implement a Python CLI tool at `/app/dispersion.py` that computes Lamb wave dispersion curves (phase velocity and group velocity vs. frequency) for free elastic multilayered anisotropic plates.

**Usage:**
```
python3 /app/dispersion.py <config.yaml> -o <output.json>
```

**Configuration format** (YAML; two configs provided at `/app/configs/`):

- `material.name` (string), `material.density` (kg/m³), `material.stiffness_GPa` (Voigt notation: `C11`–`C66` for upper-triangle of the 6×6 elastic stiffness matrix)
- `layup.orientations` (layer angles, degrees), `layup.thicknesses` (per-layer, mm), `layup.repetitions` (int), `layup.symmetric` (bool — if true, mirror the repeated super layer)
- `propagation_angle` (degrees)
- `analysis.frequency_min`, `analysis.frequency_max` (kHz), `analysis.frequency_steps`, `analysis.num_modes`, `analysis.phase_velocity_max` (m/ms), `analysis.phase_velocity_steps`

Only the decoupled case is supported: each layer's fiber-to-propagation angle must be 0° or 90°. Exit with code 1 and a descriptive error on stderr for any other configuration.

**Output JSON schema:**
```json
{
  "metadata": {
    "material": "<name>",
    "total_thickness_mm": "<float>",
    "num_layers": "<int>",
    "method": "SMM",
    "propagation_angle_deg": "<float>"
  },
  "modes": [
    {
      "index": "<int>",
      "phase_velocity": [["<freq_kHz>", "<cp_m_per_ms>"], "..."],
      "group_velocity": [["<freq_kHz>", "<cg_m_per_ms>"], "..."]
    }
  ]
}
```

- Modes ordered by ascending phase velocity at the lowest reported frequency
- Velocities in m/ms (= km/s), frequencies in kHz
- Group velocities physically bounded: no values exceeding 15 m/ms

**Provided configurations at `/app/configs/`:**
- `aluminum_1mm.yaml`: single-layer isotropic aluminum, 1 mm thick
- `composite_0_90_2s.yaml`: T800M913 carbon/epoxy [0/90]₂ₛ cross-ply laminate, 8 layers, 1 mm total

Both must produce physically correct dispersion curves with at least 2 modes. For the aluminum case, the lowest symmetric-like mode at low frequency-thickness products must exhibit a phase velocity near the known plate velocity (~5.4 km/s). Phase velocities must agree with independent solutions of the Rayleigh-Lamb characteristic equation within 5% at representative frequencies.
