A TEMA E shell-and-tube heat exchanger P-NTU analysis tool is partially implemented at `/app/`. The implementation has bugs producing incorrect results for several tube-pass configurations, missing support for others, and incomplete solver modes. Known-correct validation data is at `/app/reference_cases.json`.

Debug and complete the implementation so that all tests pass.

**Required files and public API:**

`/app/hx_solver.py` must export:

- `temperature_effectiveness_TEMA_E(R1, NTU1, Ntp=1, optimal=True) -> float` — shell-side temperature effectiveness P1. Must produce correct results for Ntp = 1, 2 (both optimal and non-optimal flow arrangements), 3 (both optimal and non-optimal), and any even Ntp >= 4. Raise `ValueError` for unsupported odd Ntp > 3. Must be numerically stable across all degenerate parameter values (coincident ratios, extreme NTU).

- `NTU_from_P_E(P1, R1, Ntp, optimal=True) -> float` — inverse: recover NTU1 from known P1 and R1 for all supported Ntp values. Raise `ValueError` if P1 is outside the achievable range.

- `P_NTU_method(m1, m2, Cp1, Cp2, UA=None, T1i=None, T1o=None, T2i=None, T2o=None, Ntp=1, optimal=True) -> dict` — full rating/design solver returning `{Q, UA, T1i, T1o, T2i, T2o, P1, P2, R1, R2, C1, C2, NTU1, NTU2}`. Side 1 = shell, side 2 = tube. Must support forward mode (UA given with any two of the four temperatures known) and inverse mode (UA unknown, three temperatures given).

`/app/f_lmtd.py` must export:

- `F_LMTD_Fakheri(Thi, Tho, Tci, Tco, shells=1) -> float` — LMTD correction factor. Must handle all valid temperature combinations without NaN or division by zero, including when hot-side and cold-side temperature drops are equal.

**Constraints:**
- Python standard library and `scipy` only. No external heat-transfer libraries.
- All outputs must match reference data and test golden values to relative tolerance 1e-7 or better.

**Success criterion:** `python3 -m pytest /tests/test_state.py -v` — all tests pass.
