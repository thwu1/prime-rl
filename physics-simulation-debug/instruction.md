A multi-layer computational physics pipeline at `/app/` simulates five systems: projectile ballistics, coupled oscillators, thermal diffusion, Keplerian orbits, and elastic collisions. The architecture spans a C shared library (`/app/lib/`, built with `make`), Python ctypes FFI bindings (`/app/engine.py`), TOML parameter files (`/app/config/`), and Python simulation drivers (`/app/simulations/`). Reference trajectories from a verified implementation are at `/app/reference/`.

Every simulation executes without crashing but produces physically implausible results. No error logs, diagnostic metadata, or known-issue documentation exists.

Perform a full numerical fidelity audit:

1. Evaluate each simulation's output against the conservation laws and physical invariants appropriate to that system — energy, momentum, symplectic structure, stability bounds, boundary conditions, and force-law symmetries as applicable. Quantify divergence from reference data.
2. For each discrepancy, determine whether the defect originates in the compiled numerical library, the Python-C marshalling layer, the physical parameter configuration, or the simulation equations. Some errors produce effects that mimic defects in a different layer.
3. Design and implement corrections across all affected layers. Rebuild compiled components with `make -C /app/lib` as needed.
4. Produce `/app/audit/report.json`: a JSON object keyed by simulation name (`ballistic`, `oscillator`, `diffusion`, `orbit`, `collision`), where each value is an object with fields:
   - `"layer"`: the pipeline layer containing the primary defect
   - `"root_cause"`: specific technical explanation of the error
   - `"conservation_law_violated"`: which physical principle the uncorrected code fails to satisfy

Diagnostic tools: `gnuplot` (`/app/tools/compare.gp`), `jq`, `make`.