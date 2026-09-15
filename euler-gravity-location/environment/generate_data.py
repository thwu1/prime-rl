#!/usr/bin/env python3
"""Generate scattered gravity survey data and prediction grid."""
import math
import os
import random

G = 6.674e-11  # gravitational constant, m^3 kg^-1 s^-2

# True subsurface point-mass sources: (easting_m, northing_m, depth_m, mass_kg)
SOURCES = [
    (2500.0, 7000.0, 1200.0, 5e11),
    (7000.0, 3000.0, 2000.0, 1.5e12),
    (4500.0, 5000.0, 800.0, 2e11),
    (8000.0, 8000.0, 2500.0, 2e12),
]


def compute_gz(x, y, z_obs, sources):
    """Downward gravitational acceleration (mGal) at (x, y, z_obs) from point masses."""
    gz = 0.0
    for xs, ys, depth, mass in sources:
        dx = x - xs
        dy = y - ys
        dz = z_obs + depth  # vertical separation (obs above surface, source below)
        r = math.sqrt(dx * dx + dy * dy + dz * dz)
        gz += G * mass * dz / (r ** 3) * 1e5
    return gz


def main():
    os.makedirs('/opt/taskdata', exist_ok=True)

    # Generate 500 scattered survey observations at varying heights
    random.seed(42)
    with open('/opt/taskdata/survey.csv', 'w') as f:
        f.write('easting,northing,height,gz_mGal\n')
        for _ in range(500):
            e = random.uniform(200, 9800)
            n = random.uniform(200, 9800)
            h = random.uniform(100, 500)
            gz = compute_gz(e, n, h, SOURCES)
            noise = random.gauss(0, 0.002)
            f.write('{:.2f},{:.2f},{:.2f},{:.10f}\n'.format(e, n, h, gz + noise))

    # Generate prediction grid: 51x51 at 500 m altitude, 200 m spacing
    with open('/opt/taskdata/prediction_grid.csv', 'w') as f:
        f.write('easting,northing,height\n')
        for ni in range(51):
            northing = ni * 200.0
            for ei in range(51):
                easting = ei * 200.0
                f.write('{:.1f},{:.1f},500.0\n'.format(easting, northing))


if __name__ == '__main__':
    main()
