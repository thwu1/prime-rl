`/app/poisson3d.c` is a naive Conjugate Gradient solver for the 3D Poisson equation −∇²u = f on [0,1]³ with N=100 interior points per axis, zero Dirichlet boundary conditions, and manufactured solution u(x,y,z) = x(1−x)y(1−y)z(1−z). It stores the sparse matrix explicitly in CSR format and uses unpreconditioned CG, requiring hundreds of iterations to converge. A basic Makefile exists at `/app/Makefile`.

Produce three deliverables:

**`/app/profile_report.txt`** — Cache performance analysis of the naive solver on a reduced grid (e.g. N=30 for tractable runtime). Must contain exactly these key=value lines:

    D1_miss_rate=<float percentage>
    DLmiss_rate=<float percentage>
    total_instructions=<integer>

**`/app/CMakeLists.txt`** with an out-of-source build at `/app/build/` — CMake build system defining targets `poisson3d` (naive) and `fast_poisson` (optimized). The `fast_poisson` binary must dynamically link against libgomp.

**`/app/fast_poisson.c`** — An optimized solver for the identical discrete problem satisfying all of:

- Relative residual ‖b − Ax‖/‖b‖ < 10⁻¹⁰
- At most 200 iterations to converge
- L∞ error < 5×10⁻³ against the manufactured solution
- Writes `/app/results.txt` with key=value lines: `iterations`, `relative_residual`, `max_error`, `time`, `grid_n=100`
- Writes `/app/solution.bin` containing N³ = 10⁶ doubles in column-major order (flat index i + N·j + N²·k)