#!/usr/bin/env python3
"""Diagnostic tool: renders a test scene with glass objects and prints pixel colors."""
import sys
import math
sys.path.insert(0, '/app')
from rt import *

w = World()
w.light = PointLight(point(-10, 10, -10), color(1, 1, 1))

floor = Plane()
floor.material.color = color(1, 0.9, 0.9)
floor.material.specular = 0
floor.material.reflective = 0.4
floor.material.transparency = 0.3
floor.material.refractive_index = 1.3
w.objects.append(floor)

ball = glass_sphere()
ball.transform = translation(0, 1, 0)
ball.material.color = color(0, 0, 0)
ball.material.ambient = 0
ball.material.diffuse = 0
ball.material.specular = 0.9
ball.material.shininess = 300
ball.material.reflective = 0.9
ball.material.transparency = 0.9
ball.material.refractive_index = 1.5
w.objects.append(ball)

red = Sphere()
red.transform = translation(0, 1, 3) * scaling(0.5, 0.5, 0.5)
red.material.color = color(1, 0, 0)
red.material.ambient = 0.5
w.objects.append(red)

cam = Camera(20, 20, math.pi / 3)
cam.transform = view_transform(
    point(0, 1.5, -5),
    point(0, 1, 0),
    vector(0, 1, 0)
)

print("Rendering 20x20 diagnostic scene...")
image = render(cam, w)

test_pixels = [(10, 10), (10, 8), (5, 10), (15, 10), (10, 15)]
for x, y in test_pixels:
    p = image.pixel_at(x, y)
    print(f"pixel({x},{y}) = ({p.x:.5f}, {p.y:.5f}, {p.z:.5f})")

print("Done.")
