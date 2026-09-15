"""Lotka-Volterra predator-prey system definition.

dx/dt = alpha*x - beta*x*y
dy/dt = delta*x*y - gamma*y

Parameters: [alpha, beta, gamma, delta]
"""

TRUE_PARAMS = [1.5, 1.0, 3.0, 1.0]
Y0 = [1.0, 1.0]


def lotka_volterra(t, u, params):
    """Right-hand side of the Lotka-Volterra ODE system."""
    x, y = u[0], u[1]
    alpha, beta, gamma, delta = params[0], params[1], params[2], params[3]
    dxdt = alpha * x - beta * x * y
    dydt = delta * x * y - gamma * y
    return [dxdt, dydt]
