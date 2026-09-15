A MuJoCo model at `/app/model.xml` defines a motorized cart-and-pendulum mechanism. A previous attempt to control this system is at `/app/controller_attempt.py` — it fails to keep the pendulums upright. Investigate the model to understand its kinematic structure (joints, degrees of freedom, actuation), diagnose why the existing controller fails, and build a controller that successfully stabilizes the entire system at the upright equilibrium (all joint angles zero).

**Performance requirements** (simulation starts from `qpos = [0.0, 0.15, -0.1]`, zero initial velocities):

- During a 10-second closed-loop simulation:
  - Cart position must stay within +/-2.0 meters at all times.
  - Control force must respect the model's actuator limits at all times.
  - At t=10s, each pendulum angle must be below 0.02 rad in absolute value.
- After t=5.0s and for the remainder of the simulation, all pendulum angles must remain below 0.01 rad and all angular velocities below 0.1 rad/s.

**Required output files in `/app/results/`** (all comma-separated, no headers unless noted):

- `A.csv` — 6×6 matrix
- `B.csv` — 6×1 matrix
- `K.csv` — 1×6 row vector; the controller applies `u = -K @ x` where `x = [qpos; qvel]` is the 6-dimensional state vector
- `controllability_rank.txt` — single integer (plain text, not CSV)
- `closed_loop_eigenvalues.csv` — eigenvalues of `(A - B @ K)`, two columns: real, imag; all magnitudes must be strictly below 0.999
- `trajectory.csv` — closed-loop simulation log with exactly 8 columns: time, cart_pos, angle1, angle2, cart_vel, omega1, omega2, ctrl; at least 100 rows spanning at least 9.9 seconds