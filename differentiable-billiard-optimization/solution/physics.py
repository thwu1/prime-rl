"""2D rigid-body physics simulator with elastic collisions and wall bounces."""


def _real(v):
    """Extract real-valued component for branching decisions."""
    return v.real if hasattr(v, 'dual') else float(v)


def simulate(positions, velocities, radius, mass, dt, steps, table=None, restitution=1.0):
    """Run a 2D rigid-body simulation with elastic collisions and wall bounces."""
    n = len(positions)
    pos = [[p[0], p[1]] for p in positions]
    vel = [[v[0], v[1]] for v in velocities]

    for _ in range(steps):
        # Symplectic Euler position update
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
                    # Collision normal (from i to j)
                    nx = dx / dist
                    ny = dy / dist

                    # Relative velocity of j w.r.t. i along normal
                    rvx = vel[j][0] - vel[i][0]
                    rvy = vel[j][1] - vel[i][1]
                    rvn = rvx * nx + rvy * ny

                    # Only resolve if approaching
                    if _real(rvn) < 0:
                        vel[i][0] = vel[i][0] + rvn * nx
                        vel[i][1] = vel[i][1] + rvn * ny
                        vel[j][0] = vel[j][0] - rvn * nx
                        vel[j][1] = vel[j][1] - rvn * ny

                    # Positional correction for overlap
                    overlap = min_dist - dist
                    if _real(overlap) > 0:
                        half = overlap * 0.5
                        pos[i][0] = pos[i][0] - half * nx
                        pos[i][1] = pos[i][1] - half * ny
                        pos[j][0] = pos[j][0] + half * nx
                        pos[j][1] = pos[j][1] + half * ny

        # Wall/cushion bounce handling
        if table is not None:
            x_min = table['x_min']
            x_max = table['x_max']
            y_min = table['y_min']
            y_max = table['y_max']

            for i in range(n):
                px = _real(pos[i][0])
                py = _real(pos[i][1])

                if px - radius < x_min:
                    pos[i][0] = (x_min + radius) + ((x_min + radius) - pos[i][0])
                    vel[i][0] = vel[i][0] * (-restitution)
                elif px + radius > x_max:
                    pos[i][0] = (x_max - radius) - (pos[i][0] - (x_max - radius))
                    vel[i][0] = vel[i][0] * (-restitution)

                if py - radius < y_min:
                    pos[i][1] = (y_min + radius) + ((y_min + radius) - pos[i][1])
                    vel[i][1] = vel[i][1] * (-restitution)
                elif py + radius > y_max:
                    pos[i][1] = (y_max - radius) - (pos[i][1] - (y_max - radius))
                    vel[i][1] = vel[i][1] * (-restitution)

    return [[p[0], p[1]] for p in pos]
