#!/usr/bin/env python3
"""Generate observation data for physics parameter identification task.
This script runs during Docker build and is NOT included in the final image."""

import pybullet as p
import pybullet_data
import json
import math

# Ground truth parameters (the unknowns the agent must identify)
RESTITUTION = 0.72
LATERAL_FRICTION = 0.38
JOINT_DAMPING = 0.12

DT = 1.0 / 240.0
RECORD_EVERY = 10


def main():
    p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())

    observations = {}
    config = {}

    # ========== Experiment 1: Bouncing Sphere ==========
    p.resetSimulation()
    p.setGravity(0, 0, -9.81)
    p.setTimeStep(DT)
    p.setPhysicsEngineParameter(numSolverIterations=50)

    plane = p.loadURDF("plane.urdf")
    p.changeDynamics(plane, -1, restitution=RESTITUTION)

    sphere_col = p.createCollisionShape(p.GEOM_SPHERE, radius=0.05)
    sphere = p.createMultiBody(baseMass=1.0, baseCollisionShapeIndex=sphere_col,
                               basePosition=[0, 0, 2.0])
    p.changeDynamics(sphere, -1, restitution=RESTITUTION,
                     linearDamping=0, angularDamping=0)

    total_steps_1 = 720
    traj1 = []
    for i in range(total_steps_1):
        p.stepSimulation()
        if (i + 1) % RECORD_EVERY == 0:
            pos, _ = p.getBasePositionAndOrientation(sphere)
            traj1.append({"step": i + 1, "z": round(pos[2], 8)})

    observations["bouncing_sphere"] = traj1
    config["bouncing_sphere"] = {
        "description": "Sphere dropped from rest onto an infinite ground plane. Identify the coefficient of restitution.",
        "setup": {
            "sphere_mass": 1.0,
            "sphere_radius": 0.05,
            "sphere_initial_position": [0, 0, 2.0],
            "sphere_initial_velocity": [0, 0, 0],
            "sphere_linearDamping": 0,
            "sphere_angularDamping": 0,
            "ground_plane": "plane.urdf from pybullet_data",
            "gravity": [0, 0, -9.81],
            "timestep": DT,
            "solver_iterations": 50,
            "record_every_n_steps": RECORD_EVERY,
            "total_steps": total_steps_1
        },
        "unknowns": ["restitution"],
        "notes": "The restitution value is identical for both the sphere and the ground plane. Use pybullet_data.getDataPath() to locate plane.urdf."
    }

    # ========== Experiment 2: Sliding Block ==========
    p.resetSimulation()
    p.setGravity(0, 0, -9.81)
    p.setTimeStep(DT)
    p.setPhysicsEngineParameter(numSolverIterations=50)

    plane = p.loadURDF("plane.urdf")
    p.changeDynamics(plane, -1, lateralFriction=LATERAL_FRICTION, restitution=0.0)

    box_col = p.createCollisionShape(p.GEOM_BOX, halfExtents=[0.05, 0.05, 0.05])
    box = p.createMultiBody(baseMass=1.0, baseCollisionShapeIndex=box_col,
                            basePosition=[0, 0, 0.05])
    p.changeDynamics(box, -1, lateralFriction=LATERAL_FRICTION, restitution=0.0,
                     linearDamping=0, angularDamping=0,
                     rollingFriction=0, spinningFriction=0)

    for _ in range(120):
        p.stepSimulation()

    p.resetBaseVelocity(box, linearVelocity=[3.0, 0, 0])

    total_steps_2 = 480
    traj2 = []
    for i in range(total_steps_2):
        p.stepSimulation()
        if (i + 1) % RECORD_EVERY == 0:
            pos, _ = p.getBasePositionAndOrientation(box)
            vel, _ = p.getBaseVelocity(box)
            traj2.append({"step": i + 1, "x": round(pos[0], 8), "vx": round(vel[0], 8)})

    observations["sliding_block"] = traj2
    config["sliding_block"] = {
        "description": "Box placed on ground plane at rest, settled for 120 simulation steps, then given an initial x-velocity. Identify the lateral friction coefficient.",
        "setup": {
            "box_mass": 1.0,
            "box_half_extents": [0.05, 0.05, 0.05],
            "box_initial_position": [0, 0, 0.05],
            "box_linearDamping": 0,
            "box_angularDamping": 0,
            "box_rollingFriction": 0,
            "box_spinningFriction": 0,
            "box_restitution": 0.0,
            "ground_plane": "plane.urdf from pybullet_data",
            "ground_restitution": 0.0,
            "settle_steps": 120,
            "initial_velocity_after_settle": [3.0, 0, 0],
            "gravity": [0, 0, -9.81],
            "timestep": DT,
            "solver_iterations": 50,
            "record_every_n_steps": RECORD_EVERY,
            "total_steps": total_steps_2
        },
        "unknowns": ["lateral_friction"],
        "notes": "The lateral friction value is identical for both the box and the ground plane. Velocity is applied via resetBaseVelocity after the settling phase."
    }

    # ========== Experiment 3: Damped Pendulum ==========
    p.resetSimulation()
    p.setGravity(0, 0, -9.81)
    p.setTimeStep(DT)
    p.setPhysicsEngineParameter(numSolverIterations=50)

    link_length = 0.5
    link_mass = 0.5
    link_half_extents = [0.02, 0.02, link_length / 2]
    pivot_position = [0, 0, 2.0]
    initial_angle = math.pi / 3

    link_col = p.createCollisionShape(p.GEOM_BOX, halfExtents=link_half_extents)

    pendulum = p.createMultiBody(
        baseMass=0,
        baseCollisionShapeIndex=-1,
        basePosition=pivot_position,
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
    p.resetJointState(pendulum, 0, initial_angle, 0)

    total_steps_3 = 1440
    traj3 = []
    for i in range(total_steps_3):
        js = p.getJointState(pendulum, 0)
        damping_torque = -JOINT_DAMPING * js[1]
        p.setJointMotorControl2(pendulum, 0, p.TORQUE_CONTROL, force=damping_torque)
        p.stepSimulation()
        if (i + 1) % RECORD_EVERY == 0:
            js = p.getJointState(pendulum, 0)
            traj3.append({
                "step": i + 1,
                "angle": round(js[0], 8),
                "angular_velocity": round(js[1], 8)
            })

    observations["damped_pendulum"] = traj3
    config["damped_pendulum"] = {
        "description": "Single-link pendulum released from initial angle with viscous damping applied as external torque. Identify the damping coefficient.",
        "setup": {
            "base_mass": 0,
            "base_position": pivot_position,
            "link_mass": link_mass,
            "link_length": link_length,
            "link_collision_shape": "GEOM_BOX",
            "link_half_extents": list(link_half_extents),
            "link_position_offset_from_joint": [0, 0, -link_length / 2],
            "link_orientation": [0, 0, 0, 1],
            "link_inertial_frame_position": [0, 0, 0],
            "link_inertial_frame_orientation": [0, 0, 0, 1],
            "link_linearDamping": 0,
            "link_angularDamping": 0,
            "joint_type": "JOINT_REVOLUTE",
            "joint_axis": [0, 1, 0],
            "initial_angle_rad": initial_angle,
            "initial_angular_velocity": 0,
            "gravity": [0, 0, -9.81],
            "timestep": DT,
            "solver_iterations": 50,
            "record_every_n_steps": RECORD_EVERY,
            "total_steps": total_steps_3
        },
        "unknowns": ["damping_coefficient"],
        "notes": "Damping is NOT applied via changeDynamics jointDamping. Instead, at each simulation step BEFORE calling stepSimulation: (1) read current joint angular velocity via getJointState, (2) compute torque = -damping_coefficient * angular_velocity, (3) apply torque via setJointMotorControl2 with TORQUE_CONTROL mode. The default joint motor must first be disabled using setJointMotorControl2 with VELOCITY_CONTROL and force=0. PyBullet automatically computes link inertia from collision shape geometry and mass."
    }

    p.disconnect()

    with open("/app/observations.json", "w") as f:
        json.dump(observations, f, indent=2)

    with open("/app/experiment_config.json", "w") as f:
        json.dump(config, f, indent=2)

    print("Data generation complete.")


if __name__ == "__main__":
    main()
