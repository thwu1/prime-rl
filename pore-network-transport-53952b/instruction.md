Implement `/app/pnm_solver.py` exporting the functions below. A partial reference implementation exists at `/app/starter.py`; it may contain errors. Network validation data is in `/app/networks/`.

**`build_cubic_network(shape, spacing=1.0)`** — Returns dict: `Np` (int), `Nt` (int), `coords` (Np×3 float, C-order raveled pore centers scaled by spacing), `conns` (Nt×2 int, axis-aligned 6-connectivity neighbor pairs, no duplicates or self-links), face-label boolean arrays (length Np): `left`/`right` (axis 0 min/max), `front`/`back` (axis 1 min/max), `bottom`/`top` (axis 2 min/max). When a dimension has size 1, both opposing face labels include all pores along that axis.

**`assemble_coefficient_matrix(Np, conns, conductances)`** — Sparse Np×Np matrix from throat conductances. A scalar conductance must broadcast identically to all throats. Must be symmetric, have zero row sums, and positive diagonal entries.

**`apply_value_bc(A, b, pore_indices, values)`** — Dirichlet elimination returning `(A_mod, b_mod)`. Must not alter the originals. Sequential calls for distinct BC sets must not corrupt prior applications.

**`solve_diffusion(network, conductances, bc_specs)`** — Steady-state Fickian diffusion. `bc_specs`: list of `(index_array, value)` tuples. Returns Np concentration array. Uniform conductance with opposing-face BCs must produce exact linear profiles along the gradient axis. A single Dirichlet BC with near-zero conductance must yield uniform concentration at the prescribed value.

**`solve_reactive_transport(network, conductances, bc_specs, source_pores, prefactor, exponent, max_iter=5000, f_rtol=1e-6, x_rtol=1e-6)`** — Nonlinear transport with source `r = prefactor · X^exponent` at `source_pores`. Iterates until both residual-norm and solution-change-norm satisfy tolerances relative to their initial values. Returns dict: `concentration` (Np array), `converged` (bool), `num_iter` (int). With `prefactor=0` must match pure diffusion. BC values preserved. Non-negative concentrations for consumption sources. A stronger consumption prefactor must lower mean concentration.

**`solve_transient_diffusion(network, conductances, pore_volumes, bc_specs, x0, tspan)`** — Time-dependent diffusion from `tspan[0]` to `tspan[1]`. `pore_volumes` and `x0` accept scalars or Np arrays. BC pore values remain fixed throughout. Returns Np array at final time. Must approach steady state at large times and evolve monotonically toward equilibrium.

**`compute_rate(network, conductances, concentration, pores)`** — Scalar net outward flux through `pores` from the full (pre-BC) coefficient matrix applied to the concentration field. Steady-state total over all pores: zero. Inlet/outlet rates must exactly balance.

**`compute_effective_diffusivity(network, conductances, concentration, inlet_pores, outlet_pores, domain_length, cross_section_area)`** — Returns `|rate_inlet| · domain_length / (cross_section_area · |mean_c_outlet − mean_c_inlet|)` where `rate_inlet` comes from `compute_rate`. For uniform-conductance cubic networks, `D_eff` must equal the conductance value. Tests also verify `D_eff` against analytical values using layered-conductance scenarios from `/app/networks/` (JSON files specifying `shape`, `spacing`, `layer_conductances`, `cross_section_conductance`, boundary conditions, and reference values).
