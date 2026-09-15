#!/usr/bin/env python3
"""Marching Tetrahedra Pipeline for Isosurface Extraction with Topological Analysis."""

import numpy as np
import json
from itertools import permutations

# ---------------------------------------------------------------------------
# Tetrahedron edge definitions: 6 edges of a tet with vertices (v0,v1,v2,v3)
# ---------------------------------------------------------------------------
TET_EDGES = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]

# ---------------------------------------------------------------------------
# Marching Tetrahedra lookup table
# Key = 4-bit sign config (bit i = 1 if vertex i is INSIDE, i.e. SDF < 0)
# Value = list of triangles; each triangle = tuple of 3 edge indices
# ---------------------------------------------------------------------------
MT_TABLE = [
    [],                            # 0:  0000 - all outside
    [(0, 1, 2)],                   # 1:  0001 - v0 inside
    [(0, 3, 4)],                   # 2:  0010 - v1 inside
    [(1, 2, 4), (1, 4, 3)],        # 3:  0011 - v0,v1 inside
    [(1, 5, 3)],                   # 4:  0100 - v2 inside
    [(0, 2, 5), (0, 5, 3)],        # 5:  0101 - v0,v2 inside
    [(0, 1, 5), (0, 5, 4)],        # 6:  0110 - v1,v2 inside
    [(2, 4, 5)],                   # 7:  0111 - v3 outside
    [(2, 5, 4)],                   # 8:  1000 - v3 inside
    [(0, 5, 1), (0, 4, 5)],        # 9:  1001 - v0,v3 inside
    [(0, 5, 2), (0, 3, 5)],        # 10: 1010 - v1,v3 inside
    [(1, 3, 5)],                   # 11: 1011 - v2 outside
    [(1, 4, 2), (1, 3, 4)],        # 12: 1100 - v2,v3 inside
    [(0, 4, 3)],                   # 13: 1101 - v1 outside
    [(0, 2, 1)],                   # 14: 1110 - v0 outside
    [],                            # 15: 1111 - all inside
]


# ---------------------------------------------------------------------------
# SDF primitives
# ---------------------------------------------------------------------------
def sdf_sphere(pts, radius=0.6):
    return np.linalg.norm(pts, axis=1) - radius


def sdf_torus(pts, R=0.5, r=0.2):
    x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
    q = np.sqrt(x ** 2 + y ** 2) - R
    return np.sqrt(q ** 2 + z ** 2) - r


def sdf_csg(pts):
    """Sphere (r=0.7) minus infinite cylinder (r=0.3 along Z axis)."""
    sphere = np.linalg.norm(pts, axis=1) - 0.7
    cyl = np.sqrt(pts[:, 0] ** 2 + pts[:, 1] ** 2) - 0.3
    return np.maximum(sphere, -cyl)


# ---------------------------------------------------------------------------
# Grid generation — Freudenthal (Kuhn) triangulation
# ---------------------------------------------------------------------------
def generate_grid(N, lo=-1.0, hi=1.0):
    """Create (N+1)^3 grid vertices and 6*N^3 Freudenthal tetrahedra."""
    lin = np.linspace(lo, hi, N + 1)
    xs, ys, zs = np.meshgrid(lin, lin, lin, indexing="ij")
    vertices = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)

    s = N + 1
    s2 = s * s

    # Base corner (0,0,0) index for every cube
    ii, jj, kk = np.meshgrid(np.arange(N), np.arange(N), np.arange(N), indexing="ij")
    v000 = (ii.ravel() * s2 + jj.ravel() * s + kk.ravel()).astype(np.int64)

    strides = np.array([s2, s, 1], dtype=np.int64)

    # 6 permutations → 6 tets per cube
    all_tets = []
    for perm in permutations(range(3)):
        t0 = v000
        t1 = t0 + strides[perm[0]]
        t2 = t1 + strides[perm[1]]
        t3 = t2 + strides[perm[2]]
        all_tets.append(np.stack([t0, t1, t2, t3], axis=1))

    return vertices, np.concatenate(all_tets, axis=0)


