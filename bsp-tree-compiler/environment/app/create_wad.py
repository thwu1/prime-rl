#!/usr/bin/env python3
"""Creates /app/map.wad binary file from hardcoded map data."""
import struct

vertices = [
    (0, 0), (300, 0), (300, 60), (300, 140), (300, 200),
    (0, 200), (380, 60), (380, 140), (380, 0), (600, 0),
    (600, 120), (520, 200), (380, 200), (100, 200), (200, 200),
    (100, 280), (200, 280), (0, 280), (300, 280), (0, 420), (300, 420),
]

linedefs = [
    (0, 0, 1, 0, -1), (1, 1, 2, 0, -1), (2, 2, 3, 0, 1),
    (3, 3, 4, 0, -1), (4, 4, 14, 0, -1), (5, 14, 13, 0, 2),
    (6, 13, 5, 0, -1), (7, 5, 0, 0, -1), (8, 2, 6, 1, -1),
    (9, 6, 7, 1, 3), (10, 7, 3, 1, -1), (11, 8, 9, 3, -1),
    (12, 9, 10, 3, -1), (13, 10, 11, 3, -1), (14, 11, 12, 3, -1),
    (15, 6, 8, 3, -1), (16, 12, 7, 3, -1), (17, 13, 15, 2, -1),
    (18, 15, 16, 2, 4), (19, 16, 14, 2, -1), (20, 17, 15, 4, -1),
    (21, 16, 18, 4, -1), (22, 18, 20, 4, -1), (23, 20, 19, 4, -1),
    (24, 19, 17, 4, -1),
]

sectors = [
    (0, "Main Hall"), (1, "East Corridor"), (2, "North Passage"),
    (3, "East Wing"), (4, "North Room"),
]

viewpoints = [
    (150, 100), (490, 100), (150, 350), (340, 100), (150, 240), (50, 50),
]

vert_data = b''.join(struct.pack('<ii', x, y) for x, y in vertices)
line_data = b''.join(
    struct.pack('<iiihh', lid, v1, v2, fs, bs)
    for lid, v1, v2, fs, bs in linedefs
)
sect_data = b''.join(
    struct.pack('<i16s', sid, name.encode('ascii').ljust(16, b'\x00')[:16])
    for sid, name in sectors
)
view_data = b''.join(struct.pack('<ii', x, y) for x, y in viewpoints)

lumps = [
    ('VERTEXES', vert_data),
    ('LINEDEFS', line_data),
    ('SECTORS', sect_data),
    ('VIEWPNTS', view_data),
]

header_size = 12
current_offset = header_size
all_data = b''
entries = []

for name, data in lumps:
    entries.append((current_offset, len(data), name))
    all_data += data
    current_offset += len(data)

dir_offset = current_offset

with open('/app/map.wad', 'wb') as f:
    f.write(struct.pack('<4sii', b'PWAD', len(lumps), dir_offset))
    f.write(all_data)
    for offset, size, name in entries:
        f.write(struct.pack('<ii8s', offset, size,
                name.encode('ascii').ljust(8, b'\x00')[:8]))

print(f"Created /app/map.wad ({12 + len(all_data) + len(entries)*16} bytes)")
