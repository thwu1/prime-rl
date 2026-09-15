Implement a swing-up and stabilization controller for an acrobot double pendulum.

The simulation framework is at `/app/`. Edit `/app/my_controller.py` to implement a `MyController` class whose `get_control_output(x, t)` method returns motor torques `[u1, u2]`.

The acrobot is a two-link pendulum where only joint 2 is actuated (max torque 6.0 Nm; joint 1 is passive). It starts at the stable hanging equilibrium `x0 = [0, 0, 0, 0]` (both links down) and must reach the unstable inverted equilibrium at `x_goal = [pi, 0, 0, 0]` (both links up). The state vector is `[q1, q2, qd1, qd2]` — joint angles measured from the hanging vertical and their velocities.

The end-effector (tip of link 2) must be above height `h = 0.45 m` (relative to the mount point) continuously for the final 2 seconds of a 10-second simulation. The simulation uses RK4 integration with `dt = 0.002 s`. No process or measurement noise is applied.

See `/app/plant.py` for the dynamics API (mass matrix, Coriolis, gravity, energy, forward kinematics, etc.), `/app/config.py` for the exact model parameters, and `/app/simulator.py` for the integrator. You may install additional Python packages as needed.