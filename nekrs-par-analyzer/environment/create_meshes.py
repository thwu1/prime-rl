#!/usr/bin/env python3
"""Generate Gmsh mesh files for nekRS auditor test cases.

Creates structured 2D quad meshes for each case directory.
Meshes are uniform (no grading) for deterministic element sizes.
"""
import gmsh
import math
import shutil
import os


def create_rect_mesh(output_path, xmin, xmax, ymin, ymax, nx, ny,
                     boundary_names):
    """Create a structured rectangular quad mesh with physical groups.

    Parameters
    ----------
    output_path : str
        Path to write the .msh file.
    xmin, xmax, ymin, ymax : float
        Domain extents.
    nx, ny : int
        Element counts in x and y.
    boundary_names : list of str
        Names for [bottom, right, top, left] physical groups.
    """
    gmsh.initialize()
    gmsh.option.setNumber("General.Verbosity", 0)
    gmsh.model.add("mesh")

    # Corner points
    p1 = gmsh.model.geo.addPoint(xmin, ymin, 0)
    p2 = gmsh.model.geo.addPoint(xmax, ymin, 0)
    p3 = gmsh.model.geo.addPoint(xmax, ymax, 0)
    p4 = gmsh.model.geo.addPoint(xmin, ymax, 0)

    # Edges: bottom, right, top, left
    l_bot = gmsh.model.geo.addLine(p1, p2)
    l_rgt = gmsh.model.geo.addLine(p2, p3)
    l_top = gmsh.model.geo.addLine(p3, p4)
    l_lft = gmsh.model.geo.addLine(p4, p1)

    cl = gmsh.model.geo.addCurveLoop([l_bot, l_rgt, l_top, l_lft])
    surf = gmsh.model.geo.addPlaneSurface([cl])

    # Transfinite (structured) mesh — uniform spacing
    gmsh.model.geo.mesh.setTransfiniteCurve(l_bot, nx + 1)
    gmsh.model.geo.mesh.setTransfiniteCurve(l_top, nx + 1)
    gmsh.model.geo.mesh.setTransfiniteCurve(l_rgt, ny + 1)
    gmsh.model.geo.mesh.setTransfiniteCurve(l_lft, ny + 1)
    gmsh.model.geo.mesh.setTransfiniteSurface(surf)
    gmsh.model.geo.mesh.setRecombine(2, surf)  # quads

    gmsh.model.geo.synchronize()

    # Physical groups with explicit tags (1-based)
    lines = [l_bot, l_rgt, l_top, l_lft]
    for i, (line, name) in enumerate(zip(lines, boundary_names)):
        gmsh.model.addPhysicalGroup(1, [line], tag=i + 1, name=name)
    gmsh.model.addPhysicalGroup(2, [surf], tag=5, name="domain")

    gmsh.model.mesh.generate(2)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    gmsh.write(output_path)
    gmsh.finalize()


# ---- RBC: [0, 4] x [0, 1], 20x12 ----
create_rect_mesh(
    "/app/cases/rbc_valid/mesh.msh",
    0, 4, 0, 1, 20, 12,
    ["hot_wall", "periodic_right", "cold_wall", "periodic_left"],
)

# ---- RANS pipe: [0, 8] x [0, 1], 24x16 ----
create_rect_mesh(
    "/app/cases/rans_valid/mesh.msh",
    0, 8, 0, 1, 24, 16,
    ["wall", "periodic_out", "symmetry", "periodic_in"],
)

# ---- CHT box: [0, 2] x [0, 1], 20x10 ----
create_rect_mesh(
    "/app/cases/cht_valid/mesh.msh",
    0, 2, 0, 1, 20, 10,
    ["heated_wall", "insulated_right", "cooled_wall", "insulated_left"],
)

# ---- Pipe flow: [0, 2*pi] x [0, 1], 16x10 ----
create_rect_mesh(
    "/app/cases/pipe_valid/mesh.msh",
    0, 2 * math.pi, 0, 1, 16, 10,
    ["wall", "periodic_out", "symmetry", "periodic_in"],
)

# Copy meshes to broken case directories (same geometry, broken .par)
for base in ["rbc", "rans", "cht", "pipe"]:
    src = "/app/cases/{}_valid/mesh.msh".format(base)
    dst_dir = "/app/cases/{}_broken".format(base)
    os.makedirs(dst_dir, exist_ok=True)
    shutil.copy2(src, os.path.join(dst_dir, "mesh.msh"))

print("All meshes generated successfully.")
