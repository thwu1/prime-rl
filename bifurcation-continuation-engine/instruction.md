A file `/app/systems.py` defines three parameterized ODE systems (`cusp_normal_form`, `brusselator`, `abc_reaction`). Each entry provides `rhs`, `jacobian`, `dim`, `param_range`, `initial_state`, and `initial_param`. A companion C source `/app/rhs_eval.c` provides equivalent C implementations with calling convention `void name_rhs(int n, const double *x, double param, double *f_out)` and `void name_jac(int n, const double *x, double param, double *J_out)` (row-major), plus `int get_system_count(void)`.

Build a bifurcation analysis pipeline in `/app/`. Running `python3 /app/analyze.py` must produce all outputs below.

**Shared library**: Compile `/app/rhs_eval.c` into `/app/librhs.so`. The analysis must load this library via Python `ctypes` and use its C functions for RHS and Jacobian evaluation during continuation. `get_system_count()` must return 3. C function outputs must be consistent with the Python implementations in `systems.py`.

**Continuation and detection**: For each system, trace the full equilibrium branch across `param_range` including through turning points. Detect and locate saddle-node (fold) points where a real eigenvalue crosses zero. Detect and locate Hopf points where a complex conjugate pair crosses the imaginary axis. Classify each Hopf point as subcritical or supercritical via the first Lyapunov coefficient sign.

**Results** — write `/app/results.json`:

```json
{
  "<system_name>": {
    "fold_points": [{"parameter_value": <float>, "state": [<float>, ...]}],
    "hopf_points": [{"parameter_value": <float>, "state": [<float>, ...],
                     "omega": <float>, "subcritical": <bool>}]
  }
}
```

All three system names as top-level keys. State vector length must equal system dimension.

**Diagram**: Write tab-separated continuation data to `/app/continuation_data.dat` with columns `system_name`, `parameter`, `state_norm`, `point_type` (one of `regular`, `fold`, `hopf`). Data must include entries for all three systems with both fold and hopf annotations present. Create a gnuplot script at `/app/plot_bifurcation.gp` and use it to generate `/app/bifurcation_diagram.png` as a valid PNG via gnuplot in non-interactive mode.

**Acceptance criteria**:

- Every reported equilibrium: `||f(x,p)|| < 1e-4`.
- Fold eigenvalue: Jacobian has a real eigenvalue with `|λ| < 0.05`.
- Hopf eigenvalue: complex pair with `|Re(λ)| < 0.05`; `omega > 0` and within 10% of `|Im(λ)|`.
- `cusp_normal_form`: exactly 2 folds at `±2√3/9 ≈ ±0.3849` (tolerance 0.01) with states `±1/√3 ≈ ±0.5774` (tolerance 0.02); zero Hopf points.
- `brusselator`: zero folds; at least 1 Hopf at `B = 3.25` (tolerance 0.02) with equilibrium state `(1.5, 3.25/1.5)` (tolerance 0.05), `omega ≈ 1.5` (10% tolerance), supercritical (`"subcritical": false`).
- `abc_reaction`: at least 1 Hopf within `param_range`; `omega > 0`; `subcritical` is boolean.
- Only `numpy` and `scipy` as Python numerical libraries.
