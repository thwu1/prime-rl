"""
Model and simulation parameters for the acrobot swing-up task.

These correspond to the AI Olympics / RealAIGym acrobot competition
(designC.1 / model1.1).
"""
import numpy as np

# Physical model parameters
PARAMS = {
    "m1": 0.5234602302310271,       # link 1 mass [kg]
    "m2": 0.6255677234174437,       # link 2 mass [kg]
    "l1": 0.2,                      # link 1 length [m]
    "l2": 0.3,                      # link 2 length [m]
    "r1": 0.2,                      # link 1 center of mass [m]
    "r2": 0.25569305436052964,      # link 2 center of mass [m]
    "I1": 0.031887199591513114,     # link 1 inertia [kg*m^2]
    "I2": 0.05086984812807257,      # link 2 inertia [kg*m^2]
    "Ir": 0.0,                      # motor inertia [kg*m^2]
    "gr": 6,                        # gear ratio
    "g": 9.81,                      # gravity [m/s^2]
    "b1": 0.0,                      # joint 1 viscous damping
    "b2": 0.0,                      # joint 2 viscous damping
    "cf1": 0.0,                     # joint 1 Coulomb friction
    "cf2": 0.0,                     # joint 2 Coulomb friction
    "torque_limit": (0.0, 6.0),     # (joint1_max, joint2_max) [Nm]
}

# Simulation settings
SIM_CONFIG = {
    "dt": 0.002,                    # integration timestep [s]
    "t_final": 10.0,                # simulation duration [s]
    "x0": [0.0, 0.0, 0.0, 0.0],    # initial state (hanging down)
    "goal": [np.pi, 0.0, 0.0, 0.0],  # goal state (upright)
    "threshold_height": 0.45,       # end-effector height threshold [m]
}
