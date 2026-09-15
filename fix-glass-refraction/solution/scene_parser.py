#!/usr/bin/env python3
"""
YAML scene parser for the ray tracer.
Parses camera, light, materials (with extend inheritance),
and object trees (sphere, plane, cube, cylinder, group, csg).
"""

import yaml
import sys
sys.path.insert(0, '/app')
from rt import *


def parse_scene(filepath):
    """Parse a YAML scene file and return (Camera, World)."""
    with open(filepath) as f:
        scene = yaml.safe_load(f)

    # Camera
    cd = scene['camera']
    camera = Camera(cd['width'], cd['height'], cd['field_of_view'])
    camera.transform = view_transform(
        point(*cd['from']), point(*cd['to']), vector(*cd['up'])
    )

    # Light
    ld = scene['light']
    light = PointLight(point(*ld['position']), color(*ld['intensity']))

    # Materials
    mat_defs = {}
    if 'materials' in scene:
        for name, md in scene['materials'].items():
            mat_defs[name] = _resolve_material(md, mat_defs)

    # World
    world = World()
    world.light = light
    for od in scene['objects']:
        world.objects.append(_parse_shape(od, mat_defs))

    return camera, world


def _resolve_material(md, defs):
    """Build a Material, optionally inheriting from a parent via 'extend'."""
    mat = Material()
    if 'extend' in md:
        parent = defs[md['extend']]
        mat.color = color(parent.color.x, parent.color.y, parent.color.z)
        mat.ambient = parent.ambient
        mat.diffuse = parent.diffuse
        mat.specular = parent.specular
        mat.shininess = parent.shininess
        mat.reflective = parent.reflective
        mat.transparency = parent.transparency
        mat.refractive_index = parent.refractive_index
    _apply_material_fields(mat, md)
    return mat


def _apply_material_fields(mat, md):
    """Override material fields from a dict."""
    if 'color' in md:
        mat.color = color(*md['color'])
    if 'ambient' in md:
        mat.ambient = md['ambient']
    if 'diffuse' in md:
        mat.diffuse = md['diffuse']
    if 'specular' in md:
        mat.specular = md['specular']
    if 'shininess' in md:
        mat.shininess = md['shininess']
    if 'reflective' in md:
        mat.reflective = md['reflective']
    if 'transparency' in md:
        mat.transparency = md['transparency']
    if 'refractive_index' in md:
        mat.refractive_index = md['refractive_index']


def _parse_material_ref(ref, defs):
    """Resolve a material reference: string name or inline dict."""
    if isinstance(ref, str):
        return defs[ref]
    elif isinstance(ref, dict):
        return _resolve_material(ref, defs)
    return Material()


def _parse_transform_list(tlist):
    """Build a combined transform matrix from a list of [op, args...].
    Transforms are applied innermost-first: the first in the list is
    applied first (closest to the object)."""
    result = identity_matrix()
    for t in tlist:
        op = t[0]
        if op == 'translate':
            mat = translation(t[1], t[2], t[3])
        elif op == 'scale':
            mat = scaling(t[1], t[2], t[3])
        elif op == 'rotate_x':
            mat = rotation_x(t[1])
        elif op == 'rotate_y':
            mat = rotation_y(t[1])
        elif op == 'rotate_z':
            mat = rotation_z(t[1])
        else:
            raise ValueError(f"Unknown transform op: {op}")
        result = mat * result
    return result


def _parse_shape(data, mat_defs):
    """Recursively parse a shape definition."""
    stype = data['type']

    if stype == 'sphere':
        shape = Sphere()
    elif stype == 'plane':
        shape = Plane()
    elif stype == 'cube':
        shape = Cube()
    elif stype == 'cylinder':
        shape = Cylinder()
        if 'min' in data:
            shape.minimum = data['min']
        if 'max' in data:
            shape.maximum = data['max']
        if 'closed' in data:
            shape.closed = data['closed']
    elif stype == 'group':
        shape = Group()
        for child in data.get('children', []):
            shape.add_child(_parse_shape(child, mat_defs))
    elif stype == 'csg':
        left = _parse_shape(data['left'], mat_defs)
        right = _parse_shape(data['right'], mat_defs)
        shape = CSG(data['operation'], left, right)
    else:
        raise ValueError(f"Unknown shape type: {stype}")

    if 'transform' in data:
        shape.transform = _parse_transform_list(data['transform'])
        shape._inverse = None

    if 'material' in data:
        shape.material = _parse_material_ref(data['material'], mat_defs)

    return shape
