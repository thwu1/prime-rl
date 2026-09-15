"""
Constrained optimization solver.

Implement the optimize() function below. It will be called by the test
harness with black-box functions f, g, c and must return a feasible
point that minimizes f(x) subject to c(x) <= 0.

Args:
    f: Objective function f(x) -> float. Each call costs 1 evaluation.
    g: Gradient of f, g(x) -> ndarray. Each call costs 2 evaluations.
    c: Constraint function c(x) -> ndarray. Feasible when all c_i(x) <= 0.
       Each call costs 1 evaluation.
    x0: Initial point (ndarray).
    n: Total evaluation budget. The sum of all f, g, c calls must not exceed n.
    count: Function returning current evaluation count.
    prob: Problem identifier string (e.g., 'prob1', 'prob2', ...).

Returns:
    x_best: ndarray, the best feasible point found.

Notes:
    - No constraint gradient is provided; estimate it if needed.
    - Only numpy is allowed as an external dependency.
    - Different strategies per problem are allowed (prob is provided).
"""
import numpy as np


def optimize(f, g, c, x0, n, count, prob):
    x_best = x0
    return x_best
