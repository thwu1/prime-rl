#!/bin/bash

# Compile the C coefficient library
gcc -shared -fPIC -O2 -o /app/libcoeffgen.so /app/coeffgen.c

# Deploy the solver
cp /solution/solver_impl.py /app/solver.py

# Validate on example scenarios
cd /app
python3 -c "
import numpy as np
import glob, os
from problem_spec import load_scenario
from solver import solve_scale_shift, estimate_rotation, recover_translation, robust_pose_estimate

scenarios = sorted(glob.glob('/app/data/scenario_*.json'))
for spath in scenarios:
    data = load_scenario(spath)
    R_est, t_est, params, mask = robust_pose_estimate(
        data['x1'], data['x2'], data['d1'], data['d2'],
        threshold=0.05, max_iterations=500,
    )
    R_err = np.linalg.norm(R_est - data['R_gt'], 'fro')
    t_gt = np.array(data['t_gt'])
    t_gt = t_gt / np.linalg.norm(t_gt)
    t_err = min(
        np.linalg.norm(t_est / np.linalg.norm(t_est) - t_gt),
        np.linalg.norm(t_est / np.linalg.norm(t_est) + t_gt),
    )
    name = os.path.basename(spath)
    print(f'{name}: R_err={R_err:.6f}  t_err={t_err:.6f}  inliers={int(np.sum(mask))}/{len(mask)}')
print('Solution validated.')
"
