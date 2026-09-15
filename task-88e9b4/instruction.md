Implement a Sedov blast wave solver at `/app/sedov.py` that computes the exact self-similar solution for a point explosion in an ideal gas.

The Sedov–von Neumann–Taylor problem describes a strong shock wave produced by an instantaneous energy release at the origin, expanding into a uniform medium. The solver must produce numerically accurate radial profiles of density, velocity, pressure, specific internal energy, and sound speed for all three standard geometries (planar=1, cylindrical=2, spherical=3) with arbitrary specific heat ratio γ and the standard uniform-density case (ω=0).

## Required API

The module must expose five callable functions with the following signatures and return types:

**`compute_sedov_exponents(geometry, gamma, omega=0.0)`** → `dict`
Returns the six similarity exponents (`a0`–`a5`), the shock-jump similarity variable `v2`, the origin similarity variable `v0`, and derived constants `gpogm`, `xg2`, `denom2`, `denom3`, `a_val`, `b_val`, `c_val`, `d_val`, `e_val`.

**`compute_sedov_functions(v, geometry, gamma, omega=0.0)`** → `(lam, dlamdv, f, g, h)`
Evaluates the Sedov similarity functions at similarity variable `v`. Returns the spatial variable λ, its derivative dλ/dv, velocity ratio f, density ratio g, and pressure ratio h. All four functions must equal 1.0 at `v = v2`.

**`compute_energy_integrals(geometry, gamma, omega=0.0)`** → `(eval1, eval2, alpha)`
Computes the kinetic and internal energy integrals over the similarity variable domain and the energy normalization constant α.

**`compute_postshock(geometry, gamma, rho0, eblast, alpha, t, omega=0.0)`** → `dict`
Computes the post-shock state. Returns dict with keys `r2`, `rho2`, `u2`, `p2`, `e2`, `cs2`.

**`solve_sedov(r, t, geometry=3, gamma=1.4, rho0=1.0, eblast=0.851072, omega=0.0)`** → `dict`
Full profile solver. For each radial position in array `r` at time `t`, returns a dict with NumPy arrays `density`, `velocity`, `pressure`, `specific_internal_energy`, `sound_speed`, plus scalars `r2`, `alpha`, `eval1`, `eval2`.

## Numerical Accuracy Requirements

Reference values (γ=1.4, ω=0):

| Geometry | eval1 | eval2 | alpha |
|-----------|-----------|-----------|-----------|
| Spherical | 2.96269e-02 | 2.11647e-02 | 8.51060e-01 |
| Cylindrical | 6.54053e-02 | 4.95650e-02 | 9.84041e-01 |
| Planar | 1.97928e-01 | 1.75834e-01 | 5.38548e-01 |

- Post-shock density ratio must satisfy `(γ+1)/(γ−1)` exactly (6.0 for γ=1.4, 4.0 for γ=5/3).
- Shock position for the standard spherical case (eblast=0.851072, ρ₀=1.0, t=1.0) must be near r≈1.0.
- Outside the shock, density=ρ₀, velocity=0, pressure=0.
- Similarity functions must be accurate to 1e-3 absolute tolerance at representative sample points.
- Energy integrals must be accurate to 1e-5 for eval1 and 1e-3 for eval2/alpha.