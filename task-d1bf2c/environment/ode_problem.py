"""Lotka-Volterra predator-prey model.

Pure Python implementation (no external dependencies).
The vector field and Jacobian define the ODE system:
    dy1/dt = alpha * y1 - beta * y1 * y2
    dy2/dt = -gamma * y2 + delta * y1 * y2
"""

# ODE parameters
ALPHA = 0.5
BETA = 0.05
GAMMA = 0.5
DELTA = 0.05

# Initial conditions
Y0 = [20.0, 20.0]

# Time interval
T0 = 0.0
T1 = 10.0


def vector_field(y):
    """Compute dy/dt = f(y) for the Lotka-Volterra system.

    Args:
        y: sequence of length 2, [prey, predator] populations

    Returns:
        list of length 2, [dy1/dt, dy2/dt]
    """
    dy1 = ALPHA * y[0] - BETA * y[0] * y[1]
    dy2 = -GAMMA * y[1] + DELTA * y[0] * y[1]
    return [dy1, dy2]


def jacobian(y):
    """Compute the Jacobian J_f(y) of the vector field.

    Args:
        y: sequence of length 2, [prey, predator] populations

    Returns:
        2x2 list of lists, J[i][j] = df_i / dy_j
    """
    J = [
        [ALPHA - BETA * y[1], -BETA * y[0]],
        [DELTA * y[1], -GAMMA + DELTA * y[0]]
    ]
    return J
