#!/usr/bin/env python3
"""
Generate a triply-periodic RVE mesh with spherical inclusions using Gmsh.

Geometry: unit cube with center sphere (r=0.2) and 8 corner spheres (r=0.25).
Physical groups: Matrix, CenterInclusion (1 vol), CornerInclusion (8 vols).
"""

import gmsh
import sys


def main():
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1)
    gmsh.model.add("rve")

    factory = gmsh.model.occ

    # ------------------------------------------------------------------
    # 1. Geometry
    # ------------------------------------------------------------------
    cube = factory.addBox(0, 0, 0, 1, 1, 1)

    R_center = 0.2
    center_sphere = factory.addSphere(0.5, 0.5, 0.5, R_center)

    R_corner = 0.25
    corner_spheres = []
    for ix in range(2):
        for iy in range(2):
            for iz in range(2):
                s = factory.addSphere(float(ix), float(iy), float(iz), R_corner)
                corner_spheres.append(s)

    # ------------------------------------------------------------------
    # 2. Boolean Fragment — conformal interfaces
    # ------------------------------------------------------------------
    all_objects = [(3, cube)]
    all_tools = [(3, center_sphere)] + [(3, s) for s in corner_spheres]

    ov, ovv = factory.fragment(all_objects, all_tools)

    # ovv[0]  : volumes from the cube (everything inside the cube)
    # ovv[1]  : volumes from center sphere
    # ovv[2:] : volumes from each corner sphere

    cube_children = set(tag for dim, tag in ovv[0] if dim == 3)
    center_children = set(tag for dim, tag in ovv[1] if dim == 3)
    corner_children = set()
    for i in range(2, 2 + len(corner_spheres)):
        for dim, tag in ovv[i]:
            if dim == 3:
                corner_children.add(tag)

    # Classify volumes inside the cube
    center_tags = sorted(center_children & cube_children)
    corner_tags = sorted(corner_children & cube_children)
    matrix_tags = sorted(cube_children - center_children - corner_children)

    # ------------------------------------------------------------------
    # 3. Remove volumes outside the cube — MUST use occ.remove BEFORE
    #    synchronize to ensure orphaned outer sphere surfaces are
    #    properly cleaned up. Using model.removeEntities after sync
    #    leaves orphaned surfaces that break periodic meshing.
    # ------------------------------------------------------------------
    all_vols_occ = factory.getEntities(3)
    outer = [(d, t) for d, t in all_vols_occ if t not in cube_children]
    if outer:
        factory.remove(outer, recursive=True)

    factory.synchronize()

    print(f"Matrix volumes:  {matrix_tags}", flush=True)
    print(f"Center volumes:  {center_tags}", flush=True)
    print(f"Corner volumes:  {corner_tags}", flush=True)

    # ------------------------------------------------------------------
    # 4. Physical Groups
    # ------------------------------------------------------------------
    gmsh.model.addPhysicalGroup(3, matrix_tags, name="Matrix")
    gmsh.model.addPhysicalGroup(3, center_tags, name="CenterInclusion")
    gmsh.model.addPhysicalGroup(3, corner_tags, name="CornerInclusion")

    # ------------------------------------------------------------------
    # 5. Size Fields
    # ------------------------------------------------------------------
    # Collect all surfaces bounding inclusions
    all_incl_tags = center_tags + corner_tags
    incl_surfs = set()
    for tag in all_incl_tags:
        bnd = gmsh.model.getBoundary([(3, tag)], oriented=False)
        for bdim, btag in bnd:
            incl_surfs.add(abs(btag))

    # Identify surfaces lying on the cube faces (not inclusion-matrix interfaces)
    eps_bb = 5e-3
    cube_face_surfs = set()
    for axis in range(3):
        for val in [0.0, 1.0]:
            lo = [-eps_bb, -eps_bb, -eps_bb]
            hi = [1 + eps_bb, 1 + eps_bb, 1 + eps_bb]
            if val < 0.5:
                hi[axis] = eps_bb
            else:
                lo[axis] = 1 - eps_bb
            surfs = gmsh.model.getEntitiesInBoundingBox(
                lo[0], lo[1], lo[2], hi[0], hi[1], hi[2], 2
            )
            for dim, tag in surfs:
                cube_face_surfs.add(tag)

    # Interface surfaces = inclusion surfaces NOT on cube faces
    interface_surfs = sorted(incl_surfs - cube_face_surfs)
    print(f"Interface surfaces for size field: {len(interface_surfs)}", flush=True)

    # Global mesh size bounds
    gmsh.option.setNumber("Mesh.MeshSizeMin", 0.04)
    gmsh.option.setNumber("Mesh.MeshSizeMax", 0.2)

    if interface_surfs:
        dis = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(dis, "SurfacesList", interface_surfs)

        thresh = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(thresh, "InField", dis)
        gmsh.model.mesh.field.setNumber(thresh, "SizeMin", 0.06)
        gmsh.model.mesh.field.setNumber(thresh, "SizeMax", 0.15)
        gmsh.model.mesh.field.setNumber(thresh, "DistMin", 0.01)
        gmsh.model.mesh.field.setNumber(thresh, "DistMax", 0.3)
        gmsh.model.mesh.field.setAsBackgroundMesh(thresh)

    # Disable size constraints from CAD model points/curvature
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)

    # ------------------------------------------------------------------
    # 6. Periodic Constraints — match opposite face pairs
    # ------------------------------------------------------------------
    gmsh.option.setNumber("Geometry.OCCBoundsUseStl", 1)

    eps_p = 5e-3
    for direction in range(3):
        translate = [0.0, 0.0, 0.0]
        translate[direction] = 1.0

        # Bounding box for the "min" face of this axis
        lo = [-eps_p, -eps_p, -eps_p]
        hi = [1 + eps_p, 1 + eps_p, 1 + eps_p]
        hi[direction] = eps_p

        Smin = gmsh.model.getEntitiesInBoundingBox(
            lo[0], lo[1], lo[2], hi[0], hi[1], hi[2], 2
        )

        matched_count = 0
        filtered_count = 0
        for _, tag_s in Smin:
            bb = gmsh.model.getBoundingBox(2, tag_s)

            # Filter: skip surfaces that extend significantly away from the face
            extent_in_dir = bb[direction + 3] - bb[direction]
            if extent_in_dir > 0.05:
                continue
            filtered_count += 1

            # Search for the matching surface on the opposite face
            Smax = gmsh.model.getEntitiesInBoundingBox(
                bb[0] - eps_p + translate[0],
                bb[1] - eps_p + translate[1],
                bb[2] - eps_p + translate[2],
                bb[3] + eps_p + translate[0],
                bb[4] + eps_p + translate[1],
                bb[5] + eps_p + translate[2],
                2,
            )

            for _, tag_m in Smax:
                bb2 = gmsh.model.getBoundingBox(2, tag_m)
                ok = True
                for i in range(3):
                    if abs((bb2[i] - translate[i]) - bb[i]) > eps_p:
                        ok = False
                        break
                    if abs((bb2[i + 3] - translate[i]) - bb[i + 3]) > eps_p:
                        ok = False
                        break
                if ok:
                    try:
                        gmsh.model.mesh.setPeriodic(
                            2,
                            [tag_m],
                            [tag_s],
                            [
                                1, 0, 0, translate[0],
                                0, 1, 0, translate[1],
                                0, 0, 1, translate[2],
                                0, 0, 0, 1,
                            ],
                        )
                        matched_count += 1
                    except Exception as e:
                        print(f"Warning: setPeriodic({tag_s}->{tag_m}) axis {direction}: {e}",
                              flush=True)
                    break

        print(f"Axis {direction}: matched {matched_count}/{filtered_count} periodic surface pairs",
              flush=True)

    # ------------------------------------------------------------------
    # 7. Mesh Generation & Optimization
    # ------------------------------------------------------------------
    gmsh.option.setNumber("Mesh.Algorithm3D", 1)        # Delaunay
    gmsh.option.setNumber("Mesh.ElementOrder", 1)        # linear tets
    gmsh.option.setNumber("Mesh.Smoothing", 3)
    gmsh.option.setNumber("Mesh.Optimize", 1)
    gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)
    gmsh.option.setNumber("Mesh.OptimizeThreshold", 0.2)

    print("Starting 3D mesh generation...", flush=True)
    gmsh.model.mesh.generate(3)
    print("3D mesh generation complete.", flush=True)

    # ------------------------------------------------------------------
    # 8. Output
    # ------------------------------------------------------------------
    gmsh.option.setNumber("Mesh.MshFileVersion", 4.1)
    gmsh.option.setNumber("Mesh.SaveAll", 0)
    gmsh.write("/app/rve.msh")

    # Print quality statistics
    types_3d, tags_3d, _ = gmsh.model.mesh.getElements(3)
    all_elem = []
    for t in tags_3d:
        all_elem.extend(t.tolist())
    if all_elem:
        qualities = gmsh.model.mesh.getElementQualities(all_elem)
        print(f"Elements: {len(all_elem)}", flush=True)
        print(f"Min SICN:  {min(qualities):.6f}", flush=True)
        print(f"Mean SICN: {sum(qualities)/len(qualities):.6f}", flush=True)

    gmsh.finalize()
    print("Done — mesh written to /app/rve.msh", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL ERROR: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        try:
            gmsh.finalize()
        except Exception:
            pass
        sys.exit(1)
    sys.exit(0)
