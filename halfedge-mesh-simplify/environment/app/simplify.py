"""
Mesh decimation tool.

Reduces the face count of a triangle mesh while preserving
geometric fidelity and manifold validity.

Usage: python3 simplify.py <input.obj> <target_face_count> <output.obj>

"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from halfedge import HalfedgeMesh
from obj_io import read_obj, write_obj


def main():
    if len(sys.argv) != 4:
        print("Usage: python3 simplify.py <input.obj> <target_faces> <output.obj>",
              file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    target = max(4, int(sys.argv[2]))
    output_path = sys.argv[3]

    mesh = read_obj(input_path)

    # TODO: Implement decimation that reduces mesh.n_faces() to at most target
    # while keeping the mesh a valid closed manifold (mesh.validate() == [])

    write_obj(mesh, output_path)


if __name__ == "__main__":
    main()
