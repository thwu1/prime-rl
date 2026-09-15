"""
Generates 2D unstructured triangular meshes on an annular domain.
Interior nodes are randomly perturbed to create non-orthogonality.
Output is JSON with node coordinates, cell connectivity, face data, and boundary info.
"""

import json
import math
import random
import sys


def generate_mesh(n_angular, n_radial, r_inner=0.5, r_outer=2.0,
                  perturbation=0.2, seed=42):
    random.seed(seed)

    nodes = []
    node_ids = {}

    for ir in range(n_radial + 1):
        r = r_inner + (r_outer - r_inner) * ir / n_radial
        for it in range(n_angular):
            theta = 2 * math.pi * it / n_angular
            x = r * math.cos(theta)
            y = r * math.sin(theta)
            nid = len(nodes)
            node_ids[(ir, it)] = nid
            nodes.append([x, y])

    # Perturb interior nodes (not on inner/outer boundaries)
    h = (r_outer - r_inner) / n_radial
    for ir in range(1, n_radial):
        for it in range(n_angular):
            nid = node_ids[(ir, it)]
            dx = perturbation * h * (random.random() - 0.5)
            dy = perturbation * h * (random.random() - 0.5)
            nodes[nid][0] += dx
            nodes[nid][1] += dy

    # Generate triangular cells by splitting each quad into 2 triangles
    cells = []
    for ir in range(n_radial):
        for it in range(n_angular):
            it_next = (it + 1) % n_angular
            n0 = node_ids[(ir, it)]
            n1 = node_ids[(ir, it_next)]
            n2 = node_ids[(ir + 1, it_next)]
            n3 = node_ids[(ir + 1, it)]
            cells.append([n0, n1, n2])
            cells.append([n0, n2, n3])

    # Build face list with owner/neighbour connectivity
    face_map = {}
    faces = []
    face_cells = []

    for ci, cell in enumerate(cells):
        for i in range(3):
            na = cell[i]
            nb = cell[(i + 1) % 3]
            edge = (min(na, nb), max(na, nb))
            if edge in face_map:
                fi = face_map[edge]
                face_cells[fi][1] = ci
            else:
                fi = len(faces)
                face_map[edge] = fi
                faces.append([na, nb])
                face_cells.append([ci, -1])

    # Classify boundary faces
    inner_boundary_faces = []
    outer_boundary_faces = []
    for fi, fc in enumerate(face_cells):
        if fc[1] == -1:
            na, nb = faces[fi]
            r1 = math.sqrt(nodes[na][0]**2 + nodes[na][1]**2)
            r2 = math.sqrt(nodes[nb][0]**2 + nodes[nb][1]**2)
            r_avg = (r1 + r2) / 2.0
            if abs(r_avg - r_inner) < abs(r_avg - r_outer):
                inner_boundary_faces.append(fi)
            else:
                outer_boundary_faces.append(fi)

    return {
        "nodes": nodes,
        "cells": cells,
        "faces": faces,
        "face_cells": face_cells,
        "inner_boundary_faces": inner_boundary_faces,
        "outer_boundary_faces": outer_boundary_faces,
        "r_inner": r_inner,
        "r_outer": r_outer,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 mesh_generator.py <level> [seed]")
        print("  level: 1 (coarse), 2 (medium), 3 (fine), 4 (validation)")
        sys.exit(1)

    level = int(sys.argv[1])
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42

    configs = {
        1: (8, 4),
        2: (16, 8),
        3: (32, 16),
        4: (24, 12),
    }
    if level not in configs:
        print(f"Invalid level {level}. Use 1-4.")
        sys.exit(1)

    n_angular, n_radial = configs[level]
    mesh = generate_mesh(n_angular, n_radial, seed=seed)

    outfile = f"mesh_level_{level}.json"
    with open(outfile, "w") as f:
        json.dump(mesh, f)

    n_cells = len(mesh["cells"])
    n_faces = len(mesh["faces"])
    n_inner = len(mesh["inner_boundary_faces"])
    n_outer = len(mesh["outer_boundary_faces"])
    print(f"Level {level}: {n_cells} cells, {n_faces} faces, "
          f"{n_inner} inner bfaces, {n_outer} outer bfaces")
    print(f"Saved to {outfile}")


if __name__ == "__main__":
    main()
