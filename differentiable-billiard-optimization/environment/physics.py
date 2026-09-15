"""2D rigid-body physics simulator with elastic collisions and wall bounces.

Implements a symplectic Euler integrator with impulse-based collision resolution.
Supports both regular floats and dual numbers (CDual) for automatic differentiation.
"""


def _real(v):
    """Extract the real-valued component for branching decisions.

    When running with dual numbers, comparisons must use only the real part
    to ensure consistent branching between primal and tangent computations.
    """
    return v.real if hasattr(v, 'dual') else float(v)


def simulate(positions, velocities, radius, mass, dt, steps, table=None, restitution=1.0):
    """Run a 2D rigid-body simulation with elastic collisions and wall bounces.

    Args:
        positions: list of [x, y] per ball (may contain CDual values)
        velocities: list of [vx, vy] per ball
        radius: ball radius (float)
        mass: ball mass (float, equal for all balls)
        dt: integration timestep
        steps: number of simulation steps
        table: dict with keys x_min, x_max, y_min, y_max defining table
               boundaries, or None for unbounded simulation
        restitution: coefficient of restitution for wall bounces (0 to 1)

    Returns:
        list of [x, y] final positions for each ball
    """
    n = len(positions)
    pos = [[p[0], p[1]] for p in positions]
    vel = [[v[0], v[1]] for v in velocities]

    for _ in range(steps):
        # Symplectic Euler: update positions using current velocities
        for i in range(n):
            pos[i][0] = pos[i][0] + vel[i][0] * dt
            pos[i][1] = pos[i][1] + vel[i][1] * dt

        # Ball-ball elastic collision detection and response
        for i in range(n):
            for j in range(i + 1, n):
                dx = pos[j][0] - pos[i][0]
                dy = pos[j][1] - pos[i][1]
                dist_sq = dx * dx + dy * dy
                dist = dist_sq.sqrt() if hasattr(dist_sq, 'sqrt') else dist_sq ** 0.5

                min_dist = 2.0 * radius
                d = _real(dist)

                if d < min_dist and d > 1e-12:
                    # TODO: Implement elastic collision response
                    # 1. Compute collision normal: n = (dx, dy) / dist
                    # 2. Compute relative velocity of j w.r.t. i along normal:
                    #    rvn = (vel[j] - vel[i]) dot n
                    # 3. If rvn < 0 (approaching), apply equal-mass elastic impulse:
                    #    vel[i] += rvn * n
                    #    vel[j] -= rvn * n
                    # 4. Apply positional correction for overlap:
                    #    overlap = min_dist - dist
                    #    If overlap > 0, separate balls by half the overlap along n
                    pass

        # Wall/cushion bounce handling
        if table is not None:
            # TODO: Implement wall reflections for each ball
            # For each ball, check all four table boundaries (accounting for
            # ball radius). When a ball exceeds a boundary:
            #   - Reflect the position about the boundary edge
            #   - Reverse and scale the velocity component by -restitution
            # Use _real() for the branch condition but apply arithmetic to
            # the original (possibly dual-number) values so gradients flow.
            #
            # Example for left wall:
            #   px = _real(pos[i][0])
            #   if px - radius < table['x_min']:
            #       pos[i][0] = 2*(table['x_min'] + radius) - pos[i][0]
            #       vel[i][0] = vel[i][0] * (-restitution)
            pass

    return [[p[0], p[1]] for p in pos]