# ---------------------------------------------------------------------------
# Marching Tetrahedra
# ---------------------------------------------------------------------------
def marching_tetrahedra(vertices, tets, sdf_values):
    """Extract isosurface with edge-based vertex deduplication."""
    # Perturb near-zero SDF values to avoid degenerate triangles at grid vertices
    # that lie exactly on the isosurface (e.g. sphere r=0.6 with grid step 0.05).
    sdf_values = sdf_values.copy()
    sdf_values[np.abs(sdf_values) < 1e-10] = 1e-10

    edge_cache = {}
    new_vertices = []
    triangles = []

    # Convert to native Python for faster inner loop
    tets_list = tets.tolist()
    sdf_list = sdf_values.tolist()

    for tet in tets_list:
        s = [sdf_list[v] for v in tet]
        case = 0
        for i in range(4):
            if s[i] < 0:
                case |= 1 << i

        tri_list = MT_TABLE[case]
        if not tri_list:
            continue

        # Resolve edge intersection vertices
        edge_verts = {}
        for tri in tri_list:
            for eidx in tri:
                if eidx in edge_verts:
                    continue
                a, b = TET_EDGES[eidx]
                va, vb = tet[a], tet[b]
                key = (va, vb) if va < vb else (vb, va)

                if key in edge_cache:
                    edge_verts[eidx] = edge_cache[key]
                else:
                    sa, sb = s[a], s[b]
                    denom = sa - sb
                    t = sa / denom if abs(denom) > 1e-15 else 0.5
                    pt = vertices[va] + t * (vertices[vb] - vertices[va])
                    idx = len(new_vertices)
                    new_vertices.append(pt)
                    edge_cache[key] = idx
                    edge_verts[eidx] = idx

        for tri in tri_list:
            triangles.append([edge_verts[e] for e in tri])

    if not new_vertices:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    return np.array(new_vertices), np.array(triangles, dtype=np.int64)


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------
def remove_degenerate_faces(vertices, faces):
    if len(faces) == 0:
        return faces
    v0 = vertices[faces[:, 0]]
    v1 = vertices[faces[:, 1]]
    v2 = vertices[faces[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
    return faces[areas > 1e-12]


# ---------------------------------------------------------------------------
# Topological analysis
# ---------------------------------------------------------------------------
def compute_topology(vertices, faces):
    if len(faces) == 0:
        return dict(num_vertices=0, num_faces=0, num_edges=0,
                    euler_characteristic=0, is_manifold=False, genus=-1)

    ref_verts = set()
    edge_face_count = {}
    for face in faces:
        f0, f1, f2 = int(face[0]), int(face[1]), int(face[2])
        ref_verts.update((f0, f1, f2))
        for a, b in ((f0, f1), (f1, f2), (f2, f0)):
            edge = (a, b) if a < b else (b, a)
            edge_face_count[edge] = edge_face_count.get(edge, 0) + 1

    V = len(ref_verts)
    E = len(edge_face_count)
    F = len(faces)
    chi = V - E + F

    is_manifold = all(c == 2 for c in edge_face_count.values())
    if is_manifold and (2 - chi) % 2 == 0 and chi <= 2:
        genus = (2 - chi) // 2
    else:
        genus = -1

    return dict(num_vertices=V, num_faces=F, num_edges=E,
                euler_characteristic=chi, is_manifold=is_manifold, genus=int(genus))


# ---------------------------------------------------------------------------
# Geometric analysis
# ---------------------------------------------------------------------------
def _unique_edge_lengths(vertices, faces):
    seen = set()
    lengths = []
    for face in faces:
        for i in range(3):
            a, b = int(face[i]), int(face[(i + 1) % 3])
            edge = (a, b) if a < b else (b, a)
            if edge not in seen:
                seen.add(edge)
                lengths.append(float(np.linalg.norm(vertices[a] - vertices[b])))
    return np.array(lengths)


def compute_geometry(vertices, faces):
    if len(faces) == 0:
        return dict(surface_area=0.0, centroid=[0.0, 0.0, 0.0],
                    mean_edge_length=0.0, edge_length_std=0.0)

    v0 = vertices[faces[:, 0]]
    v1 = vertices[faces[:, 1]]
    v2 = vertices[faces[:, 2]]
    cross = np.cross(v1 - v0, v2 - v0)
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    surface_area = float(areas.sum())

    tri_centroids = (v0 + v1 + v2) / 3.0
    if surface_area > 0:
        centroid = ((tri_centroids * areas[:, None]).sum(axis=0) / surface_area).tolist()
    else:
        centroid = tri_centroids.mean(axis=0).tolist()

    edge_lengths = _unique_edge_lengths(vertices, faces)
    return dict(surface_area=surface_area, centroid=centroid,
                mean_edge_length=float(edge_lengths.mean()),
                edge_length_std=float(edge_lengths.std()))


# ---------------------------------------------------------------------------
# Laplacian smoothing (umbrella operator, Jacobi iteration)
# ---------------------------------------------------------------------------
def laplacian_smooth(vertices, faces, iterations=10, weight=0.5):
    n = len(vertices)
    adj = [set() for _ in range(n)]
    for face in faces:
        f0, f1, f2 = int(face[0]), int(face[1]), int(face[2])
        adj[f0].update((f1, f2))
        adj[f1].update((f0, f2))
        adj[f2].update((f0, f1))
    adj_lists = [list(s) for s in adj]

    verts = vertices.copy()
    for _ in range(iterations):
        new_verts = verts.copy()
        for i in range(n):
            nbrs = adj_lists[i]
            if nbrs:
                avg = verts[nbrs].mean(axis=0)
                new_verts[i] = verts[i] + weight * (avg - verts[i])
        verts = new_verts
    return verts


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def process_scene(name, sdf_func, grid_vertices, tets):
    print(f"  Evaluating SDF for '{name}'...")
    sdf_values = sdf_func(grid_vertices)

    print(f"  Marching tetrahedra...")
    mesh_verts, mesh_faces = marching_tetrahedra(grid_vertices, tets, sdf_values)
    print(f"  Raw: {len(mesh_verts)} verts, {len(mesh_faces)} faces")

    # SDF perturbation in marching_tetrahedra prevents truly degenerate faces,
    # so skip removal — removing near-zero-area faces would break manifoldness.
    print(f"  Faces: {len(mesh_faces)}")

    topo = compute_topology(mesh_verts, mesh_faces)
    print(f"  chi={topo['euler_characteristic']} genus={topo['genus']} manifold={topo['is_manifold']}")

    geom = compute_geometry(mesh_verts, mesh_faces)
    print(f"  area={geom['surface_area']:.4f} centroid=[{', '.join(f'{c:.4f}' for c in geom['centroid'])}]")

    print(f"  Laplacian smoothing...")
    smoothed = laplacian_smooth(mesh_verts, mesh_faces)
    smoothed_std = float(_unique_edge_lengths(smoothed, mesh_faces).std())
    print(f"  edge_std: {geom['edge_length_std']:.6f} -> {smoothed_std:.6f}")

    return {**topo, **geom, "smoothed_edge_length_std": smoothed_std}


def main():
    resolution = 40
    output_path = "/app/result.json"

    print(f"Generating Freudenthal grid (res={resolution})...")
    grid_vertices, tets = generate_grid(resolution)
    print(f"Grid: {len(grid_vertices)} vertices, {len(tets)} tetrahedra")

    scenes = {
        "sphere": lambda pts: sdf_sphere(pts, radius=0.6),
        "torus": lambda pts: sdf_torus(pts, R=0.5, r=0.2),
        "csg": sdf_csg,
    }

    result = {}
    for name, sdf_func in scenes.items():
        print(f"\n=== {name} ===")
        result[name] = process_scene(name, sdf_func, grid_vertices, tets)

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nResults written to {output_path}")


if __name__ == "__main__":
    main()
