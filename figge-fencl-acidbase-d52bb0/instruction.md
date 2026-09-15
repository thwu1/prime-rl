The Figge-Fencl v3.0 quantitative physicochemical acid-base model must be operational at `/app/`. Model parameters are at `/app/spec/model_params.json`. Validation data (65 experimental samples) are at `/app/data/golden_data.csv`.

**Required files:**

- `/app/src/*.c` — C source files.
- `/app/libfigge.so` — ELF shared object (DYN type) exporting symbols: `figge_albumin_net_charge`, `figge_solve_ph`, `figge_phosphate_charge`.
- `/app/Makefile` — `make build` produces `libfigge.so`; `make clean` removes it; `make clean && make build` succeeds.
- `/app/figge_fencl.py` — Python module that loads `libfigge.so` via `ctypes.CDLL`. Charge computation must delegate to C, not be reimplemented in Python (pKa-based exponentiation outside `hco3` is prohibited in this file). Exposes:
  - `predict_pH(SID, PCO2, Pi, Albumin)` -> float pH
  - `albumin_charge(albumin_g_dL, pH)` -> float mEq/L
  - `albumin_net_charge_per_mol(pH)` -> float Eq/mol
  - `phosphate_charge(phos_mmol_L, pH)` -> float mEq/L
  - `hco3(pH, pCO2)` -> float mmol/L
- `/app/cli.py` — subcommands printing JSON to stdout:
  - `predict-ph --sid F --pco2 F --pi F --alb F` -> `{"pH": float}`
  - `validate --data PATH` -> `{"n_samples": int, "rmse": float, "mad": float, "max_abs_error": float, "r_squared": float, "results": [...]}`
  - `analyze --na F --k F --ica F --img F --cl F --lac F --alb F --phos F --ph F --pco2 F` -> `{"SIDa": float, "SIDe": float, "SIG": float, "AG": float, "HCO3": float, "Alb_charge_mEq_L": float, "Pi_charge_mEq_L": float}`
  - `albumin-charge --alb F --ph F` -> `{"charge_mEq_L": float, "charge_Eq_per_mol": float}`
  - `phosphate-charge --phos F --ph F` -> `{"charge_mEq_L": float}`

**Acceptance criteria:**

Golden data: every sample |predicted - measured| < 0.10; RMSE < 0.04; R^2 > 0.98.

Albumin charge: at pH 7.40 with 4.4 g/dL -> 12.3 +/- 0.2 mEq/L; with 4.0 g/dL -> 11.2 +/- 0.2 mEq/L. Scales linearly with concentration. Increases monotonically with pH. Zero albumin -> zero charge. Net charge/mol at pH 7.40: -18.5 +/- 0.5 Eq/mol. Net charge is positive at very low pH (e.g. 2.0) and changes sign between pH 4.0 and 6.0 (isoelectric region). Titration slope over pH 6.9-7.9: 0.123 +/- 0.01 mEq/g/pH.

Phosphate: at pH 7.40, 1.0 mmol/L -> 1.85 +/- 0.05 mEq/L. Scales linearly with concentration. Increases with pH. Zero input -> zero. Approaches zero at very low pH (< 0.1 at pH 0.5).

HCO3: at pH 7.40, pCO2 40 -> 23-25 mmol/L. Scales linearly with pCO2.

pH solver: normal physiology (SID ~42, PCO2 40, Pi 1.0, Alb 4.0) -> pH 7.30-7.50. SID 22, PCO2 40 -> pH < 7.15. SID 42, PCO2 20 -> pH > 7.55. Higher albumin at same SID/PCO2 -> lower pH. Zero albumin + zero phosphate -> pH > 7.4.

Clinical analysis consistency: SIDa = Na + K + 2*iCa + 2*iMg - Cl - Lac; SIDe = HCO3 + Alb_charge + Pi_charge; SIG = SIDa - SIDe; AG = Na + K - Cl - HCO3.
