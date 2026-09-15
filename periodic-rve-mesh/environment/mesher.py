#!/usr/bin/env python3
"""
RVE mesh generator.
Reads geometry and mesh constraints from rve_config.json.
"""
import json
import gmsh
import sys


def main():
    with open("/app/rve_config.json") as f:
        config = json.load(f)

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1)
    gmsh.model.add("rve")

    occ = gmsh.model.occ

    # --- Domain ---
    origin = config["domain"]["origin"]
    size = config["domain"]["size"]
    box = occ.addBox(origin[0], origin[1], origin[2],
                     size[0], size[1], size[2])

    # --- Inclusions ---
    inclusion_tags = {}
    for inc in config["inclusions"]:
        mat = inc["material"]
        cx, cy, cz = inc["center"]
        r = inc["radius"]

        if inc.get("periodic_images"):
            tags = []
            for ix in range(2):
                for iy in range(2):
                    for iz in range(2):
                        x = origin[0] + ix * size[0]
                        y = origin[1] + iy * size[1]
                        z = origin[2] + iz * size[2]
                        s = occ.addSphere(x, y, z, r)
                        tags.append(s)
            inclusion_tags[mat] = tags
        else:
            s = occ.addSphere(cx, cy, cz, r)
            inclusion_tags[mat] = [s]

    # --- Boolean: subtract inclusions from box ---
    all_inc_dimtags = []
    for tags in inclusion_tags.values():
        all_inc_dimtags.extend([(3, t) for t in tags])

    result, _ = occ.cut(
        [(3, box)], all_inc_dimtags,
        removeObject=True, removeTool=False
    )
    occ.synchronize()

    # --- Physical groups ---
    matrix_vols = [dt[1] for dt in result]
    gmsh.model.addPhysicalGroup(3, matrix_vols,
                                name=config["matrix_material"])

    for mat, tags in inclusion_tags.items():
        gmsh.model.addPhysicalGroup(3, tags, name=mat)

    # --- Mesh size: uniform ---
    mesh_cfg = config["mesh"]
    f1 = gmsh.model.mesh.field.add("MathEval")
    gmsh.model.mesh.field.setString(f1, "F", str(mesh_cfg["bulk_size"]))
    gmsh.model.mesh.field.setAsBackgroundMesh(f1)

    # --- Generate ---
    gmsh.option.setNumber("Mesh.Algorithm3D", 1)
    gmsh.option.setNumber("Mesh.ElementOrder", 1)
    gmsh.model.mesh.generate(3)

    gmsh.option.setNumber("Mesh.MshFileVersion", 4.1)
    gmsh.write(config["output_path"])
    gmsh.finalize()
    print("Done.")


if __name__ == "__main__":
    main()
