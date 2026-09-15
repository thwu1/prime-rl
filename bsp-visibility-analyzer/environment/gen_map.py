#!/usr/bin/env python3
"""Generate BSPMAP2D binary from embedded map data."""
import struct

WALLS = [
    (0, 0, 250, 0), (250, 0, 250, 100), (250, 200, 250, 300),
    (250, 300, 0, 300), (0, 300, 0, 0), (250, 100, 400, 100),
    (250, 200, 400, 200), (400, 0, 650, 0), (650, 0, 650, 300),
    (650, 300, 400, 300), (400, 300, 400, 200), (400, 100, 400, 0),
    (80, 130, 120, 130), (120, 130, 120, 170), (120, 170, 80, 170),
    (80, 170, 80, 130), (500, 30, 620, 250),
]
VIEWPOINTS = [
    (125, 150, 0.0, 90.0), (325, 150, 0.0, 90.0),
    (525, 150, 180.0, 90.0), (125, 50, 45.0, 90.0),
    (560, 60, 90.0, 120.0),
]

out = bytearray()
out += b'BSPMAP2D'
out += struct.pack('<HH', len(WALLS), len(VIEWPOINTS))
out += struct.pack('<I', 0)
for sx, sy, ex, ey in WALLS:
    out += struct.pack('<hhhh', sx, sy, ex, ey)
for x, y, angle, fov in VIEWPOINTS:
    out += struct.pack('<hhff', x, y, angle, fov)

with open('/app/map.bin', 'wb') as f:
    f.write(out)
print(f"Generated map.bin: {len(out)} bytes, {len(WALLS)} walls, {len(VIEWPOINTS)} viewpoints")
