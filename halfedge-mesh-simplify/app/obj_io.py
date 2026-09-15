"""
Wavefront OBJ file reader and writer for HalfedgeMesh.

"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from halfedge import HalfedgeMesh


def read_obj(path):
    """Read a Wavefront OBJ file and return a HalfedgeMesh.

    Handles ``v`` (vertex) and ``f`` (face) records.
    Face indices may use v/vt/vn notation; only the vertex index is used.
    """
    vertices = []
    faces = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if not parts or parts[0].startswith('#'):
                continue
            if parts[0] == 'v' and len(parts) >= 4:
                vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif parts[0] == 'f':
                face = []
                for p in parts[1:]:
                    idx = int(p.split('/')[0])
                    if idx < 0:
                        idx = len(vertices) + idx + 1
                    face.append(idx - 1)
                faces.append(face)
    return HalfedgeMesh.from_indexed_faces(vertices, faces)


def write_obj(mesh, path):
    """Write a HalfedgeMesh to a Wavefront OBJ file."""
    positions, faces = mesh.to_indexed_faces()
    with open(path, 'w') as f:
        f.write("# Wavefront OBJ\n")
        for p in positions:
            f.write(f"v {p[0]:.10g} {p[1]:.10g} {p[2]:.10g}\n")
        for face in faces:
            f.write("f " + " ".join(str(i + 1) for i in face) + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 obj_io.py <file.obj> [output.obj]", file=sys.stderr)
        sys.exit(1)
    mesh = read_obj(sys.argv[1])
    print(f"Vertices: {mesh.n_vertices()}")
    print(f"Edges:    {mesh.n_edges()}")
    print(f"Faces:    {mesh.n_faces()}")
    errors = mesh.validate()
    if errors:
        print(f"Validation errors ({len(errors)}):")
        for e in errors:
            print(f"  {e}")
    else:
        print("Valid: yes")
    if len(sys.argv) >= 3:
        write_obj(mesh, sys.argv[2])
        print(f"Wrote {sys.argv[2]}")
