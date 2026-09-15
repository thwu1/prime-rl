#!/usr/bin/env python3
"""Fix all 6 bugs in the SDF scene renderer.

Bug 1 (primitives.py, sd_torus): abs(q) - r  -->  sqrt(q*q + py*py) - r
Bug 2 (primitives.py, sd_octahedron): m * 0.5  -->  m * 0.57735027
Bug 3 (operations.py, smin_poly): missing k *= 4.0 scaling
Bug 4 (scene.py, _twist_y): wrong rotation plane (XY instead of XZ)
Bug 5 (scene.py, scene_sdf): max(d_carve, d_box) --> max(-d_carve, d_box)
Bug 6 (main.py, compute_normal): epsilon 0.1 --> 5e-4
"""

import re

def fix_file(path, replacements):
    with open(path, "r") as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            raise ValueError(f"Pattern not found in {path}: {old!r}")
        content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print(f"Fixed {path}: {len(replacements)} replacement(s)")

# Bug 1: Torus SDF — was computing cylindrical shell distance instead of torus
fix_file("/app/primitives.py", [
    (
        "    q = math.sqrt(px * px + pz * pz) - R\n    return abs(q) - r",
        "    q = math.sqrt(px * px + pz * pz) - R\n    return math.sqrt(q * q + py * py) - r"
    ),
])

# Bug 2: Octahedron SDF — wrong normalization constant
fix_file("/app/primitives.py", [
    (
        "return m * 0.5",
        "return m * 0.57735027"
    ),
])

# Bug 3: Smooth minimum — missing k *= 4.0 scaling
fix_file("/app/operations.py", [
    (
        "    h = max(k - abs(d1 - d2), 0.0)\n    return min(d1, d2) - h * h / (4.0 * k)",
        "    k *= 4.0\n    h = max(k - abs(d1 - d2), 0.0)\n    return min(d1, d2) - h * h / (4.0 * k)"
    ),
])

# Bug 4: Twist — was rotating in XY plane instead of XZ
fix_file("/app/scene.py", [
    (
        "    return c * px - s * py, s * px + c * py, pz",
        "    return c * px + s * pz, py, -s * px + c * pz"
    ),
])

# Bug 5: CSG subtraction — missing negation of carve distance
fix_file("/app/scene.py", [
    (
        "    d_carved = max(d_carve, d_box)",
        "    d_carved = max(-d_carve, d_box)"
    ),
])

# Bug 6: Normal computation epsilon too large
fix_file("/app/main.py", [
    (
        "    e = 0.1",
        "    e = 5e-4"
    ),
])

print("All 6 bugs fixed.")
