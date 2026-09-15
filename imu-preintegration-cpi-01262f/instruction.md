A C++ reference implementation of two IMU continuous preintegration models exists in `/app/reference/`, with sensor configuration and IMU data in `/app/data/`. The C++ codebase has build and runtime defects that prevent it from producing valid output.

The following files must exist and be fully functional:

**`/app/build/generate_groundtruth`** — C++ executable built from `/app/reference/` via CMake (build directory: `/app/build/`). When run, must produce `/app/output/groundtruth_v1.json` (Model 1) and `/app/output/groundtruth_v2.json` (Model 2) using parameters from `/app/data/sensor_config.json` and measurements from `/app/data/imu_sequence.csv`.

**`/app/cpi_preintegration.py`** — Python module implementing both models consistent with the C++ reference. Required public API:

Module-level functions: `skew_x(w)`, `quat_2_rot(q)`, `rot_2_quat(R)`, `quat_multiply(q,p)`, `exp_so3(w)`, `log_so3(R)` — JPL quaternion convention `[qx, qy, qz, q4]`.

`CpiV1(sigma_w, sigma_wb, sigma_a, sigma_ab, imu_avg=False)`:
- `set_linearization_points(b_w_lin, b_a_lin)`
- `feed_imu(t_0, t_1, w_m_0, a_m_0, w_m_1=None, a_m_1=None)`
- Attributes: `DT`, `alpha_tau(3,)`, `beta_tau(3,)`, `R_k2tau(3,3)`, `q_k2tau(4,)`, `J_q`, `J_a`, `J_b`, `H_a`, `H_b` (all 3x3), `P_meas(15,15)`

`CpiV2(sigma_w, sigma_wb, sigma_a, sigma_ab, imu_avg=False)`:
- `set_linearization_points(b_w_lin, b_a_lin, q_k_lin, grav)`
- `feed_imu(...)` same signature as CpiV1
- Same attributes as CpiV1, plus `O_a(3,3)`, `O_b(3,3)`, `P_big(21,21)`

**`/app/process_imu.py`** — Reads `/app/data/sensor_config.json` and `/app/data/imu_sequence.csv`, runs both models, writes `/app/output/preintegrated_v1.json` and `/app/output/preintegrated_v2.json`.

**JSON schema** (all four output files):
```json
{"DT": <float>, "alpha_tau": [3], "beta_tau": [3], "q_k2tau": [4], "P_meas_trace": <float>, "P_meas_diag": [15]}
```

**Success criteria**: Python pipeline results must match C++ ground truth within 1e-10 for all fields. Model 1 and Model 2 outputs must differ from each other.
