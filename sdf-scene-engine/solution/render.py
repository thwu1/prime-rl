#!/usr/bin/env python3
"""Render a depth-map PGM from an SDF scene.

"""

import json
import math
import sys

sys.path.insert(0, '/solution')
from engine import evaluate, vnorm, vadd, vmuls, vsub, v3, vcross


def main():
    scene_path = sys.argv[1] if len(sys.argv) > 1 else "/app/scene.json"
    camera_path = sys.argv[2] if len(sys.argv) > 2 else "/app/camera.json"
    output_path = sys.argv[3] if len(sys.argv) > 3 else "/app/render.pgm"

    with open(scene_path) as f:
        scene = json.load(f)
    with open(camera_path) as f:
        cam = json.load(f)

    root = scene["root"]
    eye = tuple(cam["eye"])
    target = tuple(cam["target"])
    up = tuple(cam["up"])
    fov = cam["fov_deg"]
    width = cam["width"]
    height = cam["height"]
    max_t = cam["max_t"]
    eps = cam["epsilon"]
    bg = cam["background_value"]

    # Camera matrix
    forward = vnorm(vsub(target, eye))
    right = vnorm(vcross(forward, up))
    cam_up = vcross(right, forward)

    half_fov_tan = math.tan(math.radians(fov / 2.0))

    pixels = []
    for row in range(height):
        if row % 32 == 0:
            print(f"  Rendering row {row}/{height}...", file=sys.stderr)
        for col in range(width):
            ndc_x = (2.0 * (col + 0.5) / width - 1.0) * half_fov_tan
            ndc_y = (1.0 - 2.0 * (row + 0.5) / height) * half_fov_tan

            d = vnorm(vadd(vadd(forward, vmuls(right, ndc_x)),
                           vmuls(cam_up, ndc_y)))

            # Ray march
            t = 0.0
            hit = False
            for _ in range(2000):
                pt = vadd(eye, vmuls(d, t))
                dist = evaluate(root, pt)
                if abs(dist) < eps:
                    hit = True
                    break
                if t > max_t:
                    break
                t += max(dist, eps * 0.5)

            if hit:
                pixel_val = round(min(t / max_t, 1.0) * 255)
            else:
                pixel_val = bg
            pixels.append(pixel_val)

    # Write PGM P2
    with open(output_path, 'w') as f:
        f.write("P2\n")
        f.write(f"{width} {height}\n")
        f.write("255\n")
        for row in range(height):
            start = row * width
            f.write(" ".join(str(pixels[start + c]) for c in range(width)))
            f.write("\n")

    print(f"Wrote {width}x{height} PGM to {output_path}")


if __name__ == "__main__":
    main()
