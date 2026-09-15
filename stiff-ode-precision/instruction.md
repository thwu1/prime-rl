The directory `/app/fortran/` contains Fortran 77 source code for the E5 extremely stiff chemical kinetics benchmark problem from the Geneva Test Set (Hairer & Wanner). The system models four chemical species whose reaction rate constants span 19 orders of magnitude. Source files include the equation/Jacobian subroutines (`equation.f`), a driver template (`driver_radau5.f`), the implicit Runge-Kutta solver (`radau5.f`), and linear algebra routines (`dc_decsol.f`, `decsol.f`).

Produce the following output files:

**`/app/fortran_reference.csv`** — High-precision numerical solution obtained by running the provided Fortran solver code. CSV with columns `t,y1,y2,y3,y4` at seven output times: t = 10, 10^3, 10^5, 10^7, 10^9, 10^11, 10^13. Values must match published reference solutions to at least 4 significant correct digits.

**`/app/e5_solver.py`** — Python module implementing the E5 ODE system. Must export:
- A right-hand-side function (named one of: `e5_rhs`, `rhs`, `f_e5`, `f`, `dydt`) with signature `(t, y) -> array`
- A Jacobian function (named one of: `e5_jac`, `jac`, `jacobian`, `jac_e5`, `e5_jacobian`) with signature `(t, y) -> 4x4 array`, encoding the E5 rate constants and computing exact partial derivatives
- A function `solve_e5(method, rtol)` returning `{t: [y1, y2, y3, y4]}` for all seven output times

**`/app/python_results.csv`** — CSV with columns `method,rtol,t,y1,y2,y3,y4`. Contains results from calling `solve_e5` with methods `Radau` and `BDF`, each at rtol = 1e-4, 1e-6, 1e-8, 1e-10 (8 method/tolerance combinations, 7 time points each).

**`/app/eigenvalues.json`** — Spectral analysis of the E5 Jacobian matrix. JSON with keys `eigenvalues_t0`, `eigenvalues_t10`, `stiffness_ratio_t0`, `stiffness_ratio_t10`. Eigenvalues are of the 4x4 Jacobian evaluated at y(0) = (1.76e-3, 0, 0, 0) and at the computed solution y(t=10). Each eigenvalue list has 4 entries. Stiffness ratio = max|lambda|/min|lambda| over eigenvalues with |lambda| > 1e-30.