A coastal storm-impact diagnostic package at `/app/coastal_diag/` must be corrected and integrated with a Fortran sediment transport kernel at `/app/fortran/sedtrans.f90`.

**Fortran module**

The file `/app/fortran/sedtrans.f90` implements Van Rijn (2007) fall velocity and a Dean equilibrium profile subroutine. It must be compiled into a Python-importable shared module named `sedtrans` accessible via `import sedtrans` when the working directory is `/app/`. The source may require modifications for compilation toolchain compatibility. The compiled module must expose callable `fall_velocity` and `equilibrium_profile` functions.

**Python package**

`/app/coastal_diag/` contains five modules: `profiles`, `spectra`, `metrics`, `verification`, and `cli`. Several contain numerical, logical, or integration defects. Reference XBeach implementations are at `/app/reference/`.

- `profiles.py` delegates computations to the compiled Fortran module. It must correctly interface with the Fortran calling conventions.
- `spectra.py` implements JONSWAP spectral density and cosine-power directional spreading. The spreading function must integrate to 1.0 over [-pi, pi].
- `metrics.py` provides BSS, RMSE, and volume change (m^3 for 2-D fields, m^3/m for 1-D profiles with dy=1).
- `verification.py` runs slope checks, bed-level change detection, mass balance, and an overall diagnostic verdict.
- `cli.py` reads configuration and CSV data, runs the full pipeline, and writes a JSON report.

**CLI contract**

```
python3 /app/coastal_diag/cli.py --config /app/data/config.json --output /app/report.json
```

Required JSON report structure:

```json
{
  "fall_velocity": <float>,
  "dean_parameter_A": <float>,
  "spectrum": {"peak_frequency": <float>, "Hm0_check": <float>},
  "brier_skill_score": <float>,
  "rmse": <float>,
  "volume_change": <float>,
  "diagnostics": {"mass_balance": {...}, "bed_level_change": {...}, "overall": "PASS"|"FAIL", ...}
}
```

**Acceptance ranges** (D50=200um, Hm0=3.0m, Tp=8.0s, T=15C):

| Metric | Range |
|---|---|
| fall_velocity | [0.020, 0.025] m/s |
| dean_parameter_A | [0.090, 0.105] |
| spectrum.Hm0_check | [2.85, 3.15] m |
| BSS | [0.93, 1.0] |
| RMSE | [0.02, 0.08] m |
| volume_change | [-25, -10] m^3/m |
| diagnostics.overall | "PASS" |

All tests at `/tests/test_state.py` must pass.
