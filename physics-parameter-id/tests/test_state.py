"""Verify physics parameter identification results by re-simulation.

No ground-truth parameter values are stored here. Verification works by
re-simulating each experiment with the agent's identified parameters and
checking that the resulting trajectory matches the original observations.
"""


import json
import math
import os
import pytest
import pybullet as p
import pybullet_data

DT = 1.0 / 240.0
RECORD_EVERY = 10
RMSE_THRESHOLD = 0.01


@pytest.fixture(scope="module")
def pybullet_env():
    """Connect to PyBullet once for the entire test module."""
    client = p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    yield client
    p.disconnect()


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def observations():
    with open("/app/observations.json") as f:
        return json.load(f)


def rmse(a, b):
    """Compute root mean squared error between two sequences."""
    assert len(a) == len(b), f"Length mismatch: {len(a)} vs {len(b)}"
    mse_val = sum((x - y) ** 2 for x, y in zip(a, b)) / len(a)
    return math.sqrt(mse_val)


# ===================== Simulation Functions =====================
# These MUST exactly match the data generation code.

def simulate_bouncing_sphere(restitution):
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


def simulate_damped_pendulum(damping_coefficient):
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
        torque = -damping_coefficient * js[1]
        p.setJointMotorControl2(pendulum, 0, p.TORQUE_CONTROL, force=torque)
        p.stepSimulation()
        if (i + 1) % RECORD_EVERY == 0:
            js = p.getJointState(pendulum, 0)
            angles.append(js[0])
    return angles


# ===================== Tests =====================

class TestResultsFormat:
    """Validate results.json structure and value ranges."""

    def test_file_exists(self):
        assert os.path.exists("/app/results.json"), \
            "/app/results.json not found"

    def test_valid_json(self):
        with open("/app/results.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), "results.json must contain a JSON object"

    def test_has_required_keys(self, results):
        for key in ["restitution", "lateral_friction", "joint_damping"]:
            assert key in results, f"Missing key: {key}"
            assert isinstance(results[key], (int, float)), \
                f"{key} must be a number, got {type(results[key])}"

    def test_values_physically_valid(self, results):
        assert 0 < results["restitution"] <= 1.0, \
            f"restitution={results['restitution']} must be in (0, 1]"
        assert 0 < results["lateral_friction"] < 5.0, \
            f"lateral_friction={results['lateral_friction']} out of valid range"
        assert 0 < results["joint_damping"] < 5.0, \
            f"joint_damping={results['joint_damping']} out of valid range"


class TestTrajectoryMatch:
    """Re-simulate with identified parameters, verify trajectory RMSE."""

    def test_bouncing_sphere_trajectory(self, pybullet_env, results, observations):
        obs_z = [pt["z"] for pt in observations["bouncing_sphere"]]
        sim_z = simulate_bouncing_sphere(results["restitution"])
        error = rmse(obs_z, sim_z)
        assert error < RMSE_THRESHOLD, \
            f"Bouncing sphere RMSE = {error:.6f}, must be < {RMSE_THRESHOLD}"

    def test_sliding_block_trajectory(self, pybullet_env, results, observations):
        obs_x = [pt["x"] for pt in observations["sliding_block"]]
        sim_x = simulate_sliding_block(results["lateral_friction"])
        error = rmse(obs_x, sim_x)
        assert error < RMSE_THRESHOLD, \
            f"Sliding block RMSE = {error:.6f}, must be < {RMSE_THRESHOLD}"

    def test_damped_pendulum_trajectory(self, pybullet_env, results, observations):
        obs_a = [pt["angle"] for pt in observations["damped_pendulum"]]
        sim_a = simulate_damped_pendulum(results["joint_damping"])
        error = rmse(obs_a, sim_a)
        assert error < RMSE_THRESHOLD, \
            f"Damped pendulum RMSE = {error:.6f}, must be < {RMSE_THRESHOLD}"
