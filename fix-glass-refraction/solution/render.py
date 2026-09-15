#!/usr/bin/env python3
"""Render the YAML scene to /app/output.ppm."""

import sys
sys.path.insert(0, '/app')
from scene_parser import parse_scene
from rt import render

camera, world = parse_scene('/app/scene.yaml')
print(f"Rendering {camera.hsize}x{camera.vsize} scene "
      f"({len(world.objects)} top-level objects)...")
image = render(camera, world)
with open('/app/output.ppm', 'w') as f:
    f.write(image.to_ppm())
print("Saved to /app/output.ppm")
