# Rectangular Prism Gravity: Mathematical Reference

## Coordinate System

Right-handed Cartesian: easting (x), northing (y), upward (z). A rectangular
prism has boundaries x1 (west), x2 (east), y1 (south), y2 (north), z1 (bottom),
z2 (top), with x1 < x2, y1 < y2, z1 < z2.

## Forward Model

The gravitational field component f at observation point p = (xp, yp, zp) due to
a prism with uniform density rho is:

    f(p) = G * rho * ||| K(X, Y, Z) |_{X1}^{X2} |_{Y1}^{Y2} |_{Z1}^{Z2}

where the shifted coordinates are Xi = xi - xp, Yi = yi - yp, Zi = zi - zp, and
the triple evaluation expands to:

    sum over all 8 vertices (Xi, Yj, Zk) with signs (-1)^(i+j+k)

where i,j,k in {1,2} index the lower/upper bounds of each dimension.

## Kernel Functions

In all kernels below, r = sqrt(x^2 + y^2 + z^2).

### Potential

    k_V(x,y,z) = x*y*L(z; x,y,r) + y*z*L(x; y,z,r) + x*z*L(y; z,x,r)
                  - (x^2/2)*A(y*z, x*r) - (y^2/2)*A(x*z, y*r) - (z^2/2)*A(x*y, z*r)

### Acceleration Components

Sign convention: the kernels below give the acceleration in the positive
direction of each axis (eastward, northward, **upward**). The original
formulation by Nagy (2000) uses a downward z-axis; the minus sign converts to
upward.

    k_x(x,y,z) = -[ y*L(z; x,y,r) + z*L(y; z,x,r) - x*A(y*z, x*r) ]
    k_y(x,y,z) = -[ z*L(x; y,z,r) + x*L(z; x,y,r) - y*A(x*z, y*r) ]
    k_z(x,y,z) = -[ x*L(y; z,x,r) + y*L(x; y,z,r) - z*A(x*y, z*r) ]

### Gravity Gradient Tensor (diagonal components)

    k_xx(x,y,z) = -A(y*z, x*r)
    k_yy(x,y,z) = -A(x*z, y*r)
    k_zz(x,y,z) = -A(x*y, z*r)

These satisfy the Laplace equation outside the source mass:

    k_xx + k_yy + k_zz = 0

## Numerically Stable Special Functions

### L(a; b, c, r) — Safe Logarithm

The first argument `a` is the coordinate being logged. The arguments `b` and `c`
are the other two shifted coordinates of the vertex (needed for numerical
stability when a < 0).

    L(a; b, c, r) =
        0                          if r = 0
        ln(a + r)                  if a >= 0
        ln((b^2 + c^2) / (r - a)) if a < 0  and  b^2 + c^2 > 0
        -ln(-2*a)                  if a < 0  and  b = 0  and  c = 0

The third branch is mathematically equivalent to ln(a + r) but avoids
catastrophic cancellation when a is negative and close to -r.

### A(p, q) — Safe Arctangent

    A(p, q) =
        arctan(p / q)   if q != 0
        pi/2            if q = 0  and  p > 0
        -pi/2           if q = 0  and  p < 0
        0               if q = 0  and  p = 0

Note: this is NOT the standard two-argument atan2(y,x). It uses single-argument
arctan(p/q) when q != 0, which has range (-pi/2, pi/2). This specific definition
is required for the gravitational field to satisfy Poisson's equation and
maintain the correct symmetry properties of the prism.

## Constants

    G = 6.6743e-11  m^3 / (kg * s^2)

## Units

- Coordinates: meters (m)
- Density: kilograms per cubic meter (kg/m^3)
- Gravitational potential: J/kg (= m^2/s^2)
- Gravitational acceleration: output in milligal (mGal), where 1 mGal = 1e-5 m/s^2
- Gravity gradient tensor: 1/s^2

## References

- Nagy, D., Papp, G., & Benedek, J. (2000). The gravitational potential and its
  derivatives for the prism. Journal of Geodesy, 74, 552-560.
- Fukushima, T. (2020). Speed and accuracy improvements in standard algorithm for
  prismatic gravitational field. Geophysical Journal International, 222(3),
  1898-1908.
