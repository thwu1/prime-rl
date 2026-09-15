#!/usr/bin/env python3
"""
Fix four interacting bugs in the ray tracer's refraction pipeline.

Bug 1 (prepare_computations): containers.pop(0) removes the wrong object
       from the container stack when tracking n1/n2 through nested geometry.
       Fix: containers.remove(obj)

Bug 2 (refracted_color): cos_t = 1.0 - sin2_t is wrong; Snell's law requires
       cos_t = sqrt(1 - sin2_t).
       Fix: cos_t = math.sqrt(1.0 - sin2_t)

Bug 3 (schlick): When n1 > n2, the Schlick approximation must use cos(theta_t)
       instead of cos(theta_i). The cos_t computation and substitution are missing.
       Fix: add cos_t = math.sqrt(1.0 - sin2_t) and cos = cos_t

Bug 4 (shade_hit): When a material is both reflective and transparent, the
       reflected and refracted contributions must be weighted by the Schlick
       reflectance, not simply added.
       Fix: apply schlick weighting
"""

import sys

with open('/app/rt.py', 'r') as f:
    code = f.read()

# Bug 1: Fix container tracking in prepare_computations
code = code.replace(
    'containers.pop(0)',
    'containers.remove(obj)'
)

# Bug 2: Fix Snell's law cos_t computation in refracted_color
code = code.replace(
    'cos_t = 1.0 - sin2_t',
    'cos_t = math.sqrt(1.0 - sin2_t)'
)

# Bug 3: Add cos_t substitution in schlick for n1 > n2 case
code = code.replace(
    '''\
        if sin2_t > 1.0:
            return 1.0

    r0 = ((comps.n1 - comps.n2) / (comps.n1 + comps.n2))**2''',
    '''\
        if sin2_t > 1.0:
            return 1.0
        cos_t = math.sqrt(1.0 - sin2_t)
        cos = cos_t

    r0 = ((comps.n1 - comps.n2) / (comps.n1 + comps.n2))**2'''
)

# Bug 4: Apply Schlick weighting in shade_hit for reflective+transparent materials
code = code.replace(
    '''\
    return surface + reflected + refracted''',
    '''\
    material = comps.object.material
    if material.reflective > 0 and material.transparency > 0:
        reflectance = schlick(comps)
        return surface + reflected * reflectance + refracted * (1 - reflectance)
    return surface + reflected + refracted'''
)

with open('/app/rt.py', 'w') as f:
    f.write(code)

print("All 4 refraction bugs fixed.")
