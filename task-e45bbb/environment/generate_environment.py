"""Generate warehouse environment data in ROS2 map_server format during Docker build."""

import numpy as np
import os

os.makedirs('/app/map', exist_ok=True)

# Create 50x50 occupancy grid (internal: 0=free, 100=occupied)
grid = np.zeros((50, 50), dtype=np.int8)

# Perimeter walls
grid[0, :] = 100
grid[49, :] = 100
grid[:, 0] = 100
grid[:, 49] = 100

# Horizontal barrier 1: rows 15-16, cols 5-34 (gap at cols 35-48)
grid[15:17, 5:35] = 100

# Horizontal barrier 2: rows 33-34, cols 15-44 (gap at cols 1-14)
grid[33:35, 15:45] = 100

# Obstacle block: rows 23-26, cols 23-26
grid[23:27, 23:27] = 100

# Small obstacles
grid[8:10, 20:22] = 100
grid[40:42, 35:37] = 100

# Convert to PGM pixel values
# ROS2 map_server convention (negate=0):
#   occupied -> pixel 0 (black), free -> pixel 254 (near-white)
height, width = grid.shape
pgm_pixels = np.full((height, width), 254, dtype=np.uint8)
pgm_pixels[grid >= 65] = 0

# PGM stores top-to-bottom; our grid has row 0 as map bottom
pgm_flipped = np.flipud(pgm_pixels)

# Write P5 (binary) PGM file
with open('/app/map/warehouse.pgm', 'wb') as f:
    header = "P5\n{} {}\n255\n".format(width, height).encode('ascii')
    f.write(header)
    f.write(pgm_flipped.tobytes())

# Write map metadata YAML (ROS2 map_server format)
yaml_content = """\
image: warehouse.pgm
resolution: 0.1
origin: [-2.5, -2.5, 0.0]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.196
"""

with open('/app/map/warehouse.yaml', 'w') as f:
    f.write(yaml_content)

print("Map generated: {}x{}, {} occupied cells".format(
    width, height, int(np.sum(grid >= 65))))
