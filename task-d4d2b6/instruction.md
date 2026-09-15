Perform a complete kinematic analysis of the Baxter robot's 7-DOF right arm.

The environment provides:
- `/app/baxter.urdf` — Baxter robot description in URDF/XML format
- `/app/task_config.toml` — test configurations and solver parameters in TOML format

No robotics or kinematics libraries may be used (ikpy, PyKDL, roboticstoolbox, etc.). Extract the right arm kinematic chain from `base` through `right_gripper` (7 actuated revolute joints), enforcing all joint limits from the URDF.

For each joint configuration specified in the config file, compute the end-effector pose (as a 4×4 matrix). For each velocity-analysis configuration, compute the 6×7 matrix relating joint-space velocities to end-effector velocities, along with a scalar dexterity measure and a conditioning metric. For each target, find joint angles that place the end-effector at the specified position (and orientation if given), respecting joint limits.

Write results to **both** of the following output formats:

**SQLite database at `/app/results.db`** with tables:
- `chain_info` (`joint_name TEXT, joint_index INTEGER, lower_limit REAL, upper_limit REAL`) — 7 rows, one per actuated joint in chain order
- `fk_results` (`config_id INTEGER, joint_angles TEXT, pose_matrix TEXT`) — JSON-encoded arrays
- `jacobian_results` (`config_id INTEGER, joint_angles TEXT, jacobian_matrix TEXT, manipulability REAL, condition_number REAL`) — JSON-encoded arrays for matrix fields
- `ik_solutions` (`target_id INTEGER, target_position TEXT, target_orientation TEXT, solution_angles TEXT, achieved_position TEXT, position_error REAL, orientation_error REAL`)

**XML report at `/app/results.xml`** with root element `<kinematic_report>` (attributes: `robot`, `chain`, `dof`), containing:
- `<chain>` with 7 `<joint>` children, each having attributes: `name`, `index`, `lower`, `upper`
- `<fk_results>` with `<config>` children (attribute: `id`), each containing a `<position>` element (`x`, `y`, `z` attributes) and an `<orientation>` element (`r00` through `r22` attributes for the 3×3 rotation matrix)
- `<ik_solutions>` with `<target>` children having attributes: `id`, `px`, `py`, `pz`, `error`