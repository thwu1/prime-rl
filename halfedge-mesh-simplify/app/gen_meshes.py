#!/usr/bin/env python3
"""Generate test mesh OBJ files during Docker build.

Uses only the standard library (no numpy) so it can run before
pip packages are installed.

"""

import os
import math


def write_obj(path, vertices, faces):
    with open(path, 'w') as f:
        f.write("# Generated mesh\n")
        for v in vertices:
            f.write(f"v {v[0]:.10g} {v[1]:.10g} {v[2]:.10g}\n")
        for face in faces:
            f.write("f " + " ".join(str(i + 1) for i in face) + "\n")


def main():
    os.makedirs("/app/meshes", exist_ok=True)

    # -- tetrahedron: 4 vertices, 4 faces --
    write_obj("/app/meshes/tetrahedron.obj",
              [(1, 1, 1), (-1, -1, 1), (-1, 1, -1), (1, -1, -1)],
              [[0, 1, 2], [0, 2, 3], [0, 3, 1], [1, 3, 2]])

    # -- octahedron: 6 vertices, 8 faces --
    oct_v = [(1, 0, 0), (-1, 0, 0), (0, 1, 0),
             (0, -1, 0), (0, 0, 1), (0, 0, -1)]
    oct_f = [[4, 0, 2], [4, 2, 1], [4, 1, 3], [4, 3, 0],
             [5, 2, 0], [5, 1, 2], [5, 3, 1], [5, 0, 3]]
    write_obj("/app/meshes/octahedron.obj", oct_v, oct_f)

    # -- icosahedron: 12 vertices, 20 faces --
    phi = (1.0 + math.sqrt(5.0)) / 2.0
    ico_v = [
        (-1, phi, 0), (1, phi, 0), (-1, -phi, 0), (1, -phi, 0),
        (0, -1, phi), (0, 1, phi), (0, -1, -phi), (0, 1, -phi),
        (phi, 0, -1), (phi, 0, 1), (-phi, 0, -1), (-phi, 0, 1),
    ]
    ico_f = [
        [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
        [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
        [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
        [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
    ]
    write_obj("/app/meshes/icosahedron.obj", ico_v, ico_f)

    # -- sphere32: subdivided octahedron, 18 vertices, 32 faces --
    edge_mids = {}
    new_v = list(oct_v)

    def get_mid(a, b):
        key = (min(a, b), max(a, b))
        if key not in edge_mids:
            va, vb = oct_v[a], oct_v[b]
            mid = ((va[0]+vb[0])/2, (va[1]+vb[1])/2, (va[2]+vb[2])/2)
            idx = len(new_v)
            new_v.append(mid)
            edge_mids[key] = idx
        return edge_mids[key]

    new_f = []
    for face in oct_f:
        a, b, c = face
        ab = get_mid(a, b)
        bc = get_mid(b, c)
        ca = get_mid(c, a)
        new_f.extend([[a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]])

    write_obj("/app/meshes/sphere32.obj", new_v, new_f)

    print("Generated: tetrahedron.obj, octahedron.obj, icosahedron.obj, sphere32.obj")


if __name__ == "__main__":
    main()
