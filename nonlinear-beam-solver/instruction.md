The environment at `/app/` contains:

- `/app/models/*.mbd` — Cantilever beam problems in MBDyn input format, each defining beam geometry, cross-section stiffness, boundary conditions, and applied tip loads/moments.
- `/app/kernels/so3_ops.c`, `so3_ops.h`, `Makefile` — C source providing SO(3) rotation operations with column-major matrix convention.

Produce `/app/beam_pipeline.py` that, when executed as `python3 /app/beam_pipeline.py`, computes the static equilibrium tip response for every `.mbd` model found in `/app/models/` and validates convergence.

**Constraints:**

- `/app/kernels/libso3.so` must be compiled and loaded via Python `ctypes` for rotation operations.
- All beam configuration must be extracted solely from the `.mbd` files (no hardcoded model parameters).
- The pipeline must handle any valid MBDyn-format cantilever beam model placed in `/app/models/`, not only the models shipped with the environment.

**Required outputs:**

`/app/results/<stem>.json` per model:
```json
{"model": "<stem>", "converged": true, "tip_displacement": [ux, uy, uz], "tip_rotation": [rx, ry, rz], "final_residual": <float>}
```
`tip_displacement`: free-end displacement vector from undeformed position (meters). `tip_rotation`: rotation vector at the free end (radians). `final_residual`: L2 norm of the equilibrium residual at the last converged load step.

`/app/validation.json`:
```json
{"models": {"<stem>": {"converged": <bool>, "final_residual": <float>, "pass": <bool>}, ...}, "all_pass": <bool>}
```
A model passes when it converges to equilibrium (final residual norm below the model's solver tolerance).

**Exit code:** 0 if all models converge and pass; 1 otherwise.
