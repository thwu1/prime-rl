"""
Blender Python pipeline: Generate a truncated icosahedron (C60 buckyball),
assign face-type-specific materials, render, and export geometric analysis.

Run with: xvfb-run -a blender --background --python pipeline.py

"""

import bpy
import bmesh
import json
import os
from mathutils import Vector


def clear_scene():
    """Reset to an empty scene."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def create_truncated_icosahedron():
    """
    Create a truncated icosahedron by truncating a regular icosahedron.

    Start with a regular icosahedron (12V, 30E, 20F) created via BMesh,
    then bevel all vertices at 1/3 of the edge length (PERCENT=33.333).
    Each vertex (degree 5) becomes a pentagon; each triangular face becomes
    a hexagon. Result: 60V, 90E, 32F (12 pentagons + 20 hexagons).
    """
    bm = bmesh.new()

    # subdivisions=1 produces the regular icosahedron (12V, 30E, 20F)
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=2.0)

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    # Truncate: bevel every vertex at 33.33% of each adjacent edge.
    verts_to_bevel = bm.verts[:]
    bmesh.ops.bevel(
        bm,
        geom=verts_to_bevel,
        offset=100.0 / 3.0,
        offset_type='PERCENT',
        segments=1,
        affect='VERTICES',
    )

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    return bm


def analyze_mesh(bm):
    """Compute topological and geometric properties of the BMesh."""
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    num_verts = len(bm.verts)
    num_edges = len(bm.edges)
    num_faces = len(bm.faces)

    pentagon_count = 0
    hexagon_count = 0
    for f in bm.faces:
        n = len(f.verts)
        if n == 5:
            pentagon_count += 1
        elif n == 6:
            hexagon_count += 1

    euler = num_verts - num_edges + num_faces

    is_manifold = all(e.is_manifold for e in bm.edges)

    surface_area = sum(f.calc_area() for f in bm.faces)

    volume = 0.0
    for f in bm.faces:
        center = f.calc_center_median()
        volume += center.dot(f.normal) * f.calc_area()
    volume = abs(volume) / 3.0

    return {
        'vertex_count': num_verts,
        'edge_count': num_edges,
        'face_count': num_faces,
        'pentagon_count': pentagon_count,
        'hexagon_count': hexagon_count,
        'euler_characteristic': euler,
        'is_manifold': is_manifold,
        'surface_area': round(surface_area, 6),
        'volume': round(volume, 6),
    }


def create_materials():
    """Create two Principled BSDF materials for pentagons and hexagons."""
    mat_pent = bpy.data.materials.new(name="PentagonMaterial")
    mat_pent.use_nodes = True
    tree_p = mat_pent.node_tree
    bsdf_p = tree_p.nodes.get("Principled BSDF")
    if bsdf_p is None:
        bsdf_p = tree_p.nodes.new('ShaderNodeBsdfPrincipled')
        out_node = tree_p.nodes.get("Material Output")
        if out_node:
            tree_p.links.new(bsdf_p.outputs["BSDF"], out_node.inputs["Surface"])
    bsdf_p.inputs["Base Color"].default_value = (0.1, 0.1, 0.1, 1.0)
    bsdf_p.inputs["Metallic"].default_value = 0.8
    bsdf_p.inputs["Roughness"].default_value = 0.2
    mat_pent.diffuse_color = (0.1, 0.1, 0.1, 1.0)

    mat_hex = bpy.data.materials.new(name="HexagonMaterial")
    mat_hex.use_nodes = True
    tree_h = mat_hex.node_tree
    bsdf_h = tree_h.nodes.get("Principled BSDF")
    if bsdf_h is None:
        bsdf_h = tree_h.nodes.new('ShaderNodeBsdfPrincipled')
        out_node = tree_h.nodes.get("Material Output")
        if out_node:
            tree_h.links.new(bsdf_h.outputs["BSDF"], out_node.inputs["Surface"])
    bsdf_h.inputs["Base Color"].default_value = (0.9, 0.9, 0.9, 1.0)
    bsdf_h.inputs["Metallic"].default_value = 0.8
    bsdf_h.inputs["Roughness"].default_value = 0.2
    mat_hex.diffuse_color = (0.9, 0.9, 0.9, 1.0)

    return mat_pent, mat_hex


def assign_materials(obj, mat_pent, mat_hex):
    """Assign pentagon material (slot 0) and hexagon material (slot 1)."""
    obj.data.materials.append(mat_pent)   # index 0
    obj.data.materials.append(mat_hex)    # index 1

    for poly in obj.data.polygons:
        if poly.loop_total == 5:
            poly.material_index = 0
        else:
            poly.material_index = 1


def setup_scene(obj):
    """Create world, camera, lights, and configure render settings."""
    scene = bpy.context.scene

    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg_node = world.node_tree.nodes.get("Background")
    if bg_node:
        bg_node.inputs["Color"].default_value = (0.05, 0.05, 0.05, 1.0)
        bg_node.inputs["Strength"].default_value = 1.0
    scene.world = world

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = 50
    cam_obj = bpy.data.objects.new("Camera", cam_data)
    scene.collection.objects.link(cam_obj)
    cam_obj.location = (5.5, -5.5, 3.5)

    direction = Vector((0, 0, 0)) - cam_obj.location
    rot_quat = direction.to_track_quat('-Z', 'Y')
    cam_obj.rotation_euler = rot_quat.to_euler()
    scene.camera = cam_obj

    sun_data = bpy.data.lights.new("Sun", type='SUN')
    sun_data.energy = 3.0
    sun_obj = bpy.data.objects.new("Sun", sun_data)
    scene.collection.objects.link(sun_obj)
    sun_obj.location = (5, 5, 10)

    fill_data = bpy.data.lights.new("Fill", type='POINT')
    fill_data.energy = 150.0
    fill_obj = bpy.data.objects.new("Fill", fill_data)
    scene.collection.objects.link(fill_obj)
    fill_obj.location = (-4, -2, 2)

    scene.render.resolution_x = 640
    scene.render.resolution_y = 480
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.engine = 'BLENDER_WORKBENCH'

    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'MATERIAL'


def export_results(obj, analysis, output_dir):
    """Render image, export OBJ, and write analysis JSON."""
    os.makedirs(output_dir, exist_ok=True)
    scene = bpy.context.scene

    render_path = os.path.join(output_dir, 'render.png')
    scene.render.filepath = render_path
    bpy.ops.render.render(write_still=True)

    obj_path = os.path.join(output_dir, 'polyhedron.obj')

    for o in bpy.data.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    try:
        bpy.ops.wm.obj_export(
            filepath=obj_path,
            export_selected_objects=True,
            export_triangulated_mesh=False,
            export_normals=True,
            export_materials=True,
        )
    except (AttributeError, TypeError):
        bpy.ops.export_scene.obj(
            filepath=obj_path,
            use_selection=True,
            use_triangles=False,
            use_normals=True,
            use_materials=True,
        )

    analysis['material_count'] = len(obj.data.materials)
    json_path = os.path.join(output_dir, 'analysis.json')
    with open(json_path, 'w') as f:
        json.dump(analysis, f, indent=2)

    print(f"Exported to {output_dir}")


def main():
    output_dir = '/app/output'

    clear_scene()

    bm = create_truncated_icosahedron()

    analysis = analyze_mesh(bm)
    print(f"Topology: {analysis['vertex_count']}V {analysis['edge_count']}E "
          f"{analysis['face_count']}F ({analysis['pentagon_count']}P + "
          f"{analysis['hexagon_count']}H), Euler={analysis['euler_characteristic']}, "
          f"manifold={analysis['is_manifold']}")

    mesh = bpy.data.meshes.new("TruncatedIcosahedron")
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new("TruncatedIcosahedron", mesh)
    bpy.context.scene.collection.objects.link(obj)

    for poly in mesh.polygons:
        poly.use_smooth = True

    mat_pent, mat_hex = create_materials()
    assign_materials(obj, mat_pent, mat_hex)

    setup_scene(obj)

    export_results(obj, analysis, output_dir)

    print("Pipeline completed successfully!")


if __name__ == '__main__':
    main()
