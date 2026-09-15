A Poppy Torso humanoid robot URDF is at `/app/poppy_torso.urdf` and kinematic problem specifications are at `/app/problems.json`. Write a solver that processes each problem and outputs all solutions to `/app/results.json` as a JSON object keyed by problem ID.

The problems file defines two kinematic chain specifications (left and right arm, each traversing from the robot base through torso joints to the respective arm) and a set of problems:

- **forward_kinematics**: Given a joint angle vector, compute the end-effector 4x4 homogeneous transformation matrix. Output `{"position": [x,y,z], "orientation_matrix": [[r00,r01,r02],[r10,r11,r12],[r20,r21,r22]]}`.

- **inverse_kinematics**: Given a target 3D position, find joint angles that place the end-effector there. Output `{"joint_angles": [full vector with one entry per chain link], "achieved_position": [x,y,z]}`. The solution must respect joint limits from the URDF.

- **jacobian**: Compute the 3xN positional Jacobian mapping active joint velocities to end-effector linear velocity at the given configuration, where N is the number of active joints. Output `{"jacobian": [[3xN matrix]]}`.

- **max_manipulability**: Find the active joint configuration that maximizes the Yoshikawa manipulability measure sqrt(det(J*J^T)) subject to URDF joint limits. Output `{"joint_angles": [full vector], "manipulability": float}`.

- **dual_arm_ik**: Solve IK for both arms simultaneously. Torso joints at chain indices 1, 2, 3 (abs_z, bust_y, bust_x) must have identical values in both arms' joint vectors. Output `{"left_joint_angles": [...], "right_joint_angles": [...], "left_achieved_position": [x,y,z], "right_achieved_position": [x,y,z]}`.

Joint angle vectors have one entry per chain link, including the origin link at index 0 and terminal fixed links. Inactive joints should remain at 0 unless the problem requires otherwise. The URDF uses RPY (roll-pitch-yaw) orientation following the standard extrinsic XYZ convention.