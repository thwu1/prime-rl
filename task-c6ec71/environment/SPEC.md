# Bezier Arc Length Computation — Requirements Specification


## 1. Arc Length Integral

The arc length of a parametric curve B(t) over [0, 1] is:

    L = integral_0^1 |B'(t)| dt = integral_0^1 sqrt(B'_x(t)^2 + B'_y(t)^2) dt

### Quadratic Bezier

For a quadratic Bezier with control points P0, P1, P2:

    B'(t) = 2[(1-t)(P1-P0) + t(P2-P1)]

The speed function |B'(t)|^2 is a quadratic polynomial in t. The resulting arc length integral — of the form integral sqrt(quadratic) dt — admits closed-form evaluation for non-degenerate cases.

**Important**: Degenerate and near-degenerate control point configurations can cause numerical issues in the closed-form evaluation (division by near-zero quantities, negative discriminants, loss of significance). Your implementation must produce correct, finite results for all valid input curves, including those where the control polygon is nearly collinear.

### Cubic Bezier

For a cubic Bezier with control points P0, P1, P2, P3:

    B'(t) = 3[(1-t)^2 (P1-P0) + 2(1-t)t(P2-P1) + t^2 (P3-P2)]

    B''(t) = 6[(1-t)(P2 - 2*P1 + P0) + t(P3 - 2*P2 + P1)]

No closed-form arc length exists for general cubic Beziers. Numerical methods are required.

## 2. Numerical Integration

Pre-computed quadrature coefficients for orders 4, 8, 16, and 24 are provided in `coefficients.py`. The C shared library `libquadrature.so` must implement the evaluation functions declared in `quadrature.h` for the cubic arc length integrand.

## 3. Error Control

A single evaluation of numerical integration may be insufficiently accurate for curves with high curvature variation or rapid direction changes. The implementation must detect when accuracy is insufficient and refine the computation.

The `estimate_cubic_error` function must produce a **conservative** (never-underestimating) bound on the integration error for a given curve. The geometric properties of a Bezier curve's control polygon — and how they diverge from the straight-line connecting the endpoints — carry information about the integrand's smoothness and can inform error estimation.

## 4. Precision Targets

- Quadratic Bezier arc lengths: relative error < 1e-12
- Cubic Bezier arc lengths: relative error < 1e-8
- The error bound function must never return a value smaller than the actual integration error for any test curve
