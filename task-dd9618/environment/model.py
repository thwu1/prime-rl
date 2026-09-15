"""Two Moons probabilistic simulator for simulation-based inference.

Prior: theta ~ Uniform([-1, 1]^2)
Simulator: Nonlinear stochastic mapping theta -> x in R^2

The generative process applies a rotation, absolute value, and additive
semicircular noise, producing a crescent-shaped bimodal posterior.
The likelihood p(x|theta) is intractable.
"""
import math
import random

PRIOR_LOW = -1.0
PRIOR_HIGH = 1.0
DIM_PARAMETERS = 2
DIM_DATA = 2


def sample_prior(rng=None):
    """Sample parameters from the prior: Uniform([-1, 1]^2).

    Args:
        rng: random.Random instance (optional)

    Returns:
        List of 2 floats: [theta_1, theta_2]
    """
    if rng is None:
        rng = random.Random()
    return [rng.uniform(PRIOR_LOW, PRIOR_HIGH) for _ in range(DIM_PARAMETERS)]


def simulate(theta, rng=None):
    """Run the Two Moons simulator.

    The generative process:
    1. Sample angle a ~ Uniform(-pi/2, pi/2)
    2. Sample radius r ~ Normal(0.1, 0.01)
    3. Compute noise point p = (cos(a)*r + 0.25, sin(a)*r)
    4. Rotate theta by -pi/4: z = R(-pi/4) @ theta
    5. Output x = p + (-|z_0|, z_1)

    Args:
        theta: List or tuple of 2 floats [theta_1, theta_2]
        rng: random.Random instance (optional)

    Returns:
        List of 2 floats: [x_1, x_2]
    """
    if rng is None:
        rng = random.Random()
    a = rng.uniform(-math.pi / 2.0, math.pi / 2.0)
    r = rng.gauss(0.1, 0.01)
    p1 = math.cos(a) * r + 0.25
    p2 = math.sin(a) * r
    ang = -math.pi / 4.0
    c = math.cos(ang)
    s = math.sin(ang)
    z0 = c * theta[0] - s * theta[1]
    z1 = s * theta[0] + c * theta[1]
    return [p1 - abs(z0), p2 + z1]


def distance(x, y):
    """Euclidean distance between two 2D observations.

    Args:
        x, y: Lists of 2 floats

    Returns:
        Float: Euclidean distance
    """
    return math.sqrt((x[0] - y[0]) ** 2 + (x[1] - y[1]) ** 2)
