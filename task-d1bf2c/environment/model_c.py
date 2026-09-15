"""Candidate model C: Two-species interaction with density-dependent mortality in species 2."""

MODEL_NAME = "model_c"
PARAM_NAMES = ["alpha", "beta", "gamma", "delta", "epsilon"]
DEFAULT_PARAMS = [0.5, 0.03, 0.5, 0.03, 0.001]
PARAM_BOUNDS = [(0.01, 3.0), (0.001, 0.2), (0.01, 3.0), (0.001, 0.2), (0.0, 0.1)]


def vector_field(t, y, params):
    alpha, beta, gamma, delta, epsilon = params
    dy1 = alpha * y[0] - beta * y[0] * y[1]
    dy2 = -gamma * y[1] + delta * y[0] * y[1] - epsilon * y[1] ** 2
    return [dy1, dy2]
