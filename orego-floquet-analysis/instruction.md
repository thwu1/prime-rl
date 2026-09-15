A stiff ODE system from a numerical benchmark collection is set up in `/app/`. The directory contains Fortran 77 source code implementing the system's right-hand side and analytical Jacobian, along with configuration and notes files. You will need to explore these files to extract the system equations and parameters.

Investigate the system's long-term dynamical behavior. Determine whether the system possesses a periodic orbit, and if so, perform a complete stability analysis.

Write results to:

- `/app/period.txt` — the period T of the orbit (single floating-point number)
- `/app/monodromy_matrix.json` — the 3×3 monodromy matrix as a nested list `[[m11,m12,m13],[m21,...],...]`
- `/app/floquet_multipliers.json` — the 3 Floquet multipliers as `[{"real":...,"imag":...}, ...]`, sorted by descending magnitude
- `/app/trace_integral.txt` — the value of the integral of tr(J(y(t))) over one complete period (single floating-point number)

All computed values must be accurate to at least 6 significant digits.