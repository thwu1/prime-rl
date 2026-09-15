A shell-and-tube heat exchanger thermal rating tool at `/app/` produces incorrect results for all provided test cases. The tool is a multi-component system:

- `/app/hx_rate.py` — main CLI entry point (Python). Reads a JSON specification from `argv[1]`, writes a JSON rating result to stdout. Contains computational defects.
- `/app/bell_delaware.py` — shell-side module (Python). Loads the C shared library `/app/libcorr.so` via `ctypes` for geometry and correction-factor computations, and reads empirical coefficients from `/app/coefficients.csv`.
- `/app/libcorr.c` + `/app/Makefile` — C source for performance-critical correlations compiled into `libcorr.so`. Must be compiled (`make -C /app`) before the tool can execute. Contains defects.
- `/app/coefficients.csv` — Taborek Table 10 empirical coefficient data for the ideal bank j-factor correlation. Contains a corrupted entry.
- `/app/case1.json` through `/app/case4.json` — test case specifications covering turbulent/laminar tube-side regimes, four tube layout angles (30/45/60/90 degrees), equal/unequal baffle spacing, and an R=1 edge case.

Defects span C source code, empirical coefficient data, and Python formulas. Some affect all cases; others are layout- or regime-specific. Fixing one bug may unmask the numerical signature of another.

Identify and fix all defects so that `python3 -m pytest /tests/test_state.py -v` exits 0. Do not modify the JSON case files, output key structure, or test files.

**Output JSON keys** (must be preserved):
`lmtd`: `LMTD_K`, `R`, `P`, `F`, `LMTD_eff_K`; `tube_side`: `Re`, `Pr`, `Nu`, `h_i_W_m2K`, `flow_regime`; `shell_side`: `Re`, `j_i`, `J_c`, `J_l`, `J_b`, `J_s`, `J_r`, `h_ideal_W_m2K`, `h_o_W_m2K`; `overall`: `U_clean_W_m2K`, `U_dirty_W_m2K`, `cleanliness_factor`, `controlling_resistance`; `area`: `required_m2`, `available_m2`, `overdesign_pct`; `heat_duty_W`

**Success criterion:** `python3 -m pytest /tests/test_state.py -v` exits 0.
