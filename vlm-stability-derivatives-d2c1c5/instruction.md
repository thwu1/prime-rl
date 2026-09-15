The aerodynamic analysis pipeline at `/app/` computes lift, drag, and moment coefficients for wing configurations. It uses a modular Python package under `/app/aero/` backed by a C shared library (`/app/libvortex/`) for core vortex computations, loaded at runtime via ctypes. Ensure the pipeline produces results satisfying all acceptance criteria below.

**Required interface:** `python3 /app/vlm_solver.py <config_path> <output_path>`

**Input:** JSON with a `cases` array. Each case provides: `name` (string), `symmetry` (bool — half-wing mesh mirrored about y=0 plane), `mesh` (3D array `[nx][ny][3]` of surface coordinates in meters), `alpha_deg` (float), `v_inf` (float, m/s), `rho` (float, kg/m³), `S_ref` (float, m²), `c_ref` (float, m), `AR` (float), `moment_ref_pt` (`[x,y,z]` in meters). A sample config is at `/app/config.json`.

**Output:** JSON with a `cases` array (same length and order as input). Each case must contain: `CL`, `CDi`, `CM` (floats), `CL_alpha` and `CM_alpha` (floats, per radian), `static_margin` (float), `oswald_efficiency` (float), `circulations` (flat list of floats, length `(nx-1)*(ny-1)`) — all values must be finite.

**Acceptance criteria:**

At alpha=5° for both cases: CL > 0, CDi > 0, all circulations > 0. For `rectangular_wing`: 0.3 < CL < 0.65; 0.002 < CDi < 0.03; `CL_alpha` in [4.0, 6.5]/rad; `oswald_efficiency` in [0.7, 1.1]; |`static_margin`| < 0.2. For `swept_wing`: `CM_alpha` < −1.0/rad; `static_margin` > 0.3; `CM_alpha` more negative than rectangular wing's.

At alpha=0°: |CL|, |CDi|, |CM| each < 1e-10 for every case.

Linearity: CL(10°)/CL(5°) within 0.02 of 2.0; CL(2.5°)/CL(5°) within 0.02 of 0.5. CDi(10°)/CDi(5°) within 0.15 of 4.0; CDi(2.5°)/CDi(5°) within 0.02 of 0.25.

Derivative self-consistency: central finite difference of CL and CM at alpha ± 0.01° must match reported `CL_alpha` and `CM_alpha` within 1% relative error.

Formula consistency: `static_margin` = −`CM_alpha` / `CL_alpha` (within 1e-6). `oswald_efficiency` = CL² / (π · AR · CDi) (within 1e-6).

Anti-symmetry: CL(5°) = −CL(−5°) within 1e-8. CDi(5°) = CDi(−5°) relative within 1e-8.
