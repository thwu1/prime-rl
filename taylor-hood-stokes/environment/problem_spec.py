
"""
Manufactured solution for 2D Stokes equations verification.

Problem: Find (u, p) satisfying
    -Delta(u) + grad(p) = f   in Omega = [0,1]^2
    div(u) = 0                 in Omega
    u = u_exact                on dOmega

with viscosity nu = 1.

Exact velocity (divergence-free by construction via stream function):
    Stream function:
      psi(x,y) = sin(pi*x)*sin(pi*y)/pi^2 + x^2*(1-x)^2 * y^2*(1-y)^2

    u1(x,y) = d(psi)/dy
            = sin(pi*x)*cos(pi*y)/pi + 2*x^2*(1-x)^2*y*(1-y)*(1-2*y)

    u2(x,y) = -d(psi)/dx
            = -cos(pi*x)*sin(pi*y)/pi - 2*x*(1-x)*(1-2*x)*y^2*(1-y)^2

Exact pressure:
    p(x,y) = sin(pi*x) * sin(pi*y)

Body force:
    f = -Laplacian(u_exact) + gradient(p_exact)
    This is NOT provided as a function. You must derive it from the
    definitions above using symbolic differentiation or manual calculus.
"""

import numpy as np

PI = np.pi


def u_exact(x, y):
    """Exact velocity field at point (x, y).

    Returns:
        u1, u2: velocity components (scalars)
    """
    u1 = (np.sin(PI * x) * np.cos(PI * y) / PI
          + 2.0 * x**2 * (1.0 - x)**2 * y * (1.0 - y) * (1.0 - 2.0 * y))
    u2 = (-np.cos(PI * x) * np.sin(PI * y) / PI
          - 2.0 * x * (1.0 - x) * (1.0 - 2.0 * x) * y**2 * (1.0 - y)**2)
    return u1, u2


def p_exact(x, y):
    """Exact pressure field at point (x, y).

    Returns:
        p: pressure value (scalar)
    """
    return np.sin(PI * x) * np.sin(PI * y)
