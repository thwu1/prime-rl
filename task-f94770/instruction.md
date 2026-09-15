The differential inverse kinematics solver at `/app/ik_solver.py` for the 6-DOF robot arm (`/app/robot.xml`) is broken — it fails to produce correct solutions. The implementation contains multiple independent bugs across its mathematical primitives and constraint logic.

Debug and fix all issues in `/app/ik_solver.py` so the solver produces correct, constraint-respecting inverse kinematics solutions. The module's public API (function names and signatures) must not change.

Pre-installed: `mujoco`, `numpy`, `qpsolvers` (with `daqp` backend).