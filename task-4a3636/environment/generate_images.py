#!/usr/bin/env python3
"""Generate synthetic fingerprint-like test images for NFIQ2 feature extraction task."""
import math
import struct
import random
import os

def write_pgm(filename, width, height, pixels):
    """Write a PGM P5 (binary grayscale) file."""
    with open(filename, 'wb') as f:
        f.write(f'P5\n{width} {height}\n255\n'.encode())
        for row in pixels:
            for val in row:
                f.write(struct.pack('B', max(0, min(255, int(round(val))))))

def gen_uniform(width=320, height=320):
    """Horizontal sinusoidal ridges, period=16, amplitude=100, offset=128."""
    pixels = []
    for y in range(height):
        row = []
        for x in range(width):
            val = 128.0 + 100.0 * math.sin(2.0 * math.pi * y / 16.0)
            row.append(val)
        pixels.append(row)
    return pixels

def gen_diagonal(width=320, height=320):
    """45-degree diagonal ridges, spatial period=16 perpendicular to ridges."""
    P = 16.0 * math.sqrt(2.0)
    pixels = []
    for y in range(height):
        row = []
        for x in range(width):
            val = 128.0 + 100.0 * math.sin(2.0 * math.pi * (x + y) / P)
            row.append(val)
        pixels.append(row)
    return pixels

def gen_degraded(width=320, height=320):
    """Top half horizontal ridges, bottom half vertical ridges, with noise."""
    random.seed(42)
    pixels = []
    half = height // 2
    for y in range(height):
        row = []
        for x in range(width):
            if y < half:
                val = 128.0 + 80.0 * math.sin(2.0 * math.pi * y / 16.0)
            else:
                val = 128.0 + 80.0 * math.sin(2.0 * math.pi * x / 16.0)
            val += random.gauss(0, 30.0)
            row.append(val)
        pixels.append(row)
    return pixels

if __name__ == '__main__':
    os.makedirs('/app/images', exist_ok=True)
    write_pgm('/app/images/uniform.pgm', 320, 320, gen_uniform())
    write_pgm('/app/images/diagonal.pgm', 320, 320, gen_diagonal())
    write_pgm('/app/images/degraded.pgm', 320, 320, gen_degraded())
    print("Generated 3 test images in /app/images/")
