#!/usr/bin/env python3
"""
CLI mesh inspector.  Reads a Wavefront OBJ file and prints mesh
properties as JSON to stdout.

Usage:  python3 mesh_stats.py <file.obj>

"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from halfedge import HalfedgeMesh
from obj_io import read_obj


def mesh_stats(path):
    mesh = read_obj(path)
    V = mesh.n_vertices()
    E = mesh.n_edges()
    F = mesh.n_faces()
    errors = mesh.validate()

    positions = [mesh.vertices[vid].position for vid in mesh.vertices]
    if positions:
        all_pos = np.array(positions)
        bbox_min = all_pos.min(axis=0).tolist()
        bbox_max = all_pos.max(axis=0).tolist()
        centroid = all_pos.mean(axis=0).tolist()
    else:
        bbox_min = bbox_max = centroid = [0.0, 0.0, 0.0]

    return {
        "file": os.path.basename(path),
        "vertex_count": V,
        "edge_count": E,
        "face_count": F,
        "euler_characteristic": V - E + F,
        "is_valid": len(errors) == 0,
        "validation_errors": errors[:10],
        "bounding_box": {"min": bbox_min, "max": bbox_max},
        "centroid": centroid,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 mesh_stats.py <file.obj>", file=sys.stderr)
        sys.exit(1)
    stats = mesh_stats(sys.argv[1])
    print(json.dumps(stats, indent=2))
