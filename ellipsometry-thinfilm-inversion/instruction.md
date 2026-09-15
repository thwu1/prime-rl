The environment at `/app/` contains a buggy multilayer thin-film optics simulator (`tmm_solver.py`) and experimental data files.

**Fix `/app/tmm_solver.py`** to correctly export:

- `coh_tmm(pol, n_list, d_list, th_0, lam_vac)` → dict with keys `r`, `t`, `R`, `T`, `power_entering`, `vw_list`, `kz_list`, `th_list`, `pol`, `n_list`, `d_list`, `th_0`, `lam_vac`
- `ellips(n_list, d_list, th_0, lam_vac)` → dict with `psi`, `Delta`
- `position_resolved(layer, distance, coh_tmm_data)` → dict with `poyn`, `absor`
- `absorp_in_each_layer(coh_tmm_data)` → list of floats

`pol` is `'s'`/`'p'`; `n_list` = complex refractive indices; `d_list` = thicknesses (`inf` for semi-infinite endpoints); `th_0` = incidence angle (radians); `lam_vac` = vacuum wavelength.

Physical correctness requirements (all verified by tests):

- Output values including `r`, `R`, `T`, and `kz_list` entries for both polarizations match golden values (relative error < 1e-10)
- `psi`, `Delta` from `ellips` match golden values (relative error < 1e-10)
- `position_resolved` returns correct `poyn` and `absor` for both s and p polarizations (golden values verified to 1e-10)
- Absorption across all layers sums to 1.0 (within 1e-10) for any stack including absorptive endpoint media and five-layer stacks
- Poynting vector continuous at interfaces (gap < 1e-12); equals `power_entering` at first-layer start and `T` at last-layer exit
- Finite-difference `d(poyn)/dz` matches `-absor` within 1e-4
- Opaque layers (1e5 nm of n=1+3j): no NaN, T near zero, R matches truncated stack to 1e-6
- Normal incidence: s and p yield identical R and T
- Single interface with real incident medium: R + T = 1

**Create `/app/run_fit.py`** using `/app/stack_config.json`, `/app/measurements.csv` (`wavelength_nm`, `angle_deg`, `psi_rad`, `Delta_rad`), and `/app/si_nk.csv` (`wavelength_nm`, `n`, `k`). Write `/app/results.json`:

```json
{"thickness_nm": <float>, "cauchy_A": <float>, "cauchy_B": <float>}
```

Tolerances: thickness within 3 nm of 250, `cauchy_A` within 0.01 of 1.46, `cauchy_B` within 300 of 5000. Forward-model max residual < 0.01 rad against all measurement points.

**Create `/app/tmm_cli.sh`** (executable shell script) with two subcommands:

`./tmm_cli.sh compute`: reads JSON from stdin with fields `pol`, `n_list` (each element a float or `[real, imag]`), `d_list` (floats or `"inf"`), `th_0`, `lam_vac`. Writes JSON to stdout: `{"R": <float>, "T": <float>, "r_real": <float>, "r_imag": <float>}`. Output must match `coh_tmm` results to 1e-8 relative error.

`./tmm_cli.sh sweep`: reads JSON from stdin with fields `n_list`, `d_list`, `th_0`, `lam_min`, `lam_max`, `lam_count`. Computes R and T for both polarizations at `lam_count` equally-spaced wavelengths from `lam_min` to `lam_max` inclusive. Stores results in SQLite database `/app/sweep_results.db`, table `sweep` with columns `wavelength_nm REAL, R_s REAL, T_s REAL, R_p REAL, T_p REAL`. Creates table if absent; replaces existing rows on re-run. Energy conservation must hold (R+T <= 1 for real incident media). Values must match direct computation to 1e-8.
