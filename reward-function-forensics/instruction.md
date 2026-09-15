A quadruped locomotion RL training pipeline has produced suboptimal policies. The reward computation modules contain bugs, the reward weight configuration has been lost, and a comprehensive multi-objective training audit with an optimal configuration recommendation is needed.

Provided files:
- `/app/reward_system.py` — Reward computation library with sigmoid-based tolerance functions and 10 locomotion reward/cost components (contains bugs)
- `/app/gait_utils.py` — Cubic Bézier gait trajectory utilities (contains a bug)
- `/app/data/trajectory.npz` — 500 timesteps of recorded quadruped state data
- `/app/data/reference_rewards.npy` — Correctly-computed total scalar rewards from a known-good backup
- `/app/data/training_history.db` — SQLite database of 20 past training experiments with reward weight configurations and performance metrics
- `/app/data_format.txt` — Data format and database schema documentation

Fix all bugs in the reward computation code, recover the 10 reward weight coefficients that reproduce the reference rewards from the trajectory data, and produce a comprehensive training audit. The audit must identify the closest historical ancestor, establish validated weight bounds, compute the Pareto front with its hypervolume indicator, quantify per-component sensitivity, and design an optimal balanced configuration via constrained optimization over the Pareto-optimal configurations.

Total reward formula: `total = clip(sum(w_i * component_i) * dt, 0.0, 10000.0)`. Known: `sigma=0.25`, `dt=0.02`, `swing_height=0.08`.

Write `/app/results/config.json`:
```json
{
  "sigma": <float>,
  "dt": <float>,
  "swing_height": <float>,
  "weights": {
    "tracking_lin_vel": <float>,
    "tracking_ang_vel": <float>,
    "lin_vel_z": <float>,
    "ang_vel_xy": <float>,
    "orientation": <float>,
    "action_rate": <float>,
    "torques": <float>,
    "joint_limits": <float>,
    "feet_air_time": <float>,
    "feet_clearance": <float>
  }
}
```

Write `/app/results/analysis.json`:
```json
{
  "ancestor_run_id": <int>,
  "weight_bounds": { "<name>": [<min>, <max>], ... },
  "pareto_front_run_ids": [<sorted ints>],
  "component_sensitivity": { "<name>": <float>, ... },
  "hypervolume_indicator": <float>,
  "designed_config": {
    "blending_weights": { "<run_id>": <float>, ... },
    "maximin_objective": <float>,
    "weights": { "<name>": <float>, ... }
  }
}
```

Field definitions:
- `ancestor_run_id`: training run with minimum L2 distance to the recovered weights
- `weight_bounds`: per-weight `[min, max]` from runs where `gait_quality_score > 0.7`
- `pareto_front_run_ids`: runs on the Pareto front of (`avg_episode_return`, `sim_to_real_transfer_score`), both maximized, sorted ascending
- `component_sensitivity`: coefficient of variation (population std / |mean|) of each weight across Pareto-optimal runs
- `hypervolume_indicator`: 2D hypervolume of the Pareto front relative to reference point `(38.5, 0.28)` — the per-objective minima across all training runs
- `designed_config`: find the convex combination of Pareto-optimal configurations (non-negative blending weights summing to 1) that maximizes the minimum of the two normalized objectives — `min(Σ λᵢ·returnᵢ/max_return, Σ λᵢ·transferᵢ/max_transfer)` — where normalization is by the per-objective maximum across the Pareto front. Report the non-zero blending weights keyed by run_id as string, the optimal maximin objective value, and the resulting 10 blended weight values.