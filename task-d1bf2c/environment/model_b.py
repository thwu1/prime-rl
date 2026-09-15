"""Candidate model B: Two-species interaction with logistic growth in species 1."""

MODEL_NAME = "model_b"
PARAM_NAMES = ["alpha", "beta", "gamma", "delta", "K"]
DEFAULT_PARAMS = [0.5, 0.03, 0.5, 0.03, 100.0]
PARAM_BOUNDS = [(0.01, 3.0), (0.001, 0.2), (0.01, 3.0), (0.001, 0.2), (10.0, 1000.0)]


def vector_field(t, y, params):
    alpha, beta, gamma, delta, K = params
    dy1 = alpha * y[0] * (1.0 - y[0] / K) - beta * y[0] * y[1]
    dy2 = -gamma * y[1] + delta * y[0] * y[1]
    return [dy1, dy2]
