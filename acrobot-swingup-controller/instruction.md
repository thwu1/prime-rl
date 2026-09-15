Implement a swing-up and stabilization controller for an underactuated double pendulum in the acrobot configuration (motor at the elbow joint only; the shoulder joint is completely passive).

The simulation framework is provided at `/app/`:

- `plant.py` — Lagrangian dynamics model (mass matrix, Coriolis, gravity, Coulomb+viscous friction)
- `simulator.py` — RK4 integration engine
- `scoring.py` — RealAI Score: composite metric over swing-up time, actuator energy, torque cost, torque smoothness, and velocity cost
- `params.json` — Physical parameters (link masses/lengths/inertias, friction coefficients, torque limits, simulation settings)
- `run_simulation.py` — Entry point that loads the controller, runs the simulation, and writes `/app/results.json`

Create `/app/controller.py` with a class `AcrobotController` whose constructor signature is `__init__(self, plant, params)` and that exposes `get_control_output(self, state, t)` returning a scalar torque value. The `state` argument is `[q1, q2, q1_dot, q2_dot]` (angles measured from hanging-down equilibrium) and `t` is the current simulation time in seconds.

The controller must swing the acrobot from rest at `[0, 0, 0, 0]` to the inverted equilibrium `[pi, 0, 0, 0]`, keeping the end-effector above 0.45 m (measured from the pivot) for at least 2 continuous seconds within the 10-second simulation window. Torques must remain within +/-6.0 Nm. The RealAI Score reported by `/app/scoring.py` must exceed 0.3.

Validate with `python3 /app/run_simulation.py`.