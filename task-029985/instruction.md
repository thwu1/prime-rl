A KUKA youBot mobile manipulator must autonomously pick up a cube from an initial pose and place it at a goal pose. The `modern_robotics` Python library (v1.1.1) is installed. The scenario configuration (initial/goal cube poses, initial robot state, controller gains, timestep) is at `/app/config.json`.

## youBot Description

The youBot has a four-mecanum-wheel omnidirectional base and a 5R robot arm.

**Base geometry**: forward-backward wheel distance 2l = 0.47m, side-to-side distance 2w = 0.3m, wheel radius r = 0.0475m. Chassis frame {b} height z = 0.0963m above the floor.

**Fixed transforms**:
- Tb0 (chassis {b} to arm base {0}) = [[1,0,0,0.1662],[0,1,0,0],[0,0,1,0.0026],[0,0,0,1]]
- M0e (arm zero-config end-effector {e} relative to {0}) = [[1,0,0,0.033],[0,1,0,0],[0,0,1,0.6546],[0,0,0,1]]

**Body screw axes** (columns of 6×5 Blist):
B1=(0,0,1,0,0.033,0), B2=(0,-1,0,-0.5076,0,0), B3=(0,-1,0,-0.3526,0,0), B4=(0,-1,0,-0.2176,0,0), B5=(0,0,1,0,0,0)

The 13-vector configuration is `(phi, x, y, J1, J2, J3, J4, J5, W1, W2, W3, W4, gripper_state)`. The cube is 5cm on a side; its body frame is at center height z=0.025m.

## Task

The robot's initial configuration (specified in `config.json`) has both orientation and position error relative to the desired end-effector reference trajectory start. Your simulation must drive the robot to correct this error, approach the cube, grasp it, transport it, and release it at the goal location.

The config file also provides the initial end-effector reference pose `Tse_initial`, grasp and standoff transforms relative to the cube frame (`Tce_grasp`, `Tce_standoff`), controller gains (`Kp`, `Ki`), timestep `dt`, and speed limit `max_speed`.

## Required Output

Produce these files using the parameters from `/app/config.json`:

- `/app/output/trajectory.csv` — each row: 13 comma-separated values `(phi, x, y, J1-J5, W1-W4, gripper_state)`
- `/app/output/error_log.csv` — each row: 6 comma-separated values (end-effector twist error components)

The trajectory must show the full pick-and-place motion: gripper starts open (0), closes (1) when grasping the cube, then reopens (0) when placing it. The first row of the trajectory must match the `robot_initial` configuration from the config. The controller must reduce the tracking error over time. The trajectory should contain between 1000 and 6000 rows at the configured timestep.