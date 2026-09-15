Create `/app/transposer.py` that performs a complete IEC 60193 model-to-prototype hydraulic transposition for a Francis turbine and produces three output artifacts. Invoke with `python3 /app/transposer.py` (no arguments).

**Input data** (pre-loaded in `/app/data/`):

- `model_tests.csv` — Twelve operating points across three guide-vane openings and four speeds. Columns: `point_id`, `gvo_pct`, `n_rpm`, `p1_kPa` (gauge), `p2_kPa` (gauge), `Q_ls` (litres/s), `T_Nm` (shaft torque), `water_temp_C`.
- `site_config.json` — Model geometry (reference diameter, measurement section areas, elevation difference, lab altitude, submergence), prototype parameters (diameter, specific energy, turbine type), site conditions (altitude, water temperature, tailwater and reference elevations), measurement uncertainties, and critical sigma.
- `water_properties.csv` — Temperature-indexed lookup: density, kinematic viscosity, vapor pressure. Linearly interpolate between entries.

**Output 1 — `/app/output/results.json`:**
```json
{
  "points": [{"point_id": 0, "E_Jkg": 0.0, "nED": 0.0, "QED": 0.0, "TED": 0.0,
    "eta_model": 0.0, "Re_model": 0.0, "Re_prototype": 0.0,
    "delta_eta": 0.0, "eta_prototype": 0.0, "sigma_model": 0.0, "f_eta_pct": 0.0}],
  "bep": {"point_id": 0, "eta_prototype": 0.0, "nED": 0.0, "QED": 0.0},
  "prototype_bep": {"Q_m3s": 0.0, "n_rpm": 0.0, "P_MW": 0.0},
  "cavitation": {"p_atm_Pa": 0.0, "p_vapor_Pa": 0.0, "sigma_plant": 0.0,
    "sigma_critical": 0.0, "safety_margin": 0.0, "is_safe": false}
}
```

**Output 2 — `/app/output/results.db`:** SQLite database with three tables:
- `operating_points` — one row per point, columns matching JSON `points` fields (all REAL except `point_id` INTEGER).
- `bep_summary` — single row: `point_id` INTEGER, `eta_prototype`, `nED`, `QED`, `Q_m3s`, `n_rpm`, `P_MW` (all REAL except point_id).
- `cavitation` — single row: `p_atm_Pa`, `p_vapor_Pa`, `sigma_plant`, `sigma_critical`, `safety_margin` (all REAL), `is_safe` (INTEGER 0/1).

**Output 3 — `/app/output/hill_chart.svg`:** Gnuplot-generated SVG visualization of prototype efficiency against IEC dimensionless speed and discharge coefficients. Must be valid SVG with gnuplot provenance metadata.

BEP is the operating point with maximum prototype efficiency. Cavitation is safe when `safety_margin` (sigma_plant minus sigma_critical) is at least 0.05. Use g = 9.80665 m/s².

Verification tolerances: energies/efficiencies/dimensionless coefficients within 0.1% relative; Reynolds numbers within 0.5% relative; cavitation sigma within 0.001 absolute; uncertainty percentage within 0.01 absolute; prototype BEP quantities within 0.5% relative. JSON and SQLite outputs must be mutually consistent.
