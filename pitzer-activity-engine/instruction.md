Build an electrolyte solution analysis pipeline at `/app/` that predicts thermodynamic properties of aqueous solutions at 25 C. The parameter database contains all information needed to identify and implement the appropriate ion-interaction model.

**Provided files:**

- `/app/ion_parameters.sql` — SQL schema defining tables `constants` and `salt_parameters` with model constants and interaction parameters for eight binary electrolytes.
- `/app/solutions.json` — Five solution compositions as `{ion_formula: molality}` with formulas like `Na+`, `Ba+2`, `SO4-2`. Each entry has an `id` (e.g., `nacl_05`, `mixed_nacl_kcl`) and a `composition` dict.
- `/app/reference_data.csv` — CRC Handbook mean activity coefficients (25 C) for seven electrolytes.

**Required: `/app/electrolyte_engine.py`**

Python module (numpy + standard library only) exposing these functions. All accept composition dicts `{ion_formula: molality}`:

- `compute_ionic_strength(composition) -> float` — Raises `ValueError` when charge imbalance exceeds 1% of total ion equivalents, including pure-cation-only or pure-anion-only inputs. Empty composition returns 0.0.
- `compute_activity_coefficient(composition, ion) -> float` — Mean molal activity coefficient. Both ions in a binary salt must return the same value. Approaches 1.0 at ~0.001 mol/kg (0.95-1.05 for 1:1; 0.85-1.05 for 2:1).
- `compute_osmotic_coefficient(composition) -> float` — Always positive.
- `compute_water_activity(composition) -> float` — In (0, 1]. Decreases monotonically with increasing concentration.
- `compute_osmotic_pressure(composition, temperature_K=298.15) -> float` — Returns bar. Positive, increases with both concentration and temperature.

Running `python3 /app/electrolyte_engine.py` must process `/app/solutions.json` and write `/app/results.json` and `/app/results.db`.

**Required: `/app/Makefile`**

- `init-db`: creates `/app/parameters.db` from `/app/ion_parameters.sql` via the `sqlite3` CLI. The resulting database must contain `constants` and `salt_parameters` tables.
- `run`: depends on `init-db`; executes the engine.
- `validate`: computes activity coefficients for all `/app/reference_data.csv` entries and prints per-electrolyte RMSE to stdout.
- `all`: runs all targets sequentially.

**Output: `/app/results.db`**

Table `results` with columns: `solution_id TEXT PRIMARY KEY, ionic_strength REAL, activity_coefficient REAL, osmotic_coefficient REAL, water_activity REAL, osmotic_pressure_bar REAL`. One row per solution using its `id` as `solution_id`. All values physically valid: ionic_strength >= 0, coefficients > 0, 0 < water_activity <= 1, pressure > 0.

**Output: `/app/results.json`**

Schema: `{"solutions": [{"id": "...", "ionic_strength": ..., "activity_coefficient": ..., "osmotic_coefficient": ..., "water_activity": ..., "osmotic_pressure_bar": ...}, ...]}`. Must contain all five solutions and be consistent with `results.db` within 1% relative tolerance on every field.

**Acceptance criteria:**

- Activity coefficients match CRC data within 5% for NaCl, KBr, LiCl, HCl, RbCl (1:1), BaCl2 (2:1), and K2SO4 (1:2) across the full concentration range in reference_data.csv.
- NaCl osmotic coefficient: ~0.921 at 0.5 mol/kg, ~0.984 at 2.0 mol/kg (5% tolerance).
- NaCl water activity: ~0.984 at 0.5 mol/kg (1% tolerance), ~0.932 at 2.0 mol/kg (2% tolerance).
- NaCl osmotic pressure: ~22.8 bar at 0.5 mol/kg, ~97.6 bar at 2.0 mol/kg (10% tolerance).
- Mixed NaCl+KCl solution: activity coefficients in 0.55-0.75, osmotic coefficient 0.85-1.0, water activity 0.95-1.0.
- `make all` completes without error.
