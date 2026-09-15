#!/usr/bin/env python3
"""Fix all 6 bugs in the SDF rendering pipeline.

Bug 1 (Makefile): SRCS missing src/sdf_ops.c — smin_poly not in library
Bug 2 (sdf_prims.c, sd_torus): fabs(q)-r instead of sqrt(q*q+py*py)-r
Bug 3 (sdf_prims.c, sd_octahedron): stub returning bound approximation —
      needs full exact implementation with 3-branch exterior distance
Bug 4 (sdf_ops.c, smin_poly): stub returning min(d1,d2) —
      needs polynomial smooth minimum with k*=4.0 scaling
Bug 5 (scene.py, _twist_y): wrong rotation plane (XY instead of XZ)
Bug 6 (scene.py, scene_sdf): max(d_carve,d_box) instead of max(-d_carve,d_box)
"""

import sys

# ── Bug 1: Makefile — add sdf_ops.c to source list ──────────────────────────

with open("/app/Makefile", "r") as f:
    content = f.read()
content = content.replace("SRCS = src/sdf_prims.c\n",
                           "SRCS = src/sdf_prims.c src/sdf_ops.c\n")
with open("/app/Makefile", "w") as f:
    f.write(content)
print("Fixed Makefile: added sdf_ops.c to SRCS")

# ── Bugs 2-3: Write complete corrected sdf_prims.c ──────────────────────────
# Writes the full file to avoid fragile multi-line pattern matching.
# Bug 2: sd_torus — fabs(q)-r corrected to sqrt(q*q+py*py)-r
# Bug 3: sd_octahedron — stub replaced with exact IQ octahedron SDF

CORRECTED_PRIMS = """\
#include <math.h>
#include "sdf.h"

double sd_sphere(double px, double py, double pz, double r) {
    return sqrt(px*px + py*py + pz*pz) - r;
}

double sd_torus(double px, double py, double pz, double R, double r) {
    double q = sqrt(px*px + pz*pz) - R;
    return sqrt(q*q + py*py) - r;
}

double sd_round_box(double px, double py, double pz,
                    double bx, double by, double bz, double rad) {
    double qx = fabs(px) - bx;
    double qy = fabs(py) - by;
    double qz = fabs(pz) - bz;
    double mx = qx > 0.0 ? qx : 0.0;
    double my = qy > 0.0 ? qy : 0.0;
    double mz = qz > 0.0 ? qz : 0.0;
    double outer = sqrt(mx*mx + my*my + mz*mz);
    double inner_xy = qx > qy ? qx : qy;
    double inner = inner_xy > qz ? inner_xy : qz;
    if (inner > 0.0) inner = 0.0;
    return outer + inner - rad;
}

double sd_octahedron(double px, double py, double pz, double s) {
    px = fabs(px);
    py = fabs(py);
    pz = fabs(pz);
    double m = px + py + pz - s;
    double qx, qy, qz;
    if (3.0 * px < m) {
        qx = px; qy = py; qz = pz;
    } else if (3.0 * py < m) {
        qx = py; qy = pz; qz = px;
    } else if (3.0 * pz < m) {
        qx = pz; qy = px; qz = py;
    } else {
        return m * 0.57735027;
    }
    double k = 0.5 * (qz - qy + s);
    if (k < 0.0) k = 0.0;
    if (k > s) k = s;
    double a = qx;
    double b = qy - s + k;
    double c = qz - k;
    return sqrt(a*a + b*b + c*c);
}
"""

with open("/app/src/sdf_prims.c", "w") as f:
    f.write(CORRECTED_PRIMS)
print("Fixed sdf_prims.c: corrected torus and octahedron SDFs")

# ── Bug 4: Write complete corrected sdf_ops.c ───────────────────────────────
# Polynomial smooth minimum with k*=4.0 scaling convention.

CORRECTED_OPS = """\
#include <math.h>
#include "sdf.h"

double smin_poly(double d1, double d2, double k) {
    k *= 4.0;
    double h = k - fabs(d1 - d2);
    if (h < 0.0) h = 0.0;
    double m = d1 < d2 ? d1 : d2;
    return m - h * h / (4.0 * k);
}
"""

with open("/app/src/sdf_ops.c", "w") as f:
    f.write(CORRECTED_OPS)
print("Fixed sdf_ops.c: implemented polynomial smooth minimum")

# ── Bugs 5-6: scene.py — twist plane + CSG subtraction ──────────────────────

with open("/app/scene.py", "r") as f:
    content = f.read()

# Bug 5: twist was rotating in XY plane instead of XZ
old_twist = "return c * px - s * py, s * px + c * py, pz"
new_twist = "return c * px + s * pz, py, -s * px + c * pz"
if old_twist not in content:
    print("WARNING: twist pattern not found", file=sys.stderr)
else:
    content = content.replace(old_twist, new_twist)

# Bug 6: CSG subtraction missing negation of carve distance
old_csg = "d_carved = max(d_carve, d_box)"
new_csg = "d_carved = max(-d_carve, d_box)"
if old_csg not in content:
    print("WARNING: CSG pattern not found", file=sys.stderr)
else:
    content = content.replace(old_csg, new_csg)

with open("/app/scene.py", "w") as f:
    f.write(content)
print("Fixed scene.py: corrected twist rotation and CSG subtraction")

print("All 6 bugs fixed.")
