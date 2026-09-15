#!/usr/bin/env python3
"""Gradient-based trajectory optimization for drone recovery using Crazyflow.

Uses JAX automatic differentiation through Crazyflow's so_rpy (second-order RPY)
quadrotor dynamics to find optimal attitude commands that recover a displaced
drone to stable hover at a target position.

The so_rpy model directly parameterizes dynamics by attitude commands [roll, pitch,
yaw, thrust], bypassing the Mellinger PID controller. This ensures clean gradient
flow through the full simulation rollout.
"""

import os
os.environ["SCIPY_ARRAY_API"] = "1"

import json

import jax
import jax.numpy as jnp
import numpy as np

import crazyflow.sim.functional as F
from crazyflow.control import Control
from crazyflow.sim import Physics, Sim

# ---------------------------------------------------------------------------
# Problem specification
# ---------------------------------------------------------------------------
INIT_POS = jnp.array([0.05, -0.03, 1.2], dtype=jnp.float32)
INIT_VEL = jnp.array([-0.02, 0.01, -0.08], dtype=jnp.float32)
TARGET_POS = jnp.array([0.0, 0.0, 1.0], dtype=jnp.float32)
N_COMMANDS = 25
STEPS_PER_CMD = 10  # each command held for 10 physics steps (0.02 s)
N_ITERS = 2000
LR = 0.02

# ---------------------------------------------------------------------------
# Simulator setup
# ---------------------------------------------------------------------------
sim = Sim(
    n_worlds=1,
    n_drones=1,
    physics=Physics.so_rpy,
    control=Control.attitude,
    freq=500,
)

# Remove floor-clip from step pipeline so gradients flow through dynamics
# that pass below the floor plane (the clip is a non-differentiable clamp).
sim.step_pipeline = sim.step_pipeline[:-1]
step_fn = sim.build_step_fn()
sim.reset()

# ---------------------------------------------------------------------------
# Initial conditions
# ---------------------------------------------------------------------------
data0 = sim.data
data0 = data0.replace(
    states=data0.states.replace(
        pos=data0.states.pos.at[0, 0].set(INIT_POS),
        vel=data0.states.vel.at[0, 0].set(INIT_VEL),
    )
)

mass = float(data0.params.mass[0, 0, 0])
hover_thrust = mass * 9.81

# ---------------------------------------------------------------------------
# Command initialisation: hover thrust, zero attitude angles
# ---------------------------------------------------------------------------
commands = jnp.zeros((N_COMMANDS, 1, 1, 4), dtype=jnp.float32)
commands = commands.at[..., 3].set(hover_thrust)

# ---------------------------------------------------------------------------
# Loss functions
# ---------------------------------------------------------------------------

def running_loss(cmds, data):
    """Running cost with linearly-increasing weights plus a strong terminal bonus.

    Providing gradient signal at every intermediate step prevents vanishing
    gradients through the long unrolled simulation, while the terminal bonus
    ensures the optimizer focuses on the final-state accuracy.
    """
    total = jnp.float32(0.0)
    for i in range(N_COMMANDS):
        data = F.attitude_control(data, cmds[i])
        data = step_fn(data, STEPS_PER_CMD)
        pos = data.states.pos[0, 0]
        vel = data.states.vel[0, 0]
        w = (i + 1.0) / N_COMMANDS
        pos_err = jnp.sum((pos - TARGET_POS) ** 2)
        vel_err = jnp.sum(vel ** 2)
        total = total + w * (pos_err + 0.3 * vel_err)
    # Strong terminal bonus to ensure final state is well-optimized
    final_pos = data.states.pos[0, 0]
    final_vel = data.states.vel[0, 0]
    total = total + 10.0 * jnp.sum((final_pos - TARGET_POS) ** 2)
    total = total + 5.0 * jnp.sum(final_vel ** 2)
    return total


def terminal_loss(cmds, data):
    """Terminal loss for evaluation: position error + velocity penalty."""
    for i in range(N_COMMANDS):
        data = F.attitude_control(data, cmds[i])
        data = step_fn(data, STEPS_PER_CMD)
    pos = data.states.pos[0, 0]
    vel = data.states.vel[0, 0]
    return jnp.sum((pos - TARGET_POS) ** 2) + 0.5 * jnp.sum(vel ** 2)


def rollout(cmds, data):
    """Forward-simulate the trajectory with the given commands."""
    for i in range(N_COMMANDS):
        data = F.attitude_control(data, cmds[i])
        data = step_fn(data, STEPS_PER_CMD)
    return data


# Compile gradient and evaluation functions
grad_fn = jax.jit(jax.value_and_grad(running_loss))
eval_fn = jax.jit(terminal_loss)

# ---------------------------------------------------------------------------
# Optimisation (Adam)
# ---------------------------------------------------------------------------
initial_loss = float(eval_fn(commands, data0))
print(f"Initial loss: {initial_loss:.6f}")

m = jnp.zeros_like(commands)
v = jnp.zeros_like(commands)
beta1, beta2, eps = 0.9, 0.999, 1e-8

best_commands = commands
best_loss = initial_loss

for t in range(1, N_ITERS + 1):
    # Learning rate schedule: full LR for first 60%, 30% LR for last 40%
    lr = LR if t <= int(N_ITERS * 0.6) else LR * 0.3

    _, g = grad_fn(commands, data0)

    # Gradient clipping for stability
    g_norm = jnp.sqrt(jnp.sum(g ** 2) + 1e-12)
    g = jnp.where(g_norm > 50.0, g * 50.0 / g_norm, g)

    m = beta1 * m + (1.0 - beta1) * g
    v = beta2 * v + (1.0 - beta2) * g ** 2
    m_hat = m / (1.0 - beta1 ** t)
    v_hat = v / (1.0 - beta2 ** t)
    commands = commands - lr * m_hat / (jnp.sqrt(v_hat) + eps)

    if t % 200 == 0:
        cur_loss = float(eval_fn(commands, data0))
        print(f"  iter {t:>4d}  loss = {cur_loss:.6f}")
        if cur_loss < best_loss:
            best_loss = cur_loss
            best_commands = commands

# Use the best commands found during optimization
cur_loss = float(eval_fn(commands, data0))
if cur_loss < best_loss:
    best_loss = cur_loss
    best_commands = commands
commands = best_commands

# ---------------------------------------------------------------------------
# Final evaluation
# ---------------------------------------------------------------------------
final_loss = float(eval_fn(commands, data0))
final_data = jax.jit(rollout)(commands, data0)

final_pos = np.array(final_data.states.pos[0, 0]).tolist()
final_vel = np.array(final_data.states.vel[0, 0]).tolist()

pos_err = float(np.linalg.norm(np.array(final_pos) - np.array([0, 0, 1])))
vel_mag = float(np.linalg.norm(final_vel))

print(f"\nFinal loss:        {final_loss:.6f}")
print(f"Position error:    {pos_err:.4f} m")
print(f"Velocity magnitude:{vel_mag:.4f} m/s")
print(f"Final position:    {final_pos}")
print(f"Final velocity:    {final_vel}")

# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------
result = {
    "final_pos": final_pos,
    "final_vel": final_vel,
    "initial_loss": initial_loss,
    "final_loss": final_loss,
    "commands": np.array(commands[:, 0, 0, :]).tolist(),
    "n_iterations": N_ITERS,
}

with open("/app/result.json", "w") as f:
    json.dump(result, f, indent=2)

print("\nResults saved to /app/result.json")
