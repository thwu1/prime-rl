"""
Variable-coefficient anisotropic Helmholtz equation on [0,1]^2.

PDE:
    -div(K(x,y) grad u) + c(x,y) u = f(x,y)    in Omega = [0,1]^2
    u = 0                                          on dOmega

Diffusion tensor (symmetric positive definite):
    K(x,y) = [[1 + x^2,   x*y/2  ],
              [x*y/2,    1 + y^2 ]]

Reaction coefficient:
    c(x,y) = 1

Manufactured exact solution:
    u(x,y) = sin(pi*x) * sin(pi*y)

The forcing function f is derived analytically from the PDE so that
u_exact satisfies the equation exactly.
"""
import numpy as np


def diffusion_tensor(x, y):
    """Return 2x2 diffusion tensor K at point (x, y)."""
    return np.array([[1.0 + x**2, x * y / 2.0],
                     [x * y / 2.0, 1.0 + y**2]])


def reaction(x, y):
    """Return reaction coefficient c at point (x, y)."""
    return 1.0


def exact_solution(x, y):
    """Return exact solution u(x, y) = sin(pi*x) * sin(pi*y)."""
    return np.sin(np.pi * x) * np.sin(np.pi * y)


def exact_gradient(x, y):
    """Return gradient [du/dx, du/dy] at point (x, y)."""
    return np.array([
        np.pi * np.cos(np.pi * x) * np.sin(np.pi * y),
        np.pi * np.sin(np.pi * x) * np.cos(np.pi * y)
    ])


def forcing(x, y):
    """Return forcing f(x, y) = -div(K grad u) + c * u.

    Derived analytically from the manufactured solution.
    """
    pi = np.pi
    sx = np.sin(pi * x)
    sy = np.sin(pi * y)
    cx = np.cos(pi * x)
    cy = np.cos(pi * y)

    return (
        (pi**2 * (2.0 + x**2 + y**2) + 1.0) * sx * sy
        - 2.0 * pi * x * cx * sy
        - 2.5 * pi * y * sx * cy
        - x * y * pi**2 * cx * cy
    )
