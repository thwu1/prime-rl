Three stiff ODE problems from the Geneva Test Set (Hairer & Wanner) are provided as Fortran 77 source in `/app/fortran/`. Each subdirectory (`rober/`, `hires/`, `e5/`) contains `equation.f` (RHS and analytical Jacobian) and `driver_radau5.f` (initial conditions, tolerances, integration parameters). Reference solutions are in `/app/reference/`.

Translate all three ODE systems **and their analytical Jacobians** from Fortran 77 to Python. Solve each using an implicit stiff solver, producing numerical solutions at the specified time points. The E5 problem has rate constants spanning 19 orders of magnitude and requires extreme absolute tolerance scaling.

**Output time points:**

- **ROBER** (3 eqs): t = 0.4, 4.0, 40.0, 400.0, 4000.0, 40000.0, 400000.0
- **HIRES** (8 eqs): t = 200.0, 321.8122, 421.8122
- **E5** (4 eqs): t = 1.0, 10.0, 100.0, 1000.0, 10000.0

Write `/app/results.json` containing keys `"rober"`, `"hires"`, `"e5"`. Each has a `"solutions"` dict mapping time-point strings to solution arrays. ROBER must include `"conservation_max_error"` (max |y1+y2+y3 - 1|). HIRES must include `"invariant_max_error"` (max |y7+y8 - 0.0057|).

**Accuracy:** ROBER and HIRES must match reference values to 6 significant digits. E5 must match to 4 significant digits. ROBER conservation error < 1e-8. HIRES invariant error < 1e-6.