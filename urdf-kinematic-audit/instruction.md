A parameterized xacro file at `/app/manipulator.xacro` describes a 4-DOF articulated manipulator arm using xacro macros, property substitutions, and math expressions. The file contains errors at multiple abstraction levels — xacro preprocessing errors that prevent URDF generation, structural errors in the kinematic tree, and physical specification violations that would cause simulation failures. The arm's kinematic and dynamic properties must be characterized at a specific operating configuration.

Produce the following files in `/app/`:

**`errors.json`** — A JSON list of every error found across both xacro preprocessing and URDF specification layers. Each entry must have keys `"error_type"` (descriptive snake_case identifier), `"element"` (the affected joint, link, or macro/property name), and `"description"`.

**`robot_fixed.urdf`** — A corrected URDF with all xacro and specification violations resolved. Each fix must be the minimal change that restores validity while preserving the robot's intended geometry and physical properties.

**`ee_pose.json`** — End-effector pose (4x4 homogeneous transformation matrix in the base frame) computed from the corrected model for revolute joint angles `[0.5, -0.3, 0.8, -0.2]` radians in kinematic chain order. Format: `{"transform": [[...], [...], [...], [...]]}`.

**`mass_properties.json`** — Total robot mass and center of mass in the base frame at zero configuration. Format: `{"total_mass": <float>, "center_of_mass": [x, y, z]}`.

**`jacobian.json`** — The 6x4 geometric Jacobian at joint angles `[0.5, -0.3, 0.8, -0.2]`, mapping joint velocities to end-effector spatial velocity (linear velocity rows first, angular velocity rows second). Format: `{"jacobian": [[...], ...]}`.

**`dynamics.json`** — The 4x4 joint-space mass matrix M(q) and the 4-element gravity torque vector g(q) at joint angles `[0.5, -0.3, 0.8, -0.2]` with gravitational acceleration `[0, 0, -9.81]` m/s². Convention: `M(q)q̈ + C(q,q̇)q̇ + g(q) = τ`. Format: `{"mass_matrix": [[...], ...], "gravity_torques": [...]}`.

**`manipulability.json`** — Yoshikawa kinematic manipulability index from the translational Jacobian with ellipsoid semi-axes (descending order), and the dynamic manipulability index with semi-axes computed from the translational Jacobian weighted by M⁻¹(q). Format: `{"manipulability_index": <float>, "ellipsoid_axes": [...], "dynamic_manipulability_index": <float>, "dynamic_ellipsoid_axes": [...]}`.