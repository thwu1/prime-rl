A co-simulation environment at `/app/` models a PI-controlled DC electric drive decomposed into three FMI 2.0-style subsystems. The subsystem implementations are in `/app/subsystems.py`, each exposing `initialize()`, `doStep(t, dt, inputs) -> outputs`, `getState() -> dict`, and `setState(state)` methods.

Interface descriptions for each subsystem follow the FMI 2.0 `modelDescription.xml` standard and are located in `/app/model_descriptions/`. The inter-subsystem wiring is defined in `/app/system_structure.ssd`, which follows the SSP (System Structure and Parameterization) standard with XML namespaces `ssd:` and `ssc:`. A monolithic reference solver is at `/app/reference_solver.py`.

Create `/app/cosim_master.py` — a co-simulation master that parses the SSP and modelDescription XML files to discover the subsystem topology and connection graph, then orchestrates the subsystems exclusively through their `doStep` interface. The master must dynamically construct its execution plan from the parsed XML topology — it must not function if `/app/system_structure.ssd` or the `/app/model_descriptions/` directory are removed.

When executed via `python3 /app/cosim_master.py`, it must produce `/app/results/` containing:

- `gauss_seidel.csv`: fixed macro-step (h=0.001 s) Gauss-Seidel coupling results with columns `time,w`
- `jacobi.csv`: fixed macro-step (h=0.001 s) Jacobi coupling results with columns `time,w`
- `adaptive.csv`: adaptive macro-step results with columns `time,w`
- `analysis.json` with these keys (all numeric):
  - `convergence_order`: observed rate at which co-simulation error decreases with macro-step size; must be strictly between 0.5 and 2.0
  - `stability_limit_jacobi`: largest stable macro-step for Jacobi coupling; must be positive and <= 1.0 s
  - `stability_limit_gauss_seidel`: largest stable macro-step for Gauss-Seidel coupling; must be positive, <= 1.0 s, and >= `stability_limit_jacobi`
  - `rmse_adaptive`: RMSE of the adaptive solution vs the monolithic reference; must be consistent with independently computed RMSE to within 0.05
  - `total_steps_adaptive`: number of macro-steps taken by the adaptive method

Quality constraints:
- All CSV files must have >= 10 data rows with finite values in every cell.
- Fixed-step solutions must remain numerically stable: max |w| < 1000.
- Gauss-Seidel at h=0.001 must achieve RMSE < 0.5 vs the monolithic reference.
- The drive's load angular velocity should start near zero and reach approximately 10 rad/s in steady state.
- The adaptive solution must achieve RMSE < 0.01 vs the monolithic reference over [0, 1] s. Discontinuities in the reference signals may affect adaptive accuracy if not handled properly.
- The master's source code must contain XML parsing logic (e.g. `xml.etree`, `lxml`, `ElementTree`).