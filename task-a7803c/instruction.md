`/app/brusselator_problem.py` defines a 2D Brusselator reaction-diffusion system on a 32×32 grid (2048 DOFs). Two chemical species (U, V) are coupled through nonlinear autocatalytic kinetics with diffusion under Neumann boundary conditions. A localized source activates at t=1.1.

Create `/app/solve_brusselator.py` (run via `python3 /app/solve_brusselator.py`) that produces all of the following output files. numpy and scipy are available. The full pipeline must complete within 300 seconds.

**`/app/solution_bdf.npz`** — Accurate solution for t ∈ [0, 11.5] using a BDF integrator with an analytical sparse Jacobian. Keys: `u_final`, `v_final` (32×32 at t=11.5), `u_mid`, `v_mid` (32×32 at t=5.75).

**`/app/solution_imex.npz`** — Solution of the same system using a separately-implemented IMEX integrator. Must remain stable and produce physically reasonable results over [0, 11.5]. Same keys as above.

**`/app/jacobian_at_t0.npz`** — The full 2048×2048 analytical Jacobian as a scipy sparse CSC matrix, evaluated at t=0 with `initial_conditions()`.

**`/app/stiffness_analysis.json`** — Spectral characterization of the Jacobian at t=0. Keys: `eigenvalues_largest` (list of 5 [real, imag] pairs, descending by magnitude), `eigenvalues_smallest` (5 [real, imag] pairs, ascending by magnitude), `stiffness_ratio` (float), `max_explicit_dt` (float).

**`/app/preconditioner_analysis.json`** — Performance comparison of GMRES on the linear system Jx = b (J = Jacobian at t=0, b = RHS vector at t=0) with and without ILU preconditioning. The preconditioned solve must achieve relative residual below 1e-5. Keys: `gmres_iters_no_precond` (int), `gmres_iters_ilu` (int), `ilu_fill_ratio` (float), `gmres_residual_no_precond` (float, relative), `gmres_residual_ilu` (float, relative).

**`/app/sparsity_analysis.json`** — Keys: `total_unknowns` (int), `nnz_jacobian` (int, structural nonzeros), `density` (float, nnz / total_unknowns²).