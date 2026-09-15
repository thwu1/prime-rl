"""
Conway Polyhedron Operator Pipeline.

Implements dual, ambo (rectification), truncate, and kis (kleetope)
Conway operators as BMesh topology transformations. Reads a target
specification from /app/targets.json, generates each polyhedron by
composing operator chains on an icosahedral seed, computes geometric
analysis, assigns materials, renders, and exports.

Run with: xvfb-run -a blender --background --python conway_pipeline.py

"""

import bpy
import bmesh
import json
import os
import math
from mathutils import Vector


# ═══════════════════════════════════════════════
# Utility: BMesh loop traversal
# ═══════════════════════════════════════════════

def ordered_faces_around_vert(v):
    """
    Return faces around vertex v in consistent winding order.
    Uses BMesh loop traversal: link_loop_prev crosses to the
    edge entering v in the current face, then link_loop_radial_next
    crosses that edge to the adjacent face (landing at v due to
    opposite winding in the adjacent face for manifold meshes).
    """
    if not v.link_loops:
        return []
    start = v.link_loops[0]
    result = []
    current = start
    for _ in range(len(v.link_faces)):
        result.append(current.face)
        current = current.link_loop_prev.link_loop_radial_next
        if current == start:
            break
    return result


def ordered_edges_around_vert(v):
    """
    Return edges leaving vertex v in consistent face-ring order.
    Each loop at v stores the edge from v to the next vertex in
    that face. Traversing the face ring yields one edge per face.
    """
    if not v.link_loops:
        return []
    start = v.link_loops[0]
    result = []
    current = start
    for _ in range(len(v.link_edges)):
        result.append(current.edge)
        current = current.link_loop_prev.link_loop_radial_next
        if current == start:
            break
    return result


def ensure_outward_normals(bm):
    """Recalculate face normals to point outward for a closed mesh."""
    bm.faces.ensure_lookup_table()
    try:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    except Exception:
        # Fallback: flip faces whose normals point inward
        bm.normal_update()
        centroid = Vector((0, 0, 0))
        for v in bm.verts:
            centroid += v.co
        if len(bm.verts) > 0:
            centroid /= len(bm.verts)
        for f in bm.faces:
            outward = f.calc_center_median() - centroid
            if outward.dot(f.normal) < 0:
                f.normal_flip()
    bm.normal_update()


# ═══════════════════════════════════════════════
# Conway Operators
# ═══════════════════════════════════════════════

def op_dual(bm_in):
    """
    Conway dual: swap vertices and faces.
    - One new vertex per original face (at centroid).
    - One new face per original vertex (connecting centroids
      of the surrounding faces in face-ring order).
    """
    bm = bmesh.new()

    face_to_vert = {}
    for f in bm_in.faces:
        v = bm.verts.new(f.calc_center_median())
        face_to_vert[f.index] = v

    bm.verts.ensure_lookup_table()

    for v in bm_in.verts:
        ring = ordered_faces_around_vert(v)
        if len(ring) >= 3:
            new_face_verts = [face_to_vert[f.index] for f in ring]
            try:
                bm.faces.new(new_face_verts)
            except ValueError:
                pass

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    ensure_outward_normals(bm)
    return bm


def op_ambo(bm_in):
    """
    Conway ambo (rectification): vertices at edge midpoints.
    - One new vertex per original edge (at midpoint).
    - One new face per original face (connecting midpoints of its edges in loop order).
    - One new face per original vertex (connecting midpoints of its edges in ring order).
    """
    bm = bmesh.new()

    edge_to_vert = {}
    for e in bm_in.edges:
        mid = (e.verts[0].co + e.verts[1].co) / 2.0
        edge_to_vert[e.index] = bm.verts.new(mid)

    bm.verts.ensure_lookup_table()

    # Face-derived faces: one per original face
    for f in bm_in.faces:
        loops = list(f.loops)
        verts = [edge_to_vert[loop.edge.index] for loop in loops]
        try:
            bm.faces.new(verts)
        except ValueError:
            pass

    # Vertex-derived faces: one per original vertex
    for v in bm_in.verts:
        edges = ordered_edges_around_vert(v)
        if len(edges) >= 3:
            verts = [edge_to_vert[e.index] for e in edges]
            try:
                bm.faces.new(verts)
            except ValueError:
                pass

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    ensure_outward_normals(bm)
    return bm


def op_truncate(bm_in):
    """
    Conway truncate: cut off each vertex.
    - Two new vertices per original edge (at 1/3 from each endpoint).
    - One new n-gon face per original vertex of degree n.
    - One new 2n-gon face per original n-gon face.
    """
    bm = bmesh.new()

    # Create two vertices per edge, keyed by (edge_index, vertex_index)
    ev = {}
    for e in bm_in.edges:
        v0, v1 = e.verts
        p0 = v0.co.lerp(v1.co, 1.0 / 3.0)
        p1 = v1.co.lerp(v0.co, 1.0 / 3.0)
        ev[(e.index, v0.index)] = bm.verts.new(p0)
        ev[(e.index, v1.index)] = bm.verts.new(p1)

    bm.verts.ensure_lookup_table()

    # Vertex faces: each vertex of degree n becomes an n-gon
    for v in bm_in.verts:
        edges = ordered_edges_around_vert(v)
        if len(edges) >= 3:
            verts = [ev[(e.index, v.index)] for e in edges]
            try:
                bm.faces.new(verts)
            except ValueError:
                pass

    # Face faces: each n-gon becomes a 2n-gon
    # For each loop vertex vi, add: vertex on previous edge near vi,
    # then vertex on current edge near vi.
    for f in bm_in.faces:
        loops = list(f.loops)
        face_verts = []
        for loop in loops:
            vi = loop.vert
            prev_edge = loop.link_loop_prev.edge
            curr_edge = loop.edge
            face_verts.append(ev[(prev_edge.index, vi.index)])
            face_verts.append(ev[(curr_edge.index, vi.index)])
        try:
            bm.faces.new(face_verts)
        except ValueError:
            pass

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    ensure_outward_normals(bm)
    return bm


def op_kis(bm_in):
    """
    Conway kis (kleetope): raise a pyramid on each face.
    - All original vertices are preserved.
    - One new apex vertex per original face (projected to circumsphere).
    - Each n-gon face is replaced by n triangles.
    """
    bm = bmesh.new()

    # Copy original vertices
    vert_map = {}
    for v in bm_in.verts:
        vert_map[v.index] = bm.verts.new(v.co.copy())

    bm.verts.ensure_lookup_table()

    # Compute average vertex radius for circumsphere projection
    avg_r = sum(v.co.length for v in bm_in.verts) / max(len(bm_in.verts), 1)

    # For each face, add apex and fan triangles
    for f in bm_in.faces:
        center = f.calc_center_median()
        if center.length > 1e-8:
            apex_pos = center.normalized() * avg_r
        else:
            apex_pos = center + f.normal.normalized() * 0.5
        apex = bm.verts.new(apex_pos)

        verts = list(f.verts)
        for i in range(len(verts)):
            v1 = vert_map[verts[i].index]
            v2 = vert_map[verts[(i + 1) % len(verts)].index]
            try:
                bm.faces.new([v1, v2, apex])
            except ValueError:
                pass

    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    ensure_outward_normals(bm)
    return bm


# ═══════════════════════════════════════════════
# Operator dispatch and chain composition
# ═══════════════════════════════════════════════

OPERATORS = {
    'dual': op_dual,
    'ambo': op_ambo,
    'truncate': op_truncate,
    'kis': op_kis,
}


def create_icosahedron(radius=2.0):
    """Create a regular icosahedron (12V, 30E, 20F) via BMesh."""
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=radius)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    return bm


SEEDS = {
    'icosahedron': create_icosahedron,
}


def apply_chain(seed_name, operators):
    """Apply a sequence of Conway operators to a seed polyhedron."""
    bm = SEEDS[seed_name]()
    for op_name in operators:
        new_bm = OPERATORS[op_name](bm)
        bm.free()
        bm = new_bm
    return bm


# ═══════════════════════════════════════════════
# Geometric analysis
# ═══════════════════════════════════════════════

def analyze_bmesh(bm):
    """Compute topological and geometric properties of a BMesh."""
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    V = len(bm.verts)
    E = len(bm.edges)
    F = len(bm.faces)

    # Face-type census
    census = {}
    for f in bm.faces:
        n = len(f.verts)
        key = str(n)
        census[key] = census.get(key, 0) + 1

    euler = V - E + F
    is_manifold = all(e.is_manifold for e in bm.edges)

    # Surface area
    surface_area = sum(f.calc_area() for f in bm.faces)

    # Volume via divergence theorem: V = (1/3) * |Σ (c · n) * A|
    volume = 0.0
    for f in bm.faces:
        c = f.calc_center_median()
        volume += c.dot(f.normal) * f.calc_area()
    volume = abs(volume) / 3.0

    # Edge length statistics
    lengths = [(e.verts[0].co - e.verts[1].co).length for e in bm.edges]
    mean_len = sum(lengths) / len(lengths) if lengths else 0.0
    variance = sum((l - mean_len) ** 2 for l in lengths) / max(len(lengths), 1)
    std_dev = math.sqrt(variance)

    # Face planarity error: max vertex-to-plane distance for non-triangular faces
    max_planarity = 0.0
    for f in bm.faces:
        if len(f.verts) <= 3:
            continue
        normal = f.normal
        center = f.calc_center_median()
        for v in f.verts:
            dist = abs((v.co - center).dot(normal))
            if dist > max_planarity:
                max_planarity = dist

    return {
        'vertex_count': V,
        'edge_count': E,
        'face_count': F,
        'face_type_census': census,
        'euler_characteristic': euler,
        'is_manifold': is_manifold,
        'surface_area': round(surface_area, 6),
        'volume': round(volume, 6),
        'edge_length_std_dev': round(std_dev, 6),
        'max_face_planarity_error': round(max_planarity, 6),
    }


