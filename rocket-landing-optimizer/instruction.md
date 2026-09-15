`/app/problem.py` defines a 2D powered descent guidance problem for a rocket that must land at the origin. The rocket has mass depletion — thrust acceleration is `T/m` where mass decreases proportionally to thrust magnitude. The state vector is `[rx, ry, vx, vy, z]` where `z = ln(mass)`, and the control is the thrust force vector `[Tx, Ty]`.

The dynamics are nonlinear due to the `exp(-z)` coupling between thrust force and mass. The thrust magnitude must remain within `[T_min, T_max]`, the trajectory must satisfy a glideslope constraint `ry >= tan(gamma) * |rx|`, and mass must stay within `[m_dry, m_wet]`. The rocket must reach the origin with zero velocity while minimizing fuel consumption (maximizing final mass).

Create `/app/optimizer.py` with a function `solve()` that returns a dict:
- `'state'`: ndarray `(N+1, 5)` — state trajectory
- `'control'`: ndarray `(N, 2)` — thrust force at each interval
- `'sigma'`: ndarray `(N,)` — thrust magnitude at each interval
- `'tf'`: float — total flight time

All parameters, dynamics equations, and constraints are specified in `/app/problem.py`. Controls are zero-order hold over each of the `N` intervals. The returned trajectory must satisfy all constraints when forward-simulated and achieve fuel consumption below `max_fuel`.