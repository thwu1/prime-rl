#!/usr/bin/env python3
"""Generate cross-section data of the SDF scene along the x-axis.

"""

import json
import sys

sys.path.insert(0, '/solution')
from engine import evaluate


def main():
    scene_path = sys.argv[1] if len(sys.argv) > 1 else "/app/scene.json"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "/app/cross_section.dat"

    with open(scene_path) as f:
        scene = json.load(f)

    root = scene["root"]
    n_samples = 500
    x_min, x_max = -3.0, 3.0

    with open(output_path, 'w') as f:
        f.write("# x\tsdf\n")
        for i in range(n_samples):
            x = x_min + i * (x_max - x_min) / (n_samples - 1)
            sdf_val = evaluate(root, (x, 0.0, 0.0))
            f.write(f"{x:.6f}\t{sdf_val:.8f}\n")

    print(f"Wrote {n_samples} samples to {output_path}")


if __name__ == "__main__":
    main()