# ═══════════════════════════════════════════════
# Blender scene construction and export
# ═══════════════════════════════════════════════

def bmesh_to_object(bm, name):
    """Convert a BMesh to a Blender object in the current scene."""
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def assign_materials_by_face_type(obj):
    """Assign distinct materials per polygon side-count."""
    mesh = obj.data
    face_types = sorted(set(p.loop_total for p in mesh.polygons))

    palette = [
        (0.15, 0.25, 0.75, 1.0),
        (0.75, 0.20, 0.20, 1.0),
        (0.20, 0.70, 0.25, 1.0),
        (0.80, 0.75, 0.15, 1.0),
        (0.70, 0.20, 0.70, 1.0),
    ]

    type_to_slot = {}
    for i, ft in enumerate(face_types):
        mat = bpy.data.materials.new(name=f"{obj.name}_{ft}gon")
        mat.diffuse_color = palette[i % len(palette)]
        mesh.materials.append(mat)
        type_to_slot[ft] = i

    for poly in mesh.polygons:
        poly.material_index = type_to_slot[poly.loop_total]


def setup_scene(objects):
    """Position objects, add camera and lights, configure render."""
    scene = bpy.context.scene

    # World background
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.05, 0.05, 0.05, 1.0)
        bg.inputs["Strength"].default_value = 1.0
    scene.world = world

    # Arrange objects in a row
    spacing = 5.5
    start_x = -(len(objects) - 1) * spacing / 2.0
    for i, obj in enumerate(objects):
        obj.location = (start_x + i * spacing, 0, 0)

    # Camera
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = 35
    cam_obj = bpy.data.objects.new("Camera", cam_data)
    scene.collection.objects.link(cam_obj)
    cam_obj.location = (0, -20, 7)
    direction = Vector((0, 0, 0)) - cam_obj.location
    cam_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam_obj

    # Sun light
    sun_data = bpy.data.lights.new("Sun", type='SUN')
    sun_data.energy = 3.0
    sun_obj = bpy.data.objects.new("Sun", sun_data)
    scene.collection.objects.link(sun_obj)
    sun_obj.location = (5, 5, 12)

    # Fill light
    fill_data = bpy.data.lights.new("Fill", type='POINT')
    fill_data.energy = 400.0
    fill_obj = bpy.data.objects.new("Fill", fill_data)
    scene.collection.objects.link(fill_obj)
    fill_obj.location = (-6, -12, 5)

    # Render settings
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'MATERIAL'


def export_obj(obj, filepath):
    """Export a single Blender object to OBJ with materials, no triangulation."""
    for o in bpy.data.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    try:
        bpy.ops.wm.obj_export(
            filepath=filepath,
            export_selected_objects=True,
            export_triangulated_mesh=False,
            export_normals=True,
            export_materials=True,
        )
    except (AttributeError, TypeError):
        bpy.ops.export_scene.obj(
            filepath=filepath,
            use_selection=True,
            use_triangles=False,
            use_normals=True,
            use_materials=True,
        )


# ═══════════════════════════════════════════════
# Main pipeline
# ═══════════════════════════════════════════════

def main():
    output_dir = '/app/output'
    os.makedirs(output_dir, exist_ok=True)

    # Load target specification
    with open('/app/targets.json') as f:
        targets = json.load(f)

    # Clear scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    all_analysis = {}
    blender_objects = []

    for target in targets['polyhedra']:
        name = target['name']
        seed = target['construction']['seed']
        ops = target['construction']['operators']

        print(f"Generating {name}: {seed} -> {' -> '.join(ops)}")

        # Generate polyhedron
        bm = apply_chain(seed, ops)

        # Analyze
        analysis = analyze_bmesh(bm)
        all_analysis[name] = analysis

        print(f"  {analysis['vertex_count']}V  {analysis['edge_count']}E  "
              f"{analysis['face_count']}F  euler={analysis['euler_characteristic']}  "
              f"manifold={analysis['is_manifold']}")
        print(f"  census={analysis['face_type_census']}")

        # Convert to Blender object
        obj = bmesh_to_object(bm, name)
        bm.free()

        # Materials
        assign_materials_by_face_type(obj)
        blender_objects.append(obj)

        # Export OBJ (before scene positioning — topology is what matters)
        export_obj(obj, os.path.join(output_dir, f'{name}.obj'))

    # Scene setup and render
    setup_scene(blender_objects)

    bpy.context.scene.render.filepath = os.path.join(output_dir, 'scene_render.png')
    bpy.ops.render.render(write_still=True)

    # Write analysis JSON
    with open(os.path.join(output_dir, 'analysis.json'), 'w') as f:
        json.dump(all_analysis, f, indent=2)

    print("Pipeline complete!")


if __name__ == '__main__':
    main()
