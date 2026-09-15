#!/usr/bin/env python3
"""Generate output files for the parameter estimation pipeline.

"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, '/app')
from estimator import estimate_parameters, load_pipeline_data, _solve_fwd, _compute_loss
from system import TRUE_PARAMS

# Load data
t_eval, y_data, y0, p_init = load_pipeline_data()
true_p = np.array(TRUE_PARAMS)

# Estimate parameters
print("Running parameter estimation...")
p_est = estimate_parameters(y_data, t_eval, y0, p_init)
rel_err = np.abs((p_est - true_p) / true_p)
print(f"Estimated: {p_est}")
print(f"True:      {true_p}")
print(f"Rel error: {rel_err}")

# Compute trajectory with estimated parameters
sol = _solve_fwd(p_est, y0, [t_eval[0], t_eval[-1]], t_eval=t_eval)
nfev = sol.nfev

# Compute final loss
final_loss = _compute_loss(p_est, y0, t_eval, y_data)

# Produce output files
os.makedirs('/app/results', exist_ok=True)

# parameters.json
params_out = {
    'recovered_params': p_est.tolist(),
    'relative_errors': rel_err.tolist(),
    'converged': bool(np.all(rel_err < 0.1)),
}
with open('/app/results/parameters.json', 'w') as f:
    json.dump(params_out, f, indent=2)
print("Wrote /app/results/parameters.json")

# trajectory.csv
with open('/app/results/trajectory.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['time', 'prey', 'predator'])
    for i in range(len(t_eval)):
        writer.writerow([t_eval[i], sol.y[0, i], sol.y[1, i]])
print("Wrote /app/results/trajectory.csv")

# diagnostics.json
diag = {
    'solver_method': 'RK45',
    'num_function_evaluations': int(nfev),
    'final_loss': float(final_loss),
}
with open('/app/results/diagnostics.json', 'w') as f:
    json.dump(diag, f, indent=2)
print("Wrote /app/results/diagnostics.json")
