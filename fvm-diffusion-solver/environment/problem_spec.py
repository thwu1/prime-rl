"""
Problem specification for the FVM solver benchmark.

PDE:  div( kappa(x,y) * grad(T) ) = S(x,y)

Domain: annular region, r_inner = 0.5, r_outer = 2.0

Diffusion coefficient:
    kappa(x, y) = 1 + 0.5 * x

Manufactured (exact) solution:
    T_exact(x, y) = x^2 + y^2 + 1

Gradient of exact solution:
    grad(T_exact) = (2x, 2y)

Source term (derived analytically from div(kappa * grad(T_exact))):
    S(x, y) = 4 + 3x

    Derivation
    ----------
    dT/dx = 2x,  dT/dy = 2y
    kappa * dT/dx = (1 + 0.5x)(2x) = 2x + x^2
    kappa * dT/dy = (1 + 0.5x)(2y) = 2y + xy
    d/dx(kappa * dT/dx) = 2 + 2x
    d/dy(kappa * dT/dy) = 2 + x
    S = (2 + 2x) + (2 + x) = 4 + 3x

Boundary conditions:
    Inner boundary (r = 0.5):  Dirichlet, T = T_exact(x, y)
    Outer boundary (r = 2.0):  Neumann,   kappa * dT/dn = q(x, y, n)

Analytical inner-boundary heat flux:
    Q_inner = integral over inner circle of kappa * grad(T) . n_out ds
    where n_out at the inner boundary points toward the centre (away from domain).

    At r = 0.5:  n_out = (-cos(theta), -sin(theta))
    grad(T) . n_out = (2x)(-cos) + (2y)(-sin) = -2r = -1
    kappa = 1 + 0.25 cos(theta)
    ds = 0.5 d(theta)

    Q_inner = integral_0^{2pi} (1 + 0.25 cos(theta)) * (-1) * 0.5 d(theta)
            = -0.5 * 2pi = -pi
"""

import math

R_INNER = 0.5
R_OUTER = 2.0

ANALYTICAL_INNER_FLUX = -math.pi


def kappa(x, y):
    """Variable diffusion coefficient."""
    return 1.0 + 0.5 * x


def source(x, y):
    """Source term S(x, y) = 4 + 3x."""
    return 4.0 + 3.0 * x


def T_exact(x, y):
    """Manufactured exact solution."""
    return x * x + y * y + 1.0


def grad_T_exact(x, y):
    """Gradient of the exact solution (dT/dx, dT/dy)."""
    return (2.0 * x, 2.0 * y)


def neumann_flux(x, y, nx, ny):
    """Neumann flux  kappa * grad(T) . n  at point (x,y) with unit normal (nx,ny)."""
    dTdx, dTdy = grad_T_exact(x, y)
    return kappa(x, y) * (dTdx * nx + dTdy * ny)
