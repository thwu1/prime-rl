A reference document at `/app/problem_spec.md` describes an analytical solution to a point-explosion problem in compressible gas dynamics, including governing equations, special parameter regimes, and published numerical verification tables. Implement a Python module at `/app/sedov.py` that computes these solutions.

The module must expose four functions:

- `sedov_funcs(v, gamma, geometry, omega)` — returns a tuple of four floats `(lam, f, g, h)`.

- `find_v_for_lambda(lam_want, gamma, geometry, omega)` — returns a float `v`.

- `sedov_alpha(gamma, geometry, omega)` — returns a tuple of three floats `(eval1, eval2, alpha)`.

- `sedov_solution(r, t, gamma=1.4, geometry=3, rho0=1.0, omega=0.0, eblast=0.851072)` — returns a dict with keys `'density'`, `'velocity'`, `'pressure'`, `'specific_internal_energy'`, `'sound_speed'` (numpy arrays matching the length of `r`), and `'shock_position'` (float).

All outputs must match the reference data tables in `/app/problem_spec.md`. The solver must handle every valid parameter combination and special case described in that document without crashing or producing incorrect results.