A 2D EKF-SLAM system at `/app/` processes pre-generated scenario data (`/app/scenario.pkl`: 8 landmarks, 400 timesteps, known data association). The motion model is implemented in C (`/app/motion_model.c`, compiled to `/app/libmotion.so` via the provided `/app/Makefile`) and called from `ekf_slam.py` through ctypes. The observation model and filter logic are in Python (`/app/ekf_slam.py`). The data generator `/app/generate_data.py` produced the scenario and is correct.

Running `python3 /app/run_slam.py` shows the filter diverges and produces incorrect state estimates. The system has multiple defects across both C and Python components that must all be identified and corrected.

**Task 1 — Fix the system.** Identify and correct all defects so the filter converges. The corrected system must satisfy:

- Final robot position error < 2.0 m
- Final robot heading error < 0.3 rad
- Average landmark position error < 1.5 m
- Maximum landmark position error < 3.0 m
- Covariance positive semi-definite (min eigenvalue > -1e-6)
- All 8 landmarks observed and tracked
- No trajectory divergence (max intermediate position error < 5.0 m)

**Task 2 — Design a comparative filter robustness evaluation.** Once the system is corrected, create `/app/filter_evaluation.py` that implements at least two meaningfully different EKF covariance update strategies (they must differ in their mathematical update equation, not just in parameter tuning) and comparatively evaluates their robustness. Run each strategy under two conditions:

1. **Clean**: the original scenario data
2. **Corrupted**: a perturbed copy where 15% of range observations are replaced with outlier values drawn from U[0, 50] (use `numpy.random.RandomState(99)` for reproducible outlier index selection)

For each strategy × condition combination, compute: position RMSE (m), mean Normalized Innovation Squared (NIS), percentage of NIS values below the chi-squared 95% threshold (df=2, threshold=5.991), log10 of the final covariance matrix condition number, and whether the covariance remained positive semi-definite throughout execution.

Write `/app/filter_evaluation.json` containing:
- `formulations`: list of objects, each with `name` (str) and `clean`/`corrupted` sub-objects holding: `position_rmse` (float), `mean_nis` (float), `nis_below_95pct` (float), `log10_condition_number` (float or null), `psd_maintained` (bool)
- `recommended_formulation` (str): name of the strategy you judge most robust overall
- `rationale` (str): justification for your recommendation citing quantitative evidence from the evaluation