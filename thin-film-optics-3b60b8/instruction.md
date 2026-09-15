`/app/tmm_engine.py` and `/app/matrix_kernel.c` implement a thin-film optics transfer-matrix method but contain defects. Golden values are in `/app/reference/benchmark.json`. Stack configurations are in `/app/stacks.yaml`.

**`/app/libmatkernel.so`** — compiled from `/app/matrix_kernel.c` via `gcc -shared -fPIC`. Exports `mat2x2_chain_multiply`, `mat2x2_mul`, `mat2x2_inv`. Matrix layout: 8 doubles per matrix, row-major, real/imag interleaved. `mat2x2_chain_multiply(matrices, n, out)` computes M[0]*M[1]*...*M[n-1] left-to-right; identity when n=0.

**`/app/tmm_engine.py`** — must match benchmark within 1e-6. Must contain a module-level `ctypes.CDLL` handle for `libmatkernel.so`; `coh_tmm` must use `mat2x2_chain_multiply` for the chain product.

Required functions (return-dict keys noted):

- `coh_tmm(pol, n_list, d_list, th_0, lam_vac)` — keys: `r, t, R, T, power_entering, vw_list, kz_list, th_list, pol, n_list, d_list, th_0, lam_vac`

- `position_resolved(layer, distance, coh_tmm_data)` — keys: `poyn, absor, Ex, Ey, Ez`. `poyn` at end of last finite layer = `T`; at first interior layer start = `power_entering`; continuous across boundaries; negative spatial derivative = `absor`.

- `absorp_in_each_layer(coh_tmm_data)` — array summing to 1.0, including for complex incident media.

- `ellips(n_list, d_list, th_0, lam_vac)` — keys: `psi`, `Delta` (radians).

- `inc_tmm(pol, n_list, d_list, c_list, th_0, lam_vac)` — `c_list`: `'c'`/`'i'` per layer; first and last `'i'`. Returns at least `R, T, VW_list, power_entering_list` (one entry per incoherent layer). All-coherent interior: R/T must match `coh_tmm`. 0 ≤ R,T ≤ 1; R+T ≤ 1. Normal incidence: s = p.

**`/app/Makefile`** — targets `lib` (builds `libmatkernel.so`) and `all` (lib + analysis producing both output files).

**`/app/results.json`** — from `/app/stacks.yaml`:
- `basic`: `{R_s, T_s, R_p, T_p, psi, Delta}` — `coh_tmm` + `ellips`
- `spr`: `{spr_angle_deg, R_min}` — p-pol reflectance sweep per `sweep_th0_deg`; minimum
- `ar_coating`: `{optimal_thickness_nm, R_min, avg_R_400_700}` — s-pol thickness sweep per `optimize_d`; `avg_R_400_700` = mean unpolarized R, 400–700 nm, 1 nm steps at optimal thickness
- `solar_cell`: `{R_s, T_s, R_p, T_p, absorption_per_layer_s: [...], absorption_per_layer_p: [...]}` — `inc_tmm` with `c_list`; one entry per layer; sum = 1; first = R; last = T; real-n layers ≈ 0; all ≥ 0

**`/app/results.db`** (SQLite):
- `stack_results(stack_name TEXT, key TEXT, value REAL)` PK `(stack_name, key)`
- `absorption(stack_name TEXT, polarization TEXT, layer_index INTEGER, absorption REAL)` PK `(stack_name, polarization, layer_index)`

DB values must match JSON. Lengths in nm, angles in radians except `spr_angle_deg`.
