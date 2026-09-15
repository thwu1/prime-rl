#!/usr/bin/env python3
"""Generate reference and candidate STL models for the geometric evaluation task.

Creates simple CAD-like primitives: boxes, cylinders, cones, spheres.
Candidates include exact matches (different tessellation), wrong-dimension variants,
a completely wrong shape, a degenerate (invalid) mesh, and an asymmetric containment pair.
"""
import trimesh
import numpy as np
import os

os.makedirs('/app/models/references', exist_ok=True)
os.makedirs('/app/models/candidates', exist_ok=True)

# ===== Reference Models =====

ref_box = trimesh.creation.box(extents=[50.0, 40.0, 30.0])
ref_box.export('/app/models/references/ref_box.stl')

ref_cyl = trimesh.creation.cylinder(radius=25.0, height=50.0, sections=64)
ref_cyl.export('/app/models/references/ref_cylinder.stl')

ref_cone = trimesh.creation.cone(radius=30.0, height=40.0, sections=64)
ref_cone.export('/app/models/references/ref_cone.stl')

ref_sphere_small = trimesh.creation.icosphere(radius=8.0, subdivisions=3)
ref_sphere_small.export('/app/models/references/ref_sphere_small.stl')

# ===== Candidate Models =====

# Cand 1 (pair_1): Match box -- same geometry, subdivided tessellation
cand_box_m = trimesh.creation.box(extents=[50.0, 40.0, 30.0])
v_sub, f_sub = trimesh.remesh.subdivide(cand_box_m.vertices, cand_box_m.faces)
cand_box_m = trimesh.Trimesh(vertices=v_sub, faces=f_sub)
cand_box_m.export('/app/models/candidates/cand_box_match.stl')

# Cand 2 (pair_2): Wrong box -- X dimension 65 instead of 50
cand_box_w = trimesh.creation.box(extents=[65.0, 40.0, 30.0])
cand_box_w.export('/app/models/candidates/cand_box_wrong.stl')

# Cand 3 (pair_3): Match cylinder -- same dims, 32 sections (different tessellation)
cand_cyl_m = trimesh.creation.cylinder(radius=25.0, height=50.0, sections=32)
cand_cyl_m.export('/app/models/candidates/cand_cyl_match.stl')

# Cand 4 (pair_4): Wrong cylinder -- radius=18 (instead of 25), same height
cand_cyl_w = trimesh.creation.cylinder(radius=18.0, height=50.0, sections=64)
cand_cyl_w.export('/app/models/candidates/cand_cyl_wrong.stl')

# Cand 5 (pair_5): Match cone -- same dims, 32 sections
cand_cone_m = trimesh.creation.cone(radius=30.0, height=40.0, sections=32)
cand_cone_m.export('/app/models/candidates/cand_cone_match.stl')

# Cand 6 (pair_6): Sphere radius=25 (completely wrong shape for cone reference)
cand_sphere = trimesh.creation.icosphere(radius=25.0, subdivisions=3)
cand_sphere.export('/app/models/candidates/cand_sphere.stl')

# Cand 7 (pair_7): Invalid/degenerate mesh -- flat open surface (not watertight, zero volume)
invalid_verts = np.array([
    [0.0, 0.0, 0.0],
    [10.0, 0.0, 0.0],
    [10.0, 10.0, 0.0],
    [0.0, 10.0, 0.0],
], dtype=np.float64)
invalid_faces = np.array([[0, 1, 2], [0, 2, 3]])
cand_invalid = trimesh.Trimesh(vertices=invalid_verts, faces=invalid_faces)
cand_invalid.export('/app/models/candidates/cand_invalid.stl')

# Cand 8 (pair_8): Large box for asymmetric containment test with small sphere
cand_box_large = trimesh.creation.box(extents=[50.0, 40.0, 30.0])
cand_box_large.export('/app/models/candidates/cand_box_large.stl')

print("All models generated successfully.")
for name, mesh in [
    ('ref_box', ref_box),
    ('ref_cylinder', ref_cyl),
    ('ref_cone', ref_cone),
    ('ref_sphere_small', ref_sphere_small),
    ('cand_box_match', cand_box_m),
    ('cand_box_wrong', cand_box_w),
    ('cand_cyl_match', cand_cyl_m),
    ('cand_cyl_wrong', cand_cyl_w),
    ('cand_cone_match', cand_cone_m),
    ('cand_sphere', cand_sphere),
    ('cand_box_large', cand_box_large),
]:
    print(f"  {name}: {len(mesh.faces)} faces, volume={mesh.volume:.1f}")
print(f"  cand_invalid: {len(cand_invalid.faces)} faces (degenerate)")
