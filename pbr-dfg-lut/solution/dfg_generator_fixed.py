#!/usr/bin/env python3

"""
Fixed dfg_generator.py — corrected LUT generation.

Fixes applied:
1. linear_roughness = coord * coord (was just coord — missing
   perceptual-to-linear roughness squaring)
2. NoV = saturate((x + 0.5) / size) (was x / size — missing
   half-texel center offset)
"""

import json
import math
import struct
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brdf import dfv_multiscatter, dfv_charlie, saturate


def load_config(config_path):
    """Load and validate pipeline configuration from JSON."""
    with open(config_path) as f:
        config = json.load(f)
    required = ["lut_size", "ggx_samples", "charlie_samples", "output_dir"]
    for key in required:
        if key not in config:
            raise KeyError(f"Missing required config key: {key}")
    return config


def generate_lut(config):
    """Generate the full DFG LUT as a flat list of float values."""
    size = config["lut_size"]
    ggx_samples = config["ggx_samples"]
    charlie_samples = config["charlie_samples"]

    pixels = []
    total = size * size
    for y in range(size):
        coord = saturate((size - y + 0.5) / size)
        # FIX: quadratic roughness mapping
        linear_roughness = coord * coord

        for x in range(size):
            # FIX: half-texel center offset
            NoV = saturate((x + 0.5) / size)

            dfg1, dfg2 = dfv_multiscatter(NoV, linear_roughness, ggx_samples)
            charlie = dfv_charlie(NoV, linear_roughness, charlie_samples)
            pixels.extend([dfg1, dfg2, charlie])

        done = (y + 1) * size
        if (y + 1) % 16 == 0 or y == size - 1:
            pct = done * 100.0 / total
            print(f"  Progress: {pct:.0f}% ({done}/{total} pixels)")

    return pixels


def write_lut(pixels, path, size, channels=3):
    """Write the LUT to a binary file with DFGL header."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"DFGL")
        f.write(struct.pack("<III", size, size, channels))
        f.write(struct.pack(f"<{len(pixels)}f", *pixels))
    print(f"Wrote {os.path.getsize(path)} bytes to {path}")


def main():
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "pipeline_config.json"
    )
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    config = load_config(config_path)

    print("DFG LUT Pipeline")
    print(f"  Config: {config_path}")
    print(f"  Size: {config['lut_size']}x{config['lut_size']}")
    print(f"  GGX samples: {config['ggx_samples']}")
    print(f"  Charlie samples: {config['charlie_samples']}")

    pixels = generate_lut(config)

    output_path = os.path.join(config["output_dir"], "dfg_lut.bin")
    write_lut(pixels, output_path, config["lut_size"])
    print("Done.")


if __name__ == "__main__":
    main()
