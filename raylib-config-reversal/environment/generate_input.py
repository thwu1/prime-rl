#!/usr/bin/env python3
"""Generate a test input image: 200x200 with 4 colored quadrants."""
import struct, zlib, os

WIDTH, HEIGHT = 200, 200

# Quadrant colors (R, G, B):
#   TL (x<100, y<100): pure red    (255,   0,   0)
#   TR (x>=100,y<100): pure green  (  0, 255,   0)
#   BL (x<100,y>=100): pure blue   (  0,   0, 255)
#   BR (x>=100,y>=100):yellow      (255, 255,   0)

raw_rows = []
for y in range(HEIGHT):
    row = b'\x00'  # PNG filter byte: None
    for x in range(WIDTH):
        if x < 100 and y < 100:
            row += b'\xff\x00\x00\xff'
        elif x >= 100 and y < 100:
            row += b'\x00\xff\x00\xff'
        elif x < 100 and y >= 100:
            row += b'\x00\x00\xff\xff'
        else:
            row += b'\xff\xff\x00\xff'
    raw_rows.append(row)

raw_data = b''.join(raw_rows)
compressed = zlib.compress(raw_data)

def make_chunk(chunk_type, data):
    chunk = chunk_type + data
    crc = struct.pack('>I', zlib.crc32(chunk) & 0xffffffff)
    return struct.pack('>I', len(data)) + chunk + crc

png = b'\x89PNG\r\n\x1a\n'
png += make_chunk(b'IHDR', struct.pack('>IIBBBBB', WIDTH, HEIGHT, 8, 6, 0, 0, 0))
png += make_chunk(b'IDAT', compressed)
png += make_chunk(b'IEND', b'')

os.makedirs('/app/input', exist_ok=True)
with open('/app/input/test.png', 'wb') as f:
    f.write(png)

print(f"Generated /app/input/test.png ({WIDTH}x{HEIGHT}, 4 quadrants)")
