A turbulent backward-facing step CFD simulation at `/app/backwardStep/` crashes when run with OpenFOAM 12 (`incompressibleFluid` solver, k-epsilon turbulence). Multiple independent configuration errors in `system/` and `0/` prevent convergence. The mesh geometry and physical properties are correct.

Fix all errors so the simulation converges (all residuals below 1e-4), then build a post-processing validation pipeline that evaluates the physical accuracy of the converged solution.

Create `/app/backwardStep/validate.py` that parses the converged OpenFOAM mesh and field data to compute the reattachment length x_r (the downstream distance from the step where reversed near-wall streamwise velocity changes sign from negative to positive on the lower wall), verify mass conservation from solver continuity errors, and evaluate accuracy against the experimental benchmark x_r/h = 7.0 (Armaly et al., 1983). The script must parse the actual OpenFOAM `constant/polyMesh/` mesh files and time-step field data — not hardcode values.

The script must produce `/app/backwardStep/validation_report.json` with exactly these fields:

- `reattachment_length_m` (float): x_r in meters
- `step_height_m` (float): step height h in meters
- `xr_over_h` (float): x_r / h
- `experimental_xr_over_h` (float): 7.0
- `accuracy_percent_error` (float): |xr_over_h - 7.0| / 7.0 * 100
- `inlet_mass_flow_m3s` (float): volumetric flow rate at inlet
- `continuity_error_final` (float): final global continuity error from solver log
- `mass_conservation_ok` (bool): true if mass conservation is acceptable
- `final_residuals` (dict): {Ux, p, k, epsilon} mapped to final initial residuals
- `converged` (bool): true if all residuals < 1e-4
- `total_iterations` (int): solver iterations completed
- `validation_verdict` (string): "pass" if converged AND 3.0 <= x_r/h <= 12.0 AND mass_conservation_ok; else "fail"

Run the simulation and the validation pipeline. Leave all output (time directories, logs, report) in `/app/backwardStep/`.

OpenFOAM 12 environment: `source /opt/openfoam12/etc/bashrc`