"""Candidate model A: Classic two-species interaction."""

MODEL_NAME = "model_a"
PARAM_NAMES = ["alpha", "beta", "gamma", "delta"]
DEFAULT_PARAMS = [0.5, 0.03, 0.5, 0.03]
PARAM_BOUNDS = [(0.01, 3.0), (0.001, 0.2), (0.01, 3.0), (0.001, 0.2)]


def vector_field(t, y, params):
    alpha, beta, gamma, delta = params
    dy1 = alpha * y[0] - beta * y[0] * y[1]
    dy2 = -gamma * y[1] + delta * y[0] * y[1]
    return [dy1, dy2]
