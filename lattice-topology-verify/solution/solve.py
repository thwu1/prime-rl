
"""
Solution: construct a correct gyroid module solid using manifold3d.

Fixes applied to the broken /app/build.py:
1. Add pi/4 phase shift to gyroid SDF coordinates
2. Add missing third box intersection in rhombic_dodecahedron
3. Increase level-set resolution from n=6 to n=15
4. Change Boolean from union (+) to subtraction (-) for inner shell
"""

import math
import json
import numpy as np
from manifold3d import Manifold


def gyroid_sdf(x, y, z):
    """Implicit function for a gyroid TPMS surface with correct phase shift."""
    xi = x - math.pi / 4.0
    yi = y - math.pi / 4.0
    zi = z - math.pi / 4.0
    return (
        math.cos(xi) * math.sin(yi)
        + math.cos(yi) * math.sin(zi)
        + math.cos(zi) * math.sin(xi)
    )


def gyroid_levelset(level, period, size, n):
    """Generate a level set of the gyroid at the given ISO value."""
    return Manifold.level_set(
        gyroid_sdf,
        [-period, -period, -period, period, period, period],
        period / n,
        level,
    ).scale([size / period] * 3)


def rhombic_dodecahedron(size):
    """Construct a rhombic dodecahedron bounding volume via three box intersections."""
    box = Manifold.cube(
        (size * math.sqrt(2.0) * np.array([1, 1, 2])).tolist(), True
    )
    result = box.rotate([90, 45, 0]) ^ box.rotate([90, 45, 90])
    return result ^ box.rotate([0, 0, 45])


def build_module(size=20, n=15):
    """Build the gyroid module solid."""
    period = math.pi * 2.0
    outer = gyroid_levelset(-0.4, period, size, n)
    inner = gyroid_levelset(0.4, period, size, n)
    rd = rhombic_dodecahedron(size)
    result = (outer ^ rd) - inner
    return result.rotate([-45, 0, 90]).translate([0, 0, size / math.sqrt(2.0)])


def main():
    solid = build_module()

    genus = solid.genus()
    volume = solid.volume()
    surface_area = solid.surface_area()
    num_vert = solid.num_vert()
    num_tri = solid.num_tri()
    components = solid.decompose()
    num_components = len(components)

    status = solid.status()
    try:
        from manifold3d import Error
        is_valid = status == Error.NoError
    except ImportError:
        is_valid = (status.value == 0) if hasattr(status, 'value') else (status == 0)

    output = {
        "genus": int(genus),
        "volume": round(float(volume), 6),
        "surface_area": round(float(surface_area), 6),
        "num_vert": int(num_vert),
        "num_tri": int(num_tri),
        "num_components": int(num_components),
        "is_valid": bool(is_valid),
    }

    with open("/app/result.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Result written to /app/result.json")
    for k, v in output.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
