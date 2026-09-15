# Virtual Trade Mathematics — Working Notes

## Setting

An embedded CPAMM with reserves `(x, y)` satisfying `x · y = K`. Two order
pools continuously sell tokens into the AMM at constant rates:

- Pool X sells at rate `x_rate` tokens per block
- Pool Y sells at rate `y_rate` tokens per block

We want the reserves after `t` blocks of simultaneous continuous trading.

## Single-sided case

When only one side is active the analysis is straightforward. If only X is
being sold, the X reserve grows linearly and the Y reserve follows from the
invariant. The reverse holds for Y-only selling.

## Two-sided case — intuition

When both pools sell simultaneously, each infinitesimal trade by one pool
shifts the price seen by the other. The X reserve increases from X-sellers
adding tokens, but simultaneously decreases as Y-sellers swap Y for X.

The net rate of change of the X reserve involves a balance between the
constant inflow `x_rate` and a term proportional to `x² / K` representing
the rate at which Y-sellers extract X from the pool (since marginal price
equals `y / x = K / x²`).

## Equilibrium

There exists a fixed point where the AMM reserves do not change despite
continuous selling from both sides. At this equilibrium, the inflow and
outflow of each token exactly cancel. The equilibrium X reserve depends on
the sell rates and the pool invariant.

## Solution character

The governing equation for the two-sided case is a first-order nonlinear ODE
of Riccati type. Its general solution can be expressed in terms of hyperbolic
trigonometric functions. The specific branch of the solution depends on
whether the initial X reserve is above or below the equilibrium point.

## Caution

Numerical care is needed near the equilibrium point where the two branches
meet. Floating-point evaluation of inverse hyperbolic functions can be
unstable when their argument approaches domain boundaries.
