
import json
import os

import numpy as np


# ---------------------------------------------------------------------------
# Problem constants (must match instruction.md)
# ---------------------------------------------------------------------------
INIT_POS = [0.05, -0.03, 1.2]
INIT_VEL = [-0.02, 0.01, -0.08]
TARGET_POS = [0.0, 0.0, 1.0]
N_COMMANDS = 25
FREQ = 500
STEPS_PER_CMD = 10
POS_TOL = 0.15   # metres
VEL_TOL = 0.5    # m/s


# ---------------------------------------------------------------------------
# Structural tests (no simulation import needed)
# ---------------------------------------------------------------------------

def test_optimize_script_exists():
    assert os.path.exists("/app/optimize.py"), "optimize.py not found at /app/"


def test_result_file_exists():
    assert os.path.exists("/app/result.json"), "result.json not found at /app/"


def test_result_structure():
    with open("/app/result.json") as f:
        result = json.load(f)
    required = [
        "final_pos", "final_vel", "initial_loss",
        "final_loss", "commands", "n_iterations",
    ]
    for key in required:
        assert key in result, f"Missing key in result.json: {key}"
    assert isinstance(result["final_pos"], list) and len(result["final_pos"]) == 3
    assert isinstance(result["final_vel"], list) and len(result["final_vel"]) == 3
    assert isinstance(result["initial_loss"], (int, float))
    assert isinstance(result["final_loss"], (int, float))
    assert isinstance(result["n_iterations"], int)


def test_commands_shape():
    with open("/app/result.json") as f:
        result = json.load(f)
    cmds = np.array(result["commands"])
    assert cmds.shape == (N_COMMANDS, 4), (
        f"Expected commands shape ({N_COMMANDS}, 4), got {cmds.shape}"
    )


def test_loss_decreased():
    with open("/app/result.json") as f:
        result = json.load(f)
    assert result["final_loss"] < result["initial_loss"], (
        f"Loss must decrease: {result['initial_loss']:.6f} -> {result['final_loss']:.6f}"
    )


def test_uses_autodiff():
    with open("/app/optimize.py") as f:
        src = f.read()
    grad_patterns = [
        "jax.grad", "jax.value_and_grad",
        "from jax import grad", "from jax import value_and_grad",
    ]
    assert any(p in src for p in grad_patterns), (
        "optimize.py must use automatic differentiation through the simulator"
    )


# ---------------------------------------------------------------------------
# Trajectory re-simulation test
# ---------------------------------------------------------------------------

def test_trajectory_accuracy():
    """Re-simulate the optimized trajectory and verify accuracy."""
    os.environ["SCIPY_ARRAY_API"] = "1"

    import jax.numpy as jnp
    import crazyflow.sim.functional as F
    from crazyflow.sim import Sim, Physics
    from crazyflow.control import Control

    with open("/app/result.json") as f:
        result = json.load(f)

    commands = jnp.array(result["commands"], dtype=jnp.float32)
    assert commands.shape == (N_COMMANDS, 4)

    # Build identical simulation (so_rpy physics, attitude control)
    sim = Sim(
        n_worlds=1, n_drones=1,
        physics=Physics.so_rpy,
        control=Control.attitude,
        freq=FREQ,
    )
    sim.step_pipeline = sim.step_pipeline[:-1]  # remove floor clip
    step_fn = sim.build_step_fn()
    sim.reset()

    # Set initial conditions
    data = sim.data
    data = data.replace(
        states=data.states.replace(
            pos=data.states.pos.at[0, 0].set(jnp.array(INIT_POS, dtype=jnp.float32)),
            vel=data.states.vel.at[0, 0].set(jnp.array(INIT_VEL, dtype=jnp.float32)),
        )
    )

    # Roll out with the optimised commands
    for i in range(N_COMMANDS):
        cmd_i = commands[i].reshape(1, 1, 4)
        data = F.attitude_control(data, cmd_i)
        data = step_fn(data, STEPS_PER_CMD)

    final_pos = np.array(data.states.pos[0, 0])
    final_vel = np.array(data.states.vel[0, 0])

    target = np.array(TARGET_POS)
    pos_error = float(np.linalg.norm(final_pos - target))
    vel_mag = float(np.linalg.norm(final_vel))

    assert pos_error < POS_TOL, (
        f"Position error {pos_error:.4f} m exceeds tolerance {POS_TOL} m "
        f"(final_pos={final_pos.tolist()})"
    )
    assert vel_mag < VEL_TOL, (
        f"Velocity magnitude {vel_mag:.4f} m/s exceeds tolerance {VEL_TOL} m/s "
        f"(final_vel={final_vel.tolist()})"
    )
