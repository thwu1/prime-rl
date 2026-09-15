"""Quadrotor simulator debugging and system identification.

Step 1: Diagnose and fix the quaternion convention bug in /app/simulator.py
        (quat_to_rotmat unpacks w,x,y,z but receives scalar-last x,y,z,w).
Step 2: Implement correct differentiable dynamics in JAX per dynamics_spec.md.
Step 3: Optimize mass, kf, kt via gradient-based system identification.
"""

import json
import os

import jax
import jax.numpy as jnp
import numpy as np

# Enable float64 for numerical precision
jax.config.update("jax_enable_x64", True)

# ---------------------------------------------------------------------------
# Step 1: Diagnose the simulator bug
# ---------------------------------------------------------------------------
# The provided /app/simulator.py has a quaternion convention mismatch:
#   quat_to_rotmat() unpacks as `w, x, y, z = q` (scalar-first)
#   but the data and spec use scalar-last [x, y, z, w].
# This causes the rotation matrix to be completely wrong for non-identity
# quaternions, leading to rapid trajectory divergence.
# We implement the correct dynamics below.

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
data = np.load("/app/data/flight_data.npz")
with open("/app/data/known_params.json") as f:
    known = json.load(f)

positions = jnp.array(data["positions"], dtype=jnp.float64)
velocities = jnp.array(data["velocities"], dtype=jnp.float64)
quaternions = jnp.array(data["quaternions"], dtype=jnp.float64)
angular_velocities = jnp.array(data["angular_velocities"], dtype=jnp.float64)
motor_rpms = jnp.array(data["motor_rpms"], dtype=jnp.float64)

ARM_LENGTH = known["arm_length"]
IXX = known["Ixx"]
IYY = known["Iyy"]
IZZ = known["Izz"]
G = known["g"]
DT = float(data["timestamps"][1] - data["timestamps"][0])

# Build training pairs for one-step prediction
states_t = jnp.concatenate(
    [positions[:-1], velocities[:-1], quaternions[:-1], angular_velocities[:-1]],
    axis=-1,
)  # (1000, 13)

states_tp1 = jnp.concatenate(
    [positions[1:], velocities[1:], quaternions[1:], angular_velocities[1:]],
    axis=-1,
)  # (1000, 13)


# ---------------------------------------------------------------------------
# Step 2: Correct dynamics implementation in JAX
# ---------------------------------------------------------------------------
def quat_multiply(q1, q2):
    """Hamilton quaternion product, scalar-last [x,y,z,w]."""
    x1, y1, z1, w1 = q1[0], q1[1], q1[2], q1[3]
    x2, y2, z2, w2 = q2[0], q2[1], q2[2], q2[3]
    return jnp.array([
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
    ])


def quat_to_rotmat(q):
    """Rotation matrix from scalar-last quaternion [x,y,z,w].

    CORRECT implementation: unpack as x, y, z, w (not w, x, y, z as in
    the buggy simulator.py).
    """
    x, y, z, w = q[0], q[1], q[2], q[3]
    return jnp.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def dynamics_step(state, rpms, log_params):
    """One forward Euler step of quadrotor dynamics.

    Args:
        state: 13-element array [pos(3), vel(3), quat(4), omega(3)]
        rpms: 4-element motor RPM array
        log_params: 3-element array [log(mass), log(kf), log(kt)]

    Returns:
        Next state as a 13-element array.
    """
    pos = state[:3]
    vel = state[3:6]
    quat = state[6:10]
    omega = state[10:13]

    mass = jnp.exp(log_params[0])
    kf = jnp.exp(log_params[1])
    kt = jnp.exp(log_params[2])

    # Per-motor thrusts
    rpm_sq = rpms ** 2
    f = kf * rpm_sq

    # Collective force and torques (plus-configuration mixing)
    F_total = jnp.sum(f)
    tau_x = ARM_LENGTH * (f[3] - f[1])
    tau_y = ARM_LENGTH * (f[0] - f[2])
    tau_z = kt * (-rpm_sq[0] + rpm_sq[1] - rpm_sq[2] + rpm_sq[3])

    # Translational dynamics
    R = quat_to_rotmat(quat)
    F_body = jnp.array([0.0, 0.0, F_total])
    acc = R @ F_body / mass + jnp.array([0.0, 0.0, -G])

    # Rotational dynamics (Euler's rigid body equation)
    J_diag = jnp.array([IXX, IYY, IZZ])
    J_inv_diag = 1.0 / J_diag
    tau = jnp.array([tau_x, tau_y, tau_z])
    J_omega = J_diag * omega
    ang_acc = J_inv_diag * (tau - jnp.cross(omega, J_omega))

    # Quaternion derivative
    omega_q = jnp.array([omega[0], omega[1], omega[2], 0.0])
    q_dot = 0.5 * quat_multiply(quat, omega_q)

    # Forward Euler integration
    pos_new = pos + vel * DT
    vel_new = vel + acc * DT
    omega_new = omega + ang_acc * DT
    quat_new = quat + q_dot * DT
    quat_new = quat_new / jnp.linalg.norm(quat_new)

    return jnp.concatenate([pos_new, vel_new, quat_new, omega_new])


