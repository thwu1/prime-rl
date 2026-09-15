The workspace at `/app/` contains a partially-implemented quadrotor flight dynamics simulator for a Crazyflie 2.x micro-drone. Three Python modules have stub functions that raise `NotImplementedError`:

- `/app/dynamics.py` — rigid-body dynamics model
- `/app/integrator.py` — numerical integration
- `/app/sysid.py` — physical parameter estimation

Complete all stubs so that the pipeline at `/app/predict.py` executes end-to-end successfully.

Physical constants known a priori are in `/app/known_params.json`. Training flight recordings (timestamped states and rotor commands) are in `/app/data/training_*.npz`. Three physical parameters — drone mass, thrust coefficient (`k_f`), and torque coefficient (`k_m`) — are **unknown** and must be recovered from the training data.

After implementing all stubs, run `python3 /app/predict.py`.

## Output requirements

The pipeline must produce files in `/app/output/`:

- **`estimated_params.json`** — JSON object with keys `mass`, `k_f`, `k_m` (all floats). Required accuracy: `mass` and `k_f` each within 3% of true values; `k_m` within 5%.
- **`scenario_1.npz`**, **`scenario_2.npz`**, **`scenario_3.npz`** — each containing arrays `positions` (501, 3), `quaternions` (501, 4), `velocities` (501, 3), `angular_velocities` (501, 3). All quaternion rows must be unit-norm (tolerance 1e-4). Position RMSE for each scenario must be below 0.05 m.