An OpenFOAM case directory at `/app/case/` defines a 1D compressible flow problem for an ideal gas. The case files encode the complete problem specification: initial left/right states, thermophysical gas properties, domain geometry, and simulation end time.

Analyze this problem by producing an exact analytical solution, numerical solutions at multiple resolutions, and diagnostic output characterizing the solution structure and numerical convergence. All physical parameters must be extracted programmatically from the case files.

## Required outputs

**`/app/riemann.py`** — A Python module exposing:
- `solve(rhoL, uL, pL, rhoR, uR, pR, gamma)` returning a dict with keys `p_star`, `u_star`, `rho_star_L`, `rho_star_R`
- `sample(x, t, x0, rhoL, uL, pL, rhoR, uR, pR, gamma)` returning a tuple `(rho, u, p)` at position `x` and time `t`, with initial discontinuity at `x0`

This module must produce correct results on standard test problems (e.g. Sod), not just the specific case provided.

**Files in `/app/results/`:**
- `exact_solution.csv` — exact solution sampled at 1000 uniformly-spaced points across the full domain at the final time. Columns: `x,rho,u,p,e` (e = specific internal energy)
- `numerical_100.csv`, `numerical_200.csv`, `numerical_400.csv` — numerical solutions at N=100, 200, 400 cells. Columns: `x,rho,u,p`
- `convergence.json` — `{"L1_errors": {"rho": [e100, e200, e400], "u": [...], "p": [...]}, "convergence_rates": {"rho": rate, "u": rate, "p": rate}}` where rate = log(e100/e400)/log(4)
- `wave_structure.json` — `{"left_wave": {"type": "shock"|"rarefaction", ...}, "contact": {"speed": ...}, "right_wave": {"type": "shock"|"rarefaction", ...}, "star_region": {"pressure": ..., "velocity": ..., "density_left": ..., "density_right": ...}}` — rarefaction waves must include `head_speed` and `tail_speed`; shock waves must include `speed`