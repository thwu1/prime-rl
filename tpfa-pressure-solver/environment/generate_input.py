#!/usr/bin/env python3
"""Generate input data for the TPFA reservoir pressure solver task."""
import json
import os


def graded_spacing(n, total, ratio=1.15):
    """Generate n cell widths with geometric grading: small at edges, large in middle."""
    half = n // 2
    sizes = []
    for i in range(half):
        sizes.append(ratio ** i)
    for i in range(half - 1, -1, -1):
        sizes.append(ratio ** i)
    scale = total / sum(sizes)
    return [round(s * scale, 8) for s in sizes]


def main():
    os.makedirs('/app/input', exist_ok=True)

    nx, ny = 20, 20
    total_x, total_y = 1000.0, 1000.0

    dx = graded_spacing(nx, total_x)
    dy = graded_spacing(ny, total_y)

    grid = {
        "nx": nx,
        "ny": ny,
        "dx": dx,
        "dy": dy,
        "thickness": 10.0
    }
    with open('/app/input/grid.json', 'w') as f:
        json.dump(grid, f, indent=2)

    # Permeability field: kx[i][j] where i=column (x), j=row (y)
    k_bg = 1e-13
    kx = [[k_bg for _ in range(ny)] for _ in range(nx)]
    ky = [[k_bg for _ in range(ny)] for _ in range(nx)]

    # High-perm channel: rows 8-11, columns 3-16 (anisotropic)
    for i in range(3, 17):
        for j in range(8, 12):
            kx[i][j] = 5e-13
            ky[i][j] = 2e-13

    # Low-perm barrier: columns 9-10, rows 0-6
    for i in range(9, 11):
        for j in range(0, 7):
            kx[i][j] = 5e-15
            ky[i][j] = 1e-14

    perm = {"kx": kx, "ky": ky}
    with open('/app/input/permeability.json', 'w') as f:
        json.dump(perm, f)

    wells = {
        "wells": [
            {"name": "INJ1", "i": 2, "j": 2, "type": "rate", "value": 5e-4},
            {"name": "INJ2", "i": 2, "j": 17, "type": "rate", "value": 5e-4},
            {"name": "PROD1", "i": 17, "j": 17, "type": "rate", "value": -5e-4},
            {"name": "PROD2", "i": 17, "j": 2, "type": "rate", "value": -5e-4}
        ]
    }
    with open('/app/input/wells.json', 'w') as f:
        json.dump(wells, f, indent=2)

    fluid = {"viscosity": 1e-3}
    with open('/app/input/fluid.json', 'w') as f:
        json.dump(fluid, f, indent=2)

    config = {
        "reference_pressure": {"i": 10, "j": 10, "value": 2e7}
    }
    with open('/app/input/config.json', 'w') as f:
        json.dump(config, f, indent=2)


if __name__ == '__main__':
    main()
