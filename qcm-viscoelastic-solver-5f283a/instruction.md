Build a QCM-D multi-harmonic viscoelastic film analysis system consisting of a physics engine at `/app/qcm_engine.py` and a data processing pipeline at `/app/analyze.py`.

**Engine** (`/app/qcm_engine.py`)

`forward_calc(layers, harmonics, f1=5e6, Zq=8.84e6)` — Compute complex frequency shifts for a viscoelastic layer stack on AT-cut quartz using the acoustic impedance transfer matrix method with power-law rheology.

- `layers`: dict `{layer_num: {'grho3': float, 'phi': float, 'drho': float}}` — layer 1 closest to crystal; `grho3` = |G\*|ρ at 3rd harmonic (Pa·kg/m³), `phi` = loss angle (degrees), `drho` = areal mass (kg/m²) or `float('inf')` for semi-infinite bulk; `grho3=0` means vacuum/zero-load
- `harmonics`: list of odd integers
- Returns: `{n: {'delf': float, 'delg': float}}` — frequency shift and half-bandwidth shift (Hz)

`inverse_calc(measurements, harmonics_f, harmonics_g, unknowns, layers_init, f1=5e6, Zq=8.84e6, bounds=None)` — Solve for unknown layer properties via bounded nonlinear least-squares.

- `measurements`: `{n: {'delf': float, 'delg': float}}`
- `unknowns`: list of `'property_layer'` strings (e.g. `'grho3_1'`)
- `layers_init`: initial/fixed layer properties (same format as `forward_calc`)
- `bounds`: optional `{name: (lo, hi)}`
- Returns: `{name: float}`

The engine must correctly reproduce the Sauerbrey equation for rigid thin films, the Gordon-Kanazawa result for bulk Newtonian liquids (equal frequency and bandwidth shifts scaling as the square root of harmonic number), and multi-layer viscoelastic coupling including near-resonance behavior at higher harmonics.

**Pipeline** (`/app/analyze.py`)

Reads crystal parameters from `/app/config/crystal.toml` and processes each experiment subdirectory under `/app/data/`. Each subdirectory contains measurement data and metadata files whose formats, units, and conventions must be determined by inspecting the files. The pipeline must perform any necessary unit conversions.

Running `python3 /app/analyze.py` must produce `/app/results.json` — a dict keyed by experiment directory name. Each entry must include:

- Calibration experiments: `fitted_grho3`, `known_grho3`, `relative_error`
- Rigid-film experiments: `sauerbrey_drho` (mean areal mass in kg/m²)
- Viscoelastic-film-in-liquid experiments: `grho3`, `phi`, `drho` of the film layer

All computations must use the crystal parameters from the configuration file.
