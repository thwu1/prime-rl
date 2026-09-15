Build `/app/bjoint` via `/app/Makefile`. Running `make` in `/app/` produces the executable. `make` must be idempotent; deleting `bjoint` and re-running `make` must recreate it.

**Modes:**
- `/app/bjoint <spec.toml>` — pretty-printed JSON to stdout.
- `/app/bjoint --batch <dir>` — processes every `.toml` in `<dir>` alphabetically; one JSON object per stdout line (JSONL), each adding `"source_file"` (input basename). Every batch entry is individually logged to the database and gets its own diagram.

**Data** at `/app/data/`: `thread_data.csv`, `bolt_grades.csv`, `nut_proof_loads.csv`, `example_spec.toml`. **Docs** at `/app/docs/` describe VDI 2230 methodology for all calculations.

**Input TOML** — all sections mandatory: `[bolt]` (size, property_class, grip_length_mm), `[nut]` (standard: "ISO"|"DIN", property_class), `[joint]` (num_interfaces, interface_friction, surface_roughness_class: "fine"|"normal"|"rough", material_elastic_modulus_GPa, cte_ppm_per_K), `[washer]` (present, hardness_HV), `[loading]` (axial_kN, shear_kN), `[tightening]` (torque_Nm, thread_friction_min/max, bearing_friction_min/max), `[environment]` (temperature_C, bolt_material: "ISO898"|"A193_B7"|"A193_B16"|"A286"|"Inconel718"), `[friction_shim]` (present, friction_coefficient).

**JSON output** — floats in kN to 2 decimals, booleans as true/false:
- `stress_area_mm2` — from thread_data.csv lookup.
- `max_preload_kN` / `min_preload_kN` — computed at min/max friction respectively. Wider friction range produces wider preload range.
- `bolt_stiffness_kN_per_mm` — decreases with longer grip.
- `joint_stiffness_kN_per_mm` — must exceed bolt stiffness.
- `load_factor_phi` — in range 0.05-0.25; decreases with longer grip.
- `embedding_loss_kN` — increases with more interfaces and rougher surfaces per docs.
- `differential_thermal_load_kN` — relative to 20 C assembly reference. Positive when joint CTE > bolt CTE (gain), negative when reversed (loss). Zero when CTEs match or at 20 C. Negative values increase `total_preload_requirement_kN`; positive values do not reduce it.
- `shear_grip_requirement_kN` — uses `friction_shim.friction_coefficient` when shim present, else `interface_friction`.
- `axial_clamp_reduction_kN`
- `total_preload_requirement_kN`
- `design_margin`
- `nut_compatible` — true when nut proof load (from standard-specific table in data/) >= stress_area * bolt UTS.
- `washer_suitable` — grades >= 8.8 require washer present; minimum HV by grade: 8.8 needs 200, 10.9 needs 300, 12.9 needs 380. Below 8.8: always suitable.
- `temperature_suitable` — true when operating temp <= bolt material service limit per docs.
- `thread_root_radius_range_mm` — 2-element list computed from thread pitch per ISO specification in docs.
- `probability_of_failure` — value in [0, 1]. Inversely correlated with design_margin; high margin yields near-zero probability.
- `diagram_path` — absolute path to generated SVG.

**Diagram**: `/app/diagrams/<bolt_size>_<db_row_id>.svg` generated via gnuplot; must be valid SVG with preload demand components and min/max preload markers.

**SQLite** at `/app/analysis.db`, table `analyses`: `id` (INTEGER PRIMARY KEY AUTOINCREMENT), `timestamp` (TEXT, ISO 8601), `bolt_size` (TEXT), `property_class` (TEXT), `grip_length_mm` (REAL), `design_margin` (REAL), `probability_of_failure` (REAL), `nut_compatible` (INTEGER, 0/1), `washer_suitable` (INTEGER, 0/1), `temperature_suitable` (INTEGER, 0/1), `risk_category` (TEXT), `full_result` (TEXT — valid JSON matching stdout output). Each analysis inserts exactly one row; rows accumulate across runs. Logged values must match JSON output.

TRIGGER `classify_risk` on INSERT auto-sets `risk_category`: "critical" (design_margin < 0.8), "marginal" (< 1.0), "acceptable" (< 2.0), "over_designed" (>= 2.0). VIEW `risk_summary` grouped by `bolt_size`: `bolt_size`, `analysis_count`, `avg_design_margin`, `min_design_margin`, `max_pof`.
