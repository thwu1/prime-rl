"""Candidate model D: Two-species interaction with Type III functional response."""

MODEL_NAME = "model_d"
PARAM_NAMES = ["alpha", "beta", "gamma", "delta", "kappa"]
DEFAULT_PARAMS = [0.5, 0.03, 0.5, 0.03, 5.0]
PARAM_BOUNDS = [(0.01, 3.0), (0.001, 0.5), (0.01, 3.0), (0.001, 0.2), (0.1, 100.0)]


def vector_field(t, y, params):
    alpha, beta, gamma, delta, kappa = params
    fr = y[0] ** 2 / (kappa ** 2 + y[0] ** 2)
    dy1 = alpha * y[0] - beta * fr * y[1]
    dy2 = -gamma * y[1] + delta * fr * y[1]
    return [dy1, dy2]
