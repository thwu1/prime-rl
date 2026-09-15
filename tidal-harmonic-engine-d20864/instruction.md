A tidal prediction engine at `/app/tidal_engine.py` produces incorrect results. The engine delegates astronomical mean longitude computations to a C shared library at `/app/libastro/` (source: `astro.c`, build: `Makefile`), loaded via `ctypes`. It reads tidal constituent coefficients from `/app/doodson_coefficients.json` and implements harmonic analysis and tidal prediction in Python. Reference implementations are at `/app/reference/` (read-only, not directly importable). Defects span the C library source, its build configuration, the Python engine, and the coefficient data.

**Module** (`/app/tidal_engine.py`) must export:

- `mean_longitudes(mjd)` → `(s, h, p, n, pp)` — five mean astronomical longitudes in degrees, each in [0, 360). Accepts scalar or numpy array.
- `doodson_number(constituent)` → float — classic Doodson number from the first six coefficients in the JSON data.
- `angular_frequency(constituents)` → numpy array of angular frequencies in radians per second.
- `nodal_corrections(mjd, constituents)` → `(u, f)` shaped `(nt, nc)` — radians and amplitude factors.
- `harmonic_analysis(t_days, heights, constituents)` → complex harmonic constants. Time in days since 1992-01-01.
- `predict_tide(t_days, hc, constituents)` → numpy array of predicted heights.
- `_constituent_parameters(name)` → `(amplitude, phase, omega, alpha, species)`.

**Data:** `/app/doodson_coefficients.json` maps constituent names to 7-element `[tau, s, h, p, n, pp, k]` arrays.

**Acceptance criteria:**

1. The C shared library at `/app/libastro/libastro.so` must build cleanly from its Makefile and produce correct range-normalized longitudes when called directly via `ctypes`. Outputs must be in [0, 360) across all tested epochs.
2. Doodson numbers for 21 constituents match published values within ±0.0005.
3. Mean longitudes at MJD 55414.0: s≈84.38°, h≈134.43°, p≈154.43°, n≈280.14°, pp≈282.8° (±0.5°/±1.0°). All in [0, 360) at any epoch.
4. Angular frequencies for 10 constituents within 0.1% of tabulated values. All positive. Semi-diurnal ≈ 2× diurnal.
5. Nodal corrections: S2/P1 f≈1.0, M2 f∈(0.9,1.1), K1 f∈(0.85,1.15), O1 varies >0.01 over 9 years. Shapes `(nt, nc)`.
6. Constituent parameters for 10 constituents: amplitude ±1e-4, omega 0.1% relative, species exact.
7. Harmonic analysis round-trip: 60 days hourly, 6 constituents, recovered amplitudes within 5%.
8. Prediction round-trip: 90-day RMS < 2mm; 60-day train / 30-day validation RMS < 5mm.
