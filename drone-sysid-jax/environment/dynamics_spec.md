# Quadrotor First-Principles Dynamics Model

## State Representation

The quadrotor state is a 13-dimensional vector:

| Component | Symbol | Dim | Frame | Units |
|---|---|---|---|---|
| Position | pos | 3 | World | m |
| Linear velocity | vel | 3 | World | m/s |
| Orientation | quat | 4 | — | [x, y, z, w] scalar-last |
| Angular velocity | omega | 3 | Body | rad/s |

## Motor Layout (Plus Configuration)

Four motors in a + pattern, each at distance L (arm length) from the center of mass:

```
        Motor 0 (+x, front, CCW)
              |
Motor 3 ------+------ Motor 1
 (+y, left,   |    (-y, right,
   CW)        |       CW)
              |
        Motor 2 (-x, rear, CCW)
```

Body frame: x forward, y left, z up (right-hand rule).

## Per-Motor Thrust

Each motor produces thrust along the body z-axis proportional to RPM squared:

    f_i = kf * rpm_i^2

where kf is the thrust coefficient (N / RPM^2).

## Collective Force and Body-Frame Torques

    F_total = f_0 + f_1 + f_2 + f_3

    tau_x = L * (f_3 - f_1)                                   (roll torque)
    tau_y = L * (f_0 - f_2)                                   (pitch torque)
    tau_z = kt * (-rpm_0^2 + rpm_1^2 - rpm_2^2 + rpm_3^2)     (yaw reactive torque)

where L is the arm length and kt is the torque coefficient (N*m / RPM^2).

## Translational Dynamics

The collective thrust acts along the body z-axis. Rotate it to the world frame using the rotation matrix derived from the quaternion:

    R = rotation_matrix(quat)
    acceleration = R @ [0, 0, F_total]^T / mass + [0, 0, -g]^T

## Rotational Dynamics (Euler's Rigid Body Equation)

    J = diag(Ixx, Iyy, Izz)
    tau = [tau_x, tau_y, tau_z]^T
    angular_acceleration = J^{-1} @ (tau - omega x (J @ omega))

where x denotes the cross product.

## Quaternion Derivative

The orientation quaternion evolves as:

    q_dot = 0.5 * q (x) [omega_x, omega_y, omega_z, 0]

where (x) is Hamilton quaternion multiplication using scalar-last convention [x, y, z, w]:

    (q1 (x) q2)_x = w1*x2 + x1*w2 + y1*z2 - z1*y2
    (q1 (x) q2)_y = w1*y2 - x1*z2 + y1*w2 + z1*x2
    (q1 (x) q2)_z = w1*z2 + x1*y2 - y1*x2 + z1*w2
    (q1 (x) q2)_w = w1*w2 - x1*x2 - y1*y2 - z1*z2

## Rotation Matrix from Quaternion

For q = [x, y, z, w]:

    R = | 1-2(y^2+z^2)   2(xy-zw)       2(xz+yw)     |
        | 2(xy+zw)       1-2(x^2+z^2)   2(yz-xw)     |
        | 2(xz-yw)       2(yz+xw)       1-2(x^2+y^2) |

## Forward Euler Integration

    pos(t+dt) = pos(t) + vel(t) * dt
    vel(t+dt) = vel(t) + acceleration(t) * dt
    omega(t+dt) = omega(t) + angular_acceleration(t) * dt
    q(t+dt) = normalize( q(t) + q_dot(t) * dt )

where normalize(q) = q / ||q||.

## Data Format

`/app/data/flight_data.npz` contains arrays:

| Key | Shape | Description |
|---|---|---|
| timestamps | (1001,) | Time in seconds |
| positions | (1001, 3) | World-frame [x, y, z] |
| velocities | (1001, 3) | World-frame [vx, vy, vz] |
| quaternions | (1001, 4) | Scalar-last [qx, qy, qz, qw] |
| angular_velocities | (1001, 3) | Body-frame [wx, wy, wz] |
| motor_rpms | (1000, 4) | Motor speeds [rpm0, rpm1, rpm2, rpm3] |

State arrays have 1001 entries (initial state + 1000 integration steps).
Motor commands have 1000 entries. `motor_rpms[t]` is the command applied between `states[t]` and `states[t+1]`.

Simulation frequency: 500 Hz (dt = 0.002 s). Total duration: 2.0 s.