# ---------------------------------------------------------------------------
# Step 3: Loss function and optimization
# ---------------------------------------------------------------------------
def loss_fn(log_params):
    """Mean squared one-step prediction error across all timesteps."""
    pred_fn = lambda st, rpm: dynamics_step(st, rpm, log_params)
    preds = jax.vmap(pred_fn)(states_t, motor_rpms)

    vel_err = jnp.mean((preds[:, 3:6] - states_tp1[:, 3:6]) ** 2)
    omega_err = jnp.mean((preds[:, 10:13] - states_tp1[:, 10:13]) ** 2)
    pos_err = jnp.mean((preds[:, :3] - states_tp1[:, :3]) ** 2)
    quat_err = jnp.mean((preds[:, 6:10] - states_tp1[:, 6:10]) ** 2)

    return vel_err + omega_err + pos_err + quat_err


print("Compiling loss and gradient functions...")
loss_and_grad = jax.jit(jax.value_and_grad(loss_fn))

# Initial guess: use the (wrong) values from sim_params.json as starting point
with open("/app/data/sim_params.json") as f:
    init_params = json.load(f)

log_params = jnp.array([
    jnp.log(init_params["mass"]),
    jnp.log(init_params["kf"]),
    jnp.log(init_params["kt"]),
], dtype=jnp.float64)

# Warm up JIT
print("JIT compiling (first call)...")
loss_val, grad = loss_and_grad(log_params)
print(f"Initial loss: {float(loss_val):.4e}")

# Adam optimizer state
m = jnp.zeros_like(log_params)
v = jnp.zeros_like(log_params)
beta1, beta2, eps = 0.9, 0.999, 1e-8

# Phase 1: coarse optimization
lr = 0.01
n_steps_phase1 = 3000
print(f"\nPhase 1: {n_steps_phase1} steps at lr={lr}")

for i in range(n_steps_phase1):
    loss_val, grad = loss_and_grad(log_params)

    if not jnp.isfinite(loss_val):
        print(f"WARNING: NaN/Inf loss at step {i}, stopping early.")
        break

    step = i + 1
    m = beta1 * m + (1 - beta1) * grad
    v = beta2 * v + (1 - beta2) * grad ** 2
    m_hat = m / (1 - beta1 ** step)
    v_hat = v / (1 - beta2 ** step)
    log_params = log_params - lr * m_hat / (jnp.sqrt(v_hat) + eps)

    if i % 500 == 0:
        p = jnp.exp(log_params)
        print(
            f"  step {i:4d} | loss={float(loss_val):.4e} | "
            f"mass={float(p[0]):.5f} | kf={float(p[1]):.3e} | kt={float(p[2]):.3e}"
        )

# Phase 2: refinement
lr = 0.001
n_steps_phase2 = 2000
print(f"\nPhase 2: {n_steps_phase2} steps at lr={lr}")

for i in range(n_steps_phase2):
    loss_val, grad = loss_and_grad(log_params)
    step = n_steps_phase1 + i + 1
    m = beta1 * m + (1 - beta1) * grad
    v = beta2 * v + (1 - beta2) * grad ** 2
    m_hat = m / (1 - beta1 ** step)
    v_hat = v / (1 - beta2 ** step)
    log_params = log_params - lr * m_hat / (jnp.sqrt(v_hat) + eps)

# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------
params = jnp.exp(log_params)
result = {
    "mass": float(params[0]),
    "kf": float(params[1]),
    "kt": float(params[2]),
}

os.makedirs("/app/results", exist_ok=True)
with open("/app/results/params.json", "w") as f:
    json.dump(result, f, indent=2)

final_loss = float(loss_and_grad(log_params)[0])
print(f"\nFinal loss: {final_loss:.4e}")
print(f"Recovered parameters:")
print(f"  mass = {result['mass']:.6f}")
print(f"  kf   = {result['kf']:.4e}")
print(f"  kt   = {result['kt']:.4e}")
print(f"\nResults saved to /app/results/params.json")
