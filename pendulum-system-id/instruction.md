A double compound pendulum was observed swinging freely under gravity. The pendulum consists of two uniform rigid rods connected by revolute joints with viscous damping. The observed joint position trajectory (positions only, no velocities) is at `/app/data/trajectory.json` and the known simulation configuration is at `/app/data/config.json`. The mass of the first link (`m1`) is known from direct measurement and is provided in the config. The initial joint velocities are unknown.

The forward dynamics simulator at `/app/simulator.py` implements the Lagrangian equations of motion using Christoffel-symbol Coriolis terms and semi-implicit Euler integration. Study the simulator to understand the physical model, its parameterization, and the relationship between parameters and trajectory behavior. Note that the equations of motion exhibit a mass-scale degeneracy: without fixing at least one mass, the remaining masses and damping coefficients are only identifiable up to a common multiplicative factor. The known `m1` in the config breaks this symmetry.

Estimate the following unknown physical parameters and initial conditions from the observed trajectory data:
- Link 2 mass: `m2` (kg)
- Link lengths: `l1`, `l2` (m)
- Viscous damping coefficients: `b1`, `b2` (N*m*s/rad)
- Initial angular velocities: `qd1_0`, `qd2_0` (rad/s)

Write the estimated parameters to `/app/estimated_params.json` as a JSON object with keys: `m2`, `l1`, `l2`, `b1`, `b2`, `qd1_0`, `qd2_0`.