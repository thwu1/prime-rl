#!/usr/bin/env python3
"""Solver for physics parameter identification task.

Reads observation data from /app/observations.json, builds matching PyBullet
simulations for each experiment, and uses parameter optimization to
identify the unknown physics parameters by minimizing trajectory MSE.

For the bouncing sphere (non-smooth MSE landscape due to discrete contacts),
a dense grid search is used instead of gradient-based methods.
"""


import json
import math
import numpy as np
import pybullet as p
import pybullet_data
from scipy.optimize import minimize_scalar

DT = 1.0 / 240.0
RECORD_EVERY = 10


def simulate_bouncing_sphere(restitution):
    """Simulate bouncing sphere with given restitution, return z-trajectory."""
    p.resetSimulation()
    p.setGravity(0, 0, -9.81)
    p.setTimeStep(DT)
    p.setPhysicsEngineParameter(numSolverIterations=50)

    plane = p.loadURDF("plane.urdf")
    p.changeDynamics(plane, -1, restitution=restitution)

    sphere_col = p.createCollisionShape(p.GEOM_SPHERE, radius=0.05)
    sphere = p.createMultiBody(baseMass=1.0, baseCollisionShapeIndex=sphere_col,
                               basePosition=[0, 0, 2.0])
    p.changeDynamics(sphere, -1, restitution=restitution,
                     linearDamping=0, angularDamping=0)

    zs = []
    for i in range(720):
        p.stepSimulation()
        if (i + 1) % RECORD_EVERY == 0:
            pos, _ = p.getBasePositionAndOrientation(sphere)
            zs.append(pos[2])
    return zs


def simulate_sliding_block(lateral_friction):
    """Simulate sliding block with given friction, return x-trajectory."""
    p.resetSimulation()
    p.setGravity(0, 0, -9.81)
    p.setTimeStep(DT)
    p.setPhysicsEngineParameter(numSolverIterations=50)

    plane = p.loadURDF("plane.urdf")
    p.changeDynamics(plane, -1, lateralFriction=lateral_friction, restitution=0.0)

    box_col = p.createCollisionShape(p.GEOM_BOX, halfExtents=[0.05, 0.05, 0.05])
    box = p.createMultiBody(baseMass=1.0, baseCollisionShapeIndex=box_col,
                            basePosition=[0, 0, 0.05])
    p.changeDynamics(box, -1, lateralFriction=lateral_friction, restitution=0.0,
                     linearDamping=0, angularDamping=0,
                     rollingFriction=0, spinningFriction=0)

    for _ in range(120):
        p.stepSimulation()

    p.resetBaseVelocity(box, linearVelocity=[3.0, 0, 0])

    xs = []
    for i in range(480):
        p.stepSimulation()
        if (i + 1) % RECORD_EVERY == 0:
            pos, _ = p.getBasePositionAndOrientation(box)
            xs.append(pos[0])
    return xs


def simulate_damped_pendulum(damping_coeff):
    """Simulate damped pendulum with given damping coefficient, return angle trajectory."""
    p.resetSimulation()
    p.setGravity(0, 0, -9.81)
    p.setTimeStep(DT)
    p.setPhysicsEngineParameter(numSolverIterations=50)

    link_length = 0.5
    link_mass = 0.5
    link_col = p.createCollisionShape(p.GEOM_BOX,
                                      halfExtents=[0.02, 0.02, link_length / 2])

    pendulum = p.createMultiBody(
        baseMass=0,
        baseCollisionShapeIndex=-1,
        basePosition=[0, 0, 2.0],
        linkMasses=[link_mass],
        linkCollisionShapeIndices=[link_col],
        linkVisualShapeIndices=[-1],
        linkPositions=[[0, 0, -link_length / 2]],
        linkOrientations=[[0, 0, 0, 1]],
        linkInertialFramePositions=[[0, 0, 0]],
        linkInertialFrameOrientations=[[0, 0, 0, 1]],
        linkParentIndices=[0],
        linkJointTypes=[p.JOINT_REVOLUTE],
        linkJointAxis=[[0, 1, 0]]
    )

    p.changeDynamics(pendulum, 0, linearDamping=0, angularDamping=0)
    p.setJointMotorControl2(pendulum, 0, p.VELOCITY_CONTROL, force=0)
    p.resetJointState(pendulum, 0, math.pi / 3, 0)

    angles = []
    for i in range(1440):
        js = p.getJointState(pendulum, 0)
        torque = -damping_coeff * js[1]
        p.setJointMotorControl2(pendulum, 0, p.TORQUE_CONTROL, force=torque)
        p.stepSimulation()
        if (i + 1) % RECORD_EVERY == 0:
            js = p.getJointState(pendulum, 0)
            angles.append(js[0])
    return angles


def mse(sim, obs):
    """Compute mean squared error between two lists."""
    return sum((s - o) ** 2 for s, o in zip(sim, obs)) / len(obs)


def grid_search_1d(sim_func, obs_values, lo, hi, coarse_n=500, fine_n=200, fine_radius=0.02):
    """Two-pass grid search for 1D parameter optimization.

    Robust against non-smooth/discontinuous MSE landscapes (e.g. contact events).
    """
    # Coarse pass
    coarse_grid = np.linspace(lo, hi, coarse_n)
    coarse_mse = [mse(sim_func(v), obs_values) for v in coarse_grid]
    best_idx = int(np.argmin(coarse_mse))
    best_val = coarse_grid[best_idx]

    # Fine pass around the best coarse point
    fine_lo = max(lo, best_val - fine_radius)
    fine_hi = min(hi, best_val + fine_radius)
    fine_grid = np.linspace(fine_lo, fine_hi, fine_n)
    fine_mse_vals = [mse(sim_func(v), obs_values) for v in fine_grid]
    best_fine_idx = int(np.argmin(fine_mse_vals))

    return fine_grid[best_fine_idx], fine_mse_vals[best_fine_idx]


def main():
    with open("/app/observations.json") as f:
        obs = json.load(f)

    p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())

    results = {}

    # --- Experiment 1: Identify restitution ---
    # Use grid search because the bouncing sphere MSE landscape is
    # non-smooth (discrete contact events create discontinuities).
    print("Optimizing restitution (grid search)...")
    obs_z = [pt["z"] for pt in obs["bouncing_sphere"]]
    best_e, best_mse = grid_search_1d(simulate_bouncing_sphere, obs_z,
                                       lo=0.01, hi=0.99,
                                       coarse_n=500, fine_n=200, fine_radius=0.02)
    results["restitution"] = round(best_e, 6)
    print(f"  restitution = {best_e:.6f}, MSE = {best_mse:.2e}")

    # --- Experiment 2: Identify lateral friction ---
    print("Optimizing lateral friction...")
    obs_x = [pt["x"] for pt in obs["sliding_block"]]

    res2 = minimize_scalar(
        lambda f: mse(simulate_sliding_block(f), obs_x),
        bounds=(0.01, 2.0), method="bounded",
        options={"xatol": 1e-6, "maxiter": 100}
    )
    results["lateral_friction"] = round(res2.x, 6)
    print(f"  lateral_friction = {res2.x:.6f}, MSE = {res2.fun:.2e}")

    # --- Experiment 3: Identify damping coefficient ---
    print("Optimizing damping coefficient...")
    obs_a = [pt["angle"] for pt in obs["damped_pendulum"]]

    res3 = minimize_scalar(
        lambda d: mse(simulate_damped_pendulum(d), obs_a),
        bounds=(0.001, 2.0), method="bounded",
        options={"xatol": 1e-6, "maxiter": 100}
    )
    results["joint_damping"] = round(res3.x, 6)
    print(f"  joint_damping = {res3.x:.6f}, MSE = {res3.fun:.2e}")

    p.disconnect()

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to /app/results.json:")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
