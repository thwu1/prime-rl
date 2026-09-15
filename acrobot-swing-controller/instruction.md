Implement a controller that swings up a double pendulum acrobot from the stable hanging-down equilibrium to the unstable inverted (upright) equilibrium and stabilizes it there.

The acrobot is a two-link planar pendulum with a fixed pivot. Only joint 2 (the elbow) is actuated, with a torque limit of +/-6.0 Nm. Joint 1 (the shoulder) is completely passive. The state vector is x = [q1, q2, qdot1, qdot2] where joint angles are measured from the downward-hanging position and qdot values are angular velocities.

Physical parameters are in `/app/params.json`. Equations of motion (mass matrix, Coriolis matrix, gravity vector, friction, energy, forward kinematics) are in `/app/equations.md`. The scoring formula is in `/app/scoring.md`.

Write a self-contained Python program (only numpy and scipy permitted as external dependencies) that:

- Simulates the acrobot for T=10 s from initial state x0 = [0, 0, 0, 0] using 4th-order Runge-Kutta integration with timestep dt = 0.002 s
- Applies a control law that swings the acrobot up to the goal state x_goal = [pi, 0, 0, 0] while respecting the torque constraints (u1 = 0 always, |u2| <= 6.0 Nm)
- Writes `/app/trajectory.csv` with columns: time, q1, q2, qd1, qd2, u1, u2 (one row per timestep, control u_i at row i is applied during the step from row i to row i+1; final row has u=[0,0])
- Writes `/app/score.json` with the RealAI Score and all sub-criteria

The end-effector (tip of link 2) must be above height y_ee >= 0.45 m (relative to the pivot) at the end of the simulation and must remain continuously above from the moment it first crosses the threshold until the end. The RealAI Score must be >= 0.15.