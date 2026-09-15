#!/usr/bin/env python3

"""Diagnose and fix bugs in the mesh validation pipeline.

Reads /app/mesh_validator.py, identifies 5 independent bugs through
code analysis, and applies targeted corrections.
"""

import sys

with open("/app/mesh_validator.py") as f:
    code = f.read()

original = code

# --- Fix 1: check_watertight must clean mesh before manifold test ---
# Without cleaning, duplicate/degenerate triangles create non-manifold
# edges that cause false negatives on geometrically watertight meshes.
code = code.replace(
    "    if not mesh.has_triangles():\n"
    "        return False\n"
    "    return mesh.is_watertight()",

    "    if not mesh.has_triangles():\n"
    "        return False\n"
    "    mesh = clean_mesh(mesh)\n"
    "    if not mesh.has_triangles():\n"
    "        return False\n"
    "    return mesh.is_watertight()",
    1,
)

# --- Fix 2: compute_volumes must guard against non-watertight meshes ---
# The divergence theorem volume is meaningless for open meshes. Without
# a watertight guard, garbage volumes pass the threshold check.
code = code.replace(
    "    gen_vol = float(gen_mesh.volume)\n"
    "    ref_vol = float(ref_mesh.volume)",

    "    if not gen_mesh.is_watertight or not ref_mesh.is_watertight:\n"
    "        gen_vol = float(abs(gen_mesh.volume)) if gen_mesh.is_watertight else None\n"
    "        ref_vol = float(abs(ref_mesh.volume)) if ref_mesh.is_watertight else None\n"
    "        return gen_vol, ref_vol, None, None\n"
    "    gen_vol = float(abs(gen_mesh.volume))\n"
    "    ref_vol = float(abs(ref_mesh.volume))",
)

# --- Fix 3: voxel_size for registration is 10x too large ---
# At 50.0mm, the downsampled point cloud has too few points for FPFH
# feature computation, destroying global registration for translated meshes.
code = code.replace("voxel_size = 50.0", "voxel_size = 5.0")

# --- Fix 4: Chamfer distance must be bidirectional ---
# Using only gen->ref underestimates distance for asymmetric shapes.
# Correct: average of mean distances in both directions.
code = code.replace(
    "chamfer = float(np.mean(dist_gen_to_ref))",
    "chamfer = float((np.mean(dist_gen_to_ref) + np.mean(dist_ref_to_gen)) / 2.0)",
)

# --- Fix 5: Bounding box extents must be sorted before comparison ---
# After alignment, axes may be permuted. Comparing raw x/y/z extents
# fails when the alignment rotates the mesh. Sorting makes comparison
# axis-invariant.
code = code.replace(
    "gen_dims = list(gen_tm.bounding_box.extents)",
    "gen_dims = sorted(gen_tm.bounding_box.extents)",
)
code = code.replace(
    "ref_dims = list(ref_tm.bounding_box.extents)",
    "ref_dims = sorted(ref_tm.bounding_box.extents)",
)

if code == original:
    print("ERROR: No fixes were applied", file=sys.stderr)
    sys.exit(1)

with open("/app/mesh_validator.py", "w") as f:
    f.write(code)

print("Applied 5 fixes to /app/mesh_validator.py")
