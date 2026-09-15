# Quadrotor First-Principles Dynamics

## State Vector

| Variable | Symbol | Frame | Shape |
|---|---|---|---|
| Position | p | world | (3,) |
| Orientation | q = [qx, qy, qz, qw] | world | (4,) — scalar-last quaternion |
| Linear velocity | v | world | (3,) |
| Angular velocity | ω | body | (3,) |
| Rotor velocities | w = [w₀,w₁,w₂,w₃] | — | (4,) RPM |

## Motor Layout (X-configuration)

Let `a = L / √2`.

| Motor | Position (body frame) | Spin |
|---|---|---|
| M0 | (+a, −a, 0) | CW |
| M1 | (−a, −a, 0) | CCW |
| M2 | (−a, +a, 0) | CW |
| M3 | (+a, +a, 0) | CCW |

## Motor Dynamics

    dw/dt = motor_tau × (cmd − w)

`motor_tau` is the time constant (1/s). `cmd` is the commanded RPM.

## Aerodynamic Forces & Torques (body frame)

    F_thrust = kf × (w₀² + w₁² + w₂² + w₃²)          along body +z

    τ_x = kf × a × (−w₀² − w₁² + w₂² + w₃²)          roll
    τ_y = kf × a × (−w₀² + w₁² + w₂² − w₃²)          pitch
    τ_z = km × (−w₀² + w₁² − w₂² + w₃²)              yaw (reaction torques)

## Translational Dynamics (world frame)

    m × a = R(q) · [0, 0, F_thrust]ᵀ  +  [0, 0, −m g]ᵀ  −  drag × v

`R(q)` is the rotation matrix corresponding to quaternion `q`.

## Rotational Dynamics (body frame)

    J · α = τ − ω × (J · ω)

where `J = diag(Ixx, Iyy, Izz)`.

## Euler Integration

    p_{t+1}  = p_t + v_t · dt
    v_{t+1}  = v_t + a_t · dt
    ω_{t+1}  = ω_t + α_t · dt
    q_{t+1}  = normalize( q_t ⊗ from_rotvec(ω_t · dt) )
    w_{t+1}  = w_t + motor_tau · (cmd_t − w_t) · dt

## Quaternion Conventions

Scalar-last: `q = [x, y, z, w]`.

Hamilton product `q₁ ⊗ q₂`:

    x = w₁x₂ + x₁w₂ + y₁z₂ − z₁y₂
    y = w₁y₂ − x₁z₂ + y₁w₂ + z₁x₂
    z = w₁z₂ + x₁y₂ − y₁x₂ + z₁w₂
    w = w₁w₂ − x₁x₂ − y₁y₂ − z₁z₂

Rotation vector → quaternion:

    angle = ‖rv‖
    axis  = rv / angle
    q = [axis · sin(angle/2),  cos(angle/2)]

Rotate vector `v` by quaternion `q`:

    v′ = (q ⊗ [v, 0] ⊗ q*)[:3]       where q* = [−qx, −qy, −qz, qw]

## Parameters

### Unknown (to be identified)

| Symbol | Units | Description |
|---|---|---|
| Ixx | kg·m² | Roll moment of inertia |
| Iyy | kg·m² | Pitch moment of inertia |
| Izz | kg·m² | Yaw moment of inertia |
| kf | N/RPM² | Thrust coefficient |
| km | Nm/RPM² | Reaction-torque coefficient |
| drag | kg/s | Linear aerodynamic drag |
| motor_tau | 1/s | First-order motor time constant |

### Known (given in config.json)

| Symbol | Value | Units |
|---|---|---|
| mass | 0.033 | kg |
| L | 0.046 | m |
| g | 9.81 | m/s² |
| dt | 0.002 | s |
