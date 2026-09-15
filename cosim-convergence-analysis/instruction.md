A PI-controlled DC motor system (controller → motor/gear → load inertia, with speed feedback) has been decomposed into three co-simulation subsystems. The subsystem definitions, physical parameters, coupling topology, dynamics equations, and Python classes are in `/app/subsystems.py`.

The system inputs are piecewise-constant: `w_desired` steps 0→10 rad/s at t=0.1 s; `tau_load` steps 0→3 N·m at t=0.5 s. Simulation interval is [0, 1] s. The full coupled system has 3 states: armature current (`i_a`), load-side angular speed (`w_load`), and PI integrator (`x_i`).

Produce two output files:

**`/app/reference.csv`** — High-accuracy monolithic reference solution of the full coupled 3-state ODE. 10001 uniformly-spaced points over [0, 1] s with columns `time,w` where `w` is motor-side speed (= ratio × w_load).

**`/app/results.json`** — Co-simulation convergence analysis comparing Jacobi and Gauss-Seidel master algorithms:

```json
{
  "reference_w_final": <w at t=1.0>,
  "jacobi": {
    "errors": {"0.0001": <rmse>, ..., "0.05": <rmse or null>},
    "convergence_order": <float>,
    "H_crit": <float>
  },
  "gauss_seidel": {
    "errors": {"0.0001": <rmse>, ..., "0.05": <rmse or null>},
    "convergence_order": <float>,
    "H_crit": <float>
  }
}
```

Sweep communication step sizes H ∈ {0.0001, 0.0002, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05}. For each (H, method) pair, report the RMSE of `w(t)` against the reference at communication points. A run is unstable if max|w| ≥ 100; report its RMSE as `null`. Use `str(H)` as dictionary keys (e.g., `"0.001"`).

`convergence_order`: slope of log(RMSE) vs log(H) over the stable range. `H_crit`: largest stable H from the sweep.