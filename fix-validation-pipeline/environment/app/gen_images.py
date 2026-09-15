#!/usr/bin/env python3
"""Generate synthetic PPM test images for validation."""
import os

os.makedirs("images", exist_ok=True)

for i in range(1, 6):
    w, h = 8, 8
    pixels = bytearray()
    for y in range(h):
        for x in range(w):
            r = ((i * 37 + x * 13 + y * 7) % 256)
            g = ((i * 53 + x * 11 + y * 23) % 256)
            b = ((i * 71 + x * 17 + y * 31) % 256)
            pixels.extend([r, g, b])

    with open(f"images/img{i:03d}.ppm", "wb") as f:
        header = f"P6\n{w} {h}\n255\n"
        f.write(header.encode("ascii"))
        f.write(bytes(pixels))
    print(f"Generated images/img{i:03d}.ppm ({w}x{h})")
