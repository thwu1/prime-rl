#!/usr/bin/env python3
"""Generate sample mesh pairs for pipeline testing."""
import os

import numpy as np
import trimesh

os.makedirs("/app/meshes", exist_ok=True)

# Pair A: Identical cubes
box = trimesh.creation.box(extents=[20, 20, 20])
box.export("/app/meshes/pair_A_gen.stl")
box.export("/app/meshes/pair_A_ref.stl")

# Pair B: Translated box (same shape, offset 100mm each axis)
translated = box.copy()
translated.apply_translation([100, 100, 100])
translated.export("/app/meshes/pair_B_gen.stl")
box.export("/app/meshes/pair_B_ref.stl")

# Pair C: Non-watertight generated mesh (faces removed)
faces_c = box.faces[:-4]
broken = trimesh.Trimesh(vertices=box.vertices, faces=faces_c, process=False)
broken.export("/app/meshes/pair_C_gen.stl")
box.export("/app/meshes/pair_C_ref.stl")

# Pair D: Two disconnected components vs single
box1 = trimesh.creation.box(extents=[10, 10, 10])
box2 = trimesh.creation.box(extents=[10, 10, 10])
box2.apply_translation([50, 0, 0])
combined = trimesh.util.concatenate([box1, box2])
combined.export("/app/meshes/pair_D_gen.stl")
box1.export("/app/meshes/pair_D_ref.stl")

# Pair E: Volume mismatch (50% larger)
big = trimesh.creation.box(extents=[10, 10, 15])
small = trimesh.creation.box(extents=[10, 10, 10])
big.export("/app/meshes/pair_E_gen.stl")
small.export("/app/meshes/pair_E_ref.stl")

# Pair F: Mesh with duplicate triangles (geometrically watertight)
box_f = trimesh.creation.box(extents=[20, 20, 20])
dup_faces = np.vstack([box_f.faces, box_f.faces[:2]])
dup_mesh = trimesh.Trimesh(vertices=box_f.vertices, faces=dup_faces, process=False)
dup_mesh.export("/app/meshes/pair_F_gen.stl")
box_f.export("/app/meshes/pair_F_ref.stl")
