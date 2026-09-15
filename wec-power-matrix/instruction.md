The RM3 two-body wave energy converter dataset is at `/app/data/`:
- `rm3_hydro_coeffs.csv` — nondimensional WAMIT BEM coefficients (260 frequencies, 13 columns)
- `rm3_params.json` — body parameters, fluid properties, PTO config, nondimensionalization conventions, wave spectrum model
- `sea_states.csv` — 24 sea states (Hs, Tp, annual hours)

## Required outputs

**`/app/wec_analysis.py`** — Script with two invocation modes:
- `python3 /app/wec_analysis.py full` — runs complete analysis, writes all output files below
- `python3 /app/wec_analysis.py query <Hs> <Tp> <Bpto>` — prints `{"power_kW": <float>}` (single JSON line) to stdout: mean absorbed power in kW for given Hs (m), Tp (s), PTO damping Bpto (N·s/m). Must compute from coefficients, not read cached results.

**`/app/rm3_analysis.h5`** — HDF5 file with these datasets:
- `/hydro/omega` — (260,), frequency vector matching `rm3_hydro_coeffs.csv` [rad/s]
- `/hydro/added_mass/{A33,A39,A93,A99}` — (260,) each, dimensional [kg]
- `/hydro/radiation_damping/{B33,B39,B93,B99}` — (260,) each, dimensional [kg/s]
- `/hydro/excitation/{F3_real,F3_imag,F9_real,F9_imag}` — (260,) each, dimensional [N/m]
- `/hydro/radiation_irf/time` — (1001,), 0 to 100 s inclusive, step 0.1 s
- `/hydro/radiation_irf/{K33,K39,K93,K99}` — (1001,) each, radiation impulse response functions
- `/results/power_kW` — (6,4), rows=ascending Hs, cols=ascending Tp
- `/results/Hs_values` — (6,)
- `/results/Tp_values` — (4,)
- `/results/optimal_Bpto_MNsm` — (6,4), same row/col ordering as power_kW

**`/app/power_matrix.json`** — `{"Hs_values": [1.0,1.5,2.0,2.5,3.0,3.5], "Tp_values": [6.0,8.0,10.0,12.0], "power_kW": {"<Hs>_<Tp>": <kW>, ...}}`. 24 entries.

**`/app/optimal_pto.json`** — `{"optimal_Bpto_MNsm": {"<Hs>_<Tp>": <MN·s/m>, ...}}`. PTO search range: 50 kN·s/m to 30 MN·s/m. 24 entries.

**`/app/aep.json`** — `{"aep_mwh": <float>}` — annual energy production (MWh/yr) from weighting each sea state's optimal power by its annual hours.

## Acceptance criteria
- Power matrix and AEP within 5% relative error of reference values
- Power scales as Hs² for fixed Tp (ratio within 5% of expected)
- Optimal PTO damping independent of Hs for fixed Tp (10% tolerance around per-Tp mean)
- Optimal PTO damping strictly increases with Tp
- Power strictly increases with both Hs and Tp
- All power and PTO damping values positive
- HDF5 dimensional coefficients correctly derived per `rm3_params.json` nondimensionalization conventions
- HDF5 result datasets match corresponding JSON output values
- HDF5 power_kW shape (6,4) with ascending Hs rows, ascending Tp columns
- Radiation IRFs decay: |K(100 s)| < 1% of max |K| for each DOF pair
- Query mode at optimal Bpto returns power matching the power matrix (2% tolerance)
- Query mode at Bpto = 50 kN·s/m yields strictly less power than optimal
