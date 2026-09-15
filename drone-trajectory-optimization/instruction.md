The Crazyflow differentiable drone simulator (`crazyflow==0.1.0`) is installed in the environment. You can explore its API via `python3 -c "import crazyflow; help(crazyflow)"` and by reading the installed package source.

## Scenario

A Crazyflie quadrotor has been displaced from its hover setpoint with the following state:
- Position: `(0.05, -0.03, 1.2)` meters
- Velocity: `(-0.02, 0.01, -0.08)` m/s
- Orientation: upright (identity quaternion)
- Angular velocity: zero

The drone must return to stable hover at target position `(0.0, 0.0, 1.0)` meters.

## Task

Write `/app/optimize.py` that finds an optimal sequence of **25 control commands** (each with 4 channels) over a 0.5-second horizon that recovers the drone to the target. The Crazyflow simulation runs at 500 Hz.

Your script must save results to `/app/result.json` containing:
- `final_pos`: 3-element list — drone position after executing the trajectory
- `final_vel`: 3-element list — drone velocity after executing the trajectory
- `initial_loss`: float — loss value before optimization
- `final_loss`: float — loss value after optimization
- `commands`: 25x4 nested list — the optimized command sequence
- `n_iterations`: int — number of optimization iterations performed

## Success criteria

- Euclidean distance from final position to `(0, 0, 1)` must be less than **0.15 m**
- Final velocity magnitude must be less than **0.5 m/s**
- The loss must decrease during optimization (`final_loss < initial_loss`)
- The solution must leverage automatic differentiation through the simulator dynamics